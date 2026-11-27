"""Run independent download jobs and display their measured transfer progress."""

import os
import re
import time
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


def run(jobs, command, draw):
    pending = deque(jobs)
    active = []
    try:
        while pending or active:
            while pending and len(active) < MAX_JOBS:
                job = pending.popleft()
                job.start(command)
                active.append(job)
            for job in active[:]:
                job.sample()
                status = job.process.poll()
                if status is None and time.monotonic() >= job.deadline:
                    job.cancel()
                    status = 124
                if status is not None:
                    job.finish(status)
                    active.remove(job)
            draw(jobs)
            if active:
                time.sleep(0.06)
    finally:
        # Workers own process groups, including curl and Git started by them.
        for job in active:
            job.cancel()
