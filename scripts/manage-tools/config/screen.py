"""Keyboard navigation and terminal ownership for the config session."""

import os
import re
import curses
import signal
import selectors
import subprocess
import unicodedata

from content.loading import job_line


class Back(Exception):
    pass


class Quit(Exception):
    pass


ENTER = (10, 13, curses.KEY_ENTER)
BACK = (27, ord("b"), ord("B"))
QUIT = (ord("q"), ord("Q"))
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def wrap(text, width):
    if width < 1:
        return [""]
    lines = []
    line = []
    available = width
    for char in ANSI.sub("", str(text)).expandtabs(4):
        if not char.isprintable():
            char = "?"
        cells = (
            0
            if unicodedata.combining(char)
            else 1 + (unicodedata.east_asian_width(char) in "WF")
        )
        if cells > width:
            char, cells = "?", 1
        if cells > available:
            lines.append("".join(line))
            line = []
            available = width
        available -= cells
        line.append(char)
    lines.append("".join(line))
    return lines


def visible(text, width):
    return wrap(text, width)[0]


class Screen:
    def __init__(self, window):
        self.window = window
        # Keep enough time to decode arrow keys without delaying a bare Esc.
        if "ESCDELAY" not in os.environ:
            curses.set_escdelay(50)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def display(self, title, lines, footer, *, cursor=None, offset=0):
        rows, columns = self.window.getmaxyx()
        self.window.erase()
        if rows > 0 and columns > 1:
            self.window.addstr(0, 0, visible(title, columns - 1), curses.A_BOLD)
        if rows > 1 and columns > 1:
            for index, text in enumerate(
                lines[offset : offset + rows - 2], offset
            ):
                style = curses.A_REVERSE if index == cursor else curses.A_NORMAL
                self.window.addstr(
                    index - offset + 1, 0, visible(text, columns - 1), style
                )
            self.window.addstr(
                rows - 1, 0, visible(footer, columns - 1), curses.A_DIM
            )
        self.window.refresh()

    def key(self, delay=-1):
        self.window.timeout(delay)
        return self.window.getch()

    def menu(
        self,
        title,
        lines,
        cursor=0,
        *,
        toggle=None,
        footer=None,
        continue_key=False,
    ):
        def draw():
            return lines() if callable(lines) else lines

        if footer is None:
            footer = "↑↓ Move  Enter Select  Esc Back  q Exit"
            if toggle is not None:
                footer = "↑↓ Move  Space Toggle  a All  n None  Enter Continue  Esc Back  q Exit"
        cursor = min(cursor, len(draw()) - 1)
        offset = 0
        while True:
            height = max(1, self.window.getmaxyx()[0] - 2)
            offset = min(cursor, max(offset, cursor - height + 1))
            labels = draw()
            self.display(
                title,
                labels,
                footer() if callable(footer) else footer,
                cursor=cursor,
                offset=offset,
            )
            key = self.key()
            self.navigate(key)
            cursor = self.move(key, cursor, len(labels))
            if key == ord("c") and continue_key:
                return None
            if key in ENTER or (toggle is not None and key == ord("c")):
                return cursor
            if toggle is not None and key in (ord(" "), ord("a"), ord("n")):
                toggle(key, cursor)

    @staticmethod
    def navigate(key):
        if key in BACK:
            raise Back
        if key in QUIT:
            raise Quit

    @staticmethod
    def move(key, cursor, length):
        if key in (curses.KEY_UP, curses.KEY_DOWN):
            return (cursor + (-1 if key == curses.KEY_UP else 1)) % length
        return {curses.KEY_HOME: 0, curses.KEY_END: length - 1}.get(key, cursor)

    def choose(self, title, labels, default=0):
        return self.menu(title, labels, default)

    def multi(self, title, labels, selected):
        def lines():
            return [
                f"[{'x' if index in selected else ' '}] {label}"
                for index, label in enumerate(labels)
            ]

        def toggle(key, cursor):
            if key == ord(" "):
                selected.symmetric_difference_update({cursor})
            else:
                selected.clear()
                if key == ord("a"):
                    selected.update(range(len(labels)))

        self.menu(title, lines, toggle=toggle)
        return sorted(selected)

    def details(self, lines):
        width = self.window.getmaxyx()[1] - 1
        return [row for line in lines for row in wrap(line, width)]

    def confirm(
        self, title, details, *, action="Apply", default=False, cancel="Cancel"
    ):
        selected = default
        offset = 0
        while True:
            height, width = self.window.getmaxyx()
            if height < 4 or width < 23:
                self.display("Resize terminal", [], "Esc Back  q Exit")
                self.navigate(self.key())
                continue
            footer = f"  {'[ ' + action + ' ]' if selected else action}    "
            footer += f"{cancel if selected else '[ ' + cancel + ' ]'}  ←→ Choose  Enter  Esc Back"
            lines = self.details(details)
            offset = self.scroll(-1, offset, lines)
            self.display(title, lines, footer, offset=offset)
            key = self.key()
            if key in ENTER:
                return selected
            if key in BACK:
                raise Back
            if key in QUIT:
                raise Quit
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
                selected = not selected
            elif key in (ord("y"), ord("Y")):
                return True
            elif key in (ord("n"), ord("N")):
                return False
            offset = self.scroll(key, offset, lines)

    def scroll(self, key, offset, lines):
        step = max(1, self.window.getmaxyx()[0] - 2)
        return max(
            0,
            min(
                max(0, len(lines) - step),
                offset
                + {
                    curses.KEY_UP: -1,
                    curses.KEY_DOWN: 1,
                    curses.KEY_PPAGE: -step,
                    curses.KEY_NPAGE: step,
                }.get(key, 0),
            ),
        )

    def page(self, title, details):
        offset = 0
        while True:
            lines = self.details(details)
            offset = self.scroll(-1, offset, lines)
            self.display(
                title,
                lines,
                "↑↓ Scroll  Enter / Esc Main menu  q Exit",
                offset=offset,
            )
            key = self.key()
            if key in (*BACK, *ENTER):
                return
            if key in QUIT:
                raise Quit
            offset = self.scroll(key, offset, lines)

    def downloads(self, title, jobs, *, cancel=True):
        rows, columns = self.window.getmaxyx()
        ordered = sorted(
            jobs, key=lambda job: (job.status is not None, job.process is None)
        )
        lines = [
            job_line(
                job,
                max(12, columns // 3),
                min(20, max(4, columns // 5)),
                columns,
            )
            for job in ordered[: max(1, rows - 2)]
        ]
        done = sum(job.status is not None for job in jobs)
        footer = "Esc Cancel download  Ctrl+C Exit" if cancel else "Ctrl+C Exit"
        self.display(f"{title}  {done}/{len(jobs)} finished", lines, footer)
        if self.key(0) in BACK and cancel:
            raise Back

    def busy(self, title, lines):
        height = max(0, self.window.getmaxyx()[0] - 2)
        self.display(title, lines[-height:] if height else [], "Ctrl+C Exit")
        self.key(0)

    def native(self, command, *, env=None, cwd=None):
        curses.def_prog_mode()
        curses.endwin()
        try:
            return subprocess.run(command, env=env, cwd=cwd, check=True)
        finally:
            curses.reset_prog_mode()
            self.window.clearok(True)
            self.window.refresh()


def stop_child(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def stream_command(command, progress, *, env=None, cwd=None, stdin=None):
    with (
        subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL if stdin is None else stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process,
        selectors.DefaultSelector() as selector,
    ):
        selector.register(process.stdout, selectors.EVENT_READ)
        chunk = b""
        try:
            while selector.get_map():
                for key, _ in selector.select(0.08):
                    data = os.read(key.fd, 8192)
                    if not data:
                        selector.unregister(key.fileobj)
                        break
                    combined = chunk + data
                    *lines, chunk = (
                        combined.rsplit(b"\n", 1)
                        if b"\n" in combined
                        else (combined,)
                    )
                    for line in lines:
                        progress(line.decode(errors="replace").splitlines())
                    chunk = chunk[-65536:]
                progress([])
                if process.poll() is not None and not selector.select(0):
                    break
            if chunk:
                progress(chunk.decode(errors="replace").splitlines())
            returncode = process.wait()
        except BaseException:
            stop_child(process)
            raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
