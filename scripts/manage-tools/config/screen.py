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
ANSI = re.compile(r"(\x1b\[[0-?]*[ -/]*[@-~])")
COLORS = {
    "31": curses.COLOR_RED,
    "32": curses.COLOR_GREEN,
    "33": curses.COLOR_YELLOW,
    "36": curses.COLOR_CYAN,
}
SGR = {"0", "1", "2", "22", "39", *COLORS}


def paint(code, text):
    return f"\033[{code}m{text}\033[0m"


def selection_mark(picked, total=1):
    if not picked:
        return "[ ]"
    if picked == total:
        return paint("1;32", "[x]")
    return paint("1;33", "[-]")


def chunks(text):
    attrs = curses.A_NORMAL
    color = None
    for index, token in enumerate(ANSI.split(str(text))):
        if index % 2 == 0:
            yield token, attrs, color
        elif token.endswith("m"):
            codes = (token[2:-1] or "0").split(";")
            if not set(codes) <= SGR:
                continue
            for code in codes:
                attrs, color = sgr(code, attrs, color)


def sgr(code, attrs, color):
    if code == "0":
        return curses.A_NORMAL, None
    if code == "39":
        return attrs, None
    if code in COLORS:
        return attrs, code
    return {
        "1": attrs | curses.A_BOLD,
        "2": attrs | curses.A_DIM,
        "22": attrs & ~(curses.A_BOLD | curses.A_DIM),
    }[code], color


def cells_for(char):
    return (
        0
        if unicodedata.combining(char)
        else 1 + (unicodedata.east_asian_width(char) in "WF")
    )


def wrap(text, width):
    """Wrap into rows of styled spans, keeping styles across line breaks."""
    if width < 1:
        yield []
        return
    spans = []
    used = 0
    tab_offset = 0
    for text, attrs, color in chunks(text):
        part = []
        span_width = 0
        text = (" " * tab_offset + text).expandtabs(4)[tab_offset:]
        tab_offset = (tab_offset + len(text)) % 4
        for char in text:
            char = char if char.isprintable() else "?"
            cells = cells_for(char)
            if cells > width:
                char, cells = "?", 1
            if used + cells > width:
                if part:
                    spans.append(("".join(part), span_width, attrs, color))
                yield spans
                spans, part = [], []
                used = span_width = 0
            part.append(char)
            used += cells
            span_width += cells
        if part:
            spans.append(("".join(part), span_width, attrs, color))
    yield spans


def palette():
    if "NO_COLOR" in os.environ or not curses.has_colors():
        return {}
    try:
        curses.use_default_colors()
        pairs = {}
        for pair, (code, foreground) in enumerate(COLORS.items(), 1):
            curses.init_pair(pair, foreground, -1)
            pairs[code] = curses.color_pair(pair)
        return pairs
    except curses.error:
        return {}


class Screen:
    def __init__(self, window):
        self.window = window
        self.colors = palette()
        # Keep enough time to decode arrow keys without delaying a bare Esc.
        if "ESCDELAY" not in os.environ:
            curses.set_escdelay(50)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def draw_row(self, row, spans, base=curses.A_NORMAL):
        column = 0
        for text, width, attrs, color in spans:
            foreground = (base & curses.A_COLOR) or self.colors.get(color, 0)
            style = base | attrs | foreground
            if attrs & curses.A_BOLD:
                style &= ~curses.A_DIM
            self.window.addstr(row, column, text, style)
            column += width

    def display(self, title, lines, footer, *, cursor=None, offset=0):
        rows, columns = self.window.getmaxyx()
        self.window.erase()
        width = columns - 1
        if rows > 0 and width > 0:
            self.draw_row(0, next(wrap(paint("1;36", title), width)))
        if rows > 1 and width > 0:
            for index, line in enumerate(
                lines[offset : offset + rows - 2], offset
            ):
                style = curses.A_NORMAL
                if index == cursor:
                    style = (
                        curses.A_REVERSE
                        | curses.A_BOLD
                        | self.colors.get("36", 0)
                    )
                spans = (
                    next(wrap(line, width)) if isinstance(line, str) else line
                )
                self.draw_row(index - offset + 1, spans, style)
            self.draw_row(rows - 1, next(wrap(footer, width)), curses.A_DIM)
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
                f"{selection_mark(index in selected)} {label}"
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
        self,
        title,
        details,
        *,
        action="Apply",
        default=False,
        cancel="Cancel",
        destructive=False,
    ):
        selected = default
        offset = 0
        while True:
            height, width = self.window.getmaxyx()
            if height < 4 or width < 23:
                self.display("Resize terminal", [], "Esc Back  q Exit")
                self.navigate(self.key())
                continue
            action_color = "1;31" if destructive else "1;32"
            primary = (
                paint(action_color, f"[ {action} ]") if selected else action
            )
            secondary = cancel if selected else paint("1;36", f"[ {cancel} ]")
            footer = f"  {primary}    {secondary}  ←→ Choose  Enter  Esc Back"
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
            self.download_line(job, columns)
            for job in ordered[: max(1, rows - 2)]
        ]
        done = sum(job.status is not None for job in jobs)
        footer = "Esc Cancel download  Ctrl+C Exit" if cancel else "Ctrl+C Exit"
        self.display(f"{title}  {done}/{len(jobs)} finished", lines, footer)
        if self.key(0) in BACK and cancel:
            raise Back

    def download_line(self, job, columns):
        line = job_line(
            job, max(12, columns // 3), min(20, max(4, columns // 5)), columns
        )
        if job.status is not None:
            return paint("32" if job.status == 0 else "31", line)
        if job.process is not None:
            return paint("36", line)
        return line

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
