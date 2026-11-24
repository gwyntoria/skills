"""Run independent download jobs and display their measured transfer progress."""

import os
import re
import sys
import time
import shutil
import signal
import subprocess
from pathlib import Path
from collections import deque
from dataclasses import dataclass


MAX_JOBS = 4
JOB_TIMEOUT = 120
BAR_WIDTH = 20


def transfer_size(headers):
    # curl records proxy handshakes and redirects as well as the final response.
    blocks = re.split(rb"\r?\n\r?\n", headers)
    for block in reversed(blocks):
        if not block.startswith(b"HTTP/"):
            continue
        status, *fields = block.lower().splitlines()
        if not re.match(rb"http/\S+ 2\d\d(?: |$)", status):
            return None
        if b"connection established" in status or any(
            line.startswith(b"transfer-encoding:") for line in fields
        ):
            return None
        for field in fields:
            length = re.fullmatch(rb"content-length:\s*(\d+)\s*", field)
            if length:
                return int(length[1]) or None
        return None
    return None


@dataclass
class Job:
    kind: str
    label: str
    value: str
    ref: str
    directory: Path
    process: subprocess.Popen | None = None
    deadline: float = 0.0
    status: int | None = None
    phase: str = "Loading"
    path: Path | None = None
    received: int = 0
    total: int | None = None

    def start(self, command):
        self.directory.mkdir()
        with (self.directory / "output").open("wb") as output:
            with (self.directory / "error").open("wb") as error:
                self.process = subprocess.Popen(
                    [
                        *command,
                        self.kind,
                        self.value,
                        self.ref,
                        str(self.directory),
                    ],
                    stdout=output,
                    stderr=error,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
        self.deadline = time.monotonic() + JOB_TIMEOUT

    def sample(self):
        try:
            phase, filename = (
                (self.directory / "transfer").read_text().splitlines()
            )
        except (OSError, ValueError):
            return
        path = Path(filename) if filename else None
        if self.path != path or self.phase != phase:
            self.path, self.phase = path, phase
            self.received, self.total = 0, None
        if path is None:
            return
        try:
            self.total = transfer_size(Path(f"{path}.headers").read_bytes())
            self.received = path.stat().st_size
        except FileNotFoundError:
            pass

    def stop(self, sig):
        if self.process is not None:
            try:
                os.killpg(self.process.pid, sig)
            except ProcessLookupError:
                pass

    def cancel(self):
        if self.process is not None:
            self.stop(signal.SIGKILL)
            self.process.wait()

    def finish(self, status):
        self.status = status
        (self.directory / "status").write_text(f"{status}\n")
        if status == 124:
            with (self.directory / "error").open("a") as error:
                error.write(f"Timed out after {JOB_TIMEOUT} seconds.\n")


def job_line(job, label_width, bar_width, width):
    filled = 0
    if job.status == 0:
        filled = bar_width
        detail = "100% Done"
    elif job.process is None:
        detail = "Queued"
    else:
        state = {None: job.phase, 124: "Timed out"}.get(job.status, "Failed")
        if job.total:
            percent = min(100, 100 * job.received // job.total)
            filled = bar_width * percent // 100
            detail = f"{percent:3}% {state}"
        elif job.path is not None:
            detail = f"{job.received:,} B {state}"
        else:
            detail = state
    bar = "#" * filled + "-" * (bar_width - filled)
    return f"{job.label[:label_width]:<{label_width}} [{bar}] {detail}"[:width]


def draw(title, jobs):
    columns, lines = shutil.get_terminal_size()
    columns = max(1, columns - 1)
    done = sum(job.status is not None for job in jobs)
    failed = sum(job.status not in (None, 0) for job in jobs)
    summary = f"{title}  {done}/{len(jobs)} finished"
    if failed:
        summary += f" | {failed} failed"
    summary += " | Ctrl+C Exit"
    # In a short terminal, give visible rows to running jobs first.
    visible = jobs
    if len(jobs) + 2 > lines:
        visible = sorted(
            jobs, key=lambda job: (job.status is not None, job.process is None)
        )
    label_width = min(max(len(job.label) for job in jobs), max(8, columns // 3))
    bar_width = min(BAR_WIDTH, max(4, columns - label_width - 18))
    rows = [summary[:columns], ""]
    rows.extend(
        job_line(job, label_width, bar_width, columns)
        for job in visible[: max(0, lines - 2)]
    )
    sys.stderr.write("\x1b[H" + "\n".join(rows) + "\x1b[J")
    sys.stderr.flush()


def start_jobs(pending, active, command, tty):
    for _ in range(min(MAX_JOBS - len(active), len(pending))):
        job = pending.popleft()
        active.append(job)
        job.start(command)
        if not tty:
            print(f"Loading {job.label}...", file=sys.stderr)


def complete_jobs(active, tty):
    for job in active[:]:
        job.sample()
        status = job.process.poll()
        if status is None and time.monotonic() >= job.deadline:
            job.cancel()
            status = 124
        if status is not None:
            job.finish(status)
            active.remove(job)
            if not tty:
                result = "Done" if status == 0 else "Failed"
                print(f"{job.label}: {result}", file=sys.stderr)


def run(title, jobs, command):
    tty = sys.stderr.isatty() and os.environ.get("TERM", "dumb") != "dumb"
    pending = deque(jobs)
    active = []
    interrupted = None

    def interrupt(sig, _frame):
        nonlocal interrupted
        interrupted = sig

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupt)
    if tty:
        sys.stderr.write("\x1b[?25l")
    try:
        while (pending or active) and interrupted is None:
            start_jobs(pending, active, command, tty)
            complete_jobs(active, tty)
            if tty:
                draw(title, jobs)
            if active:
                time.sleep(0.08)
    finally:
        # Workers use separate process groups so a cancelled curl or Git
        # subprocess cannot outlive the batch and write into its temporary files.
        for job in active:
            job.cancel()
        if tty:
            sys.stderr.write("\x1b[H\x1b[J\x1b[?25h")
            sys.stderr.flush()
    return 128 + interrupted if interrupted else 0


def main():
    title, directory, bash, entry, snapshot, url, *items = sys.argv[1:]
    jobs = [
        Job(*items[index : index + 4], Path(directory, str(index // 4)))
        for index in range(0, len(items), 4)
    ]
    return run(title, jobs, [bash, entry, snapshot, "load-worker", url])


if __name__ == "__main__":
    sys.exit(main())
