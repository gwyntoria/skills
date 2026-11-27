"""Keyboard navigation and terminal ownership for the config session."""

import os
import re
import curses
import signal
import selectors
import subprocess
import unicodedata
from itertools import zip_longest

from content.paths import abbreviate_home
from content.loading import job_line


class Back(Exception):
    pass


class Quit(Exception):
    pass


ENTER = (10, 13, curses.KEY_ENTER)
BACK = (27, ord("b"), ord("B"))
QUIT = (ord("q"), ord("Q"))
ANSI = re.compile(r"(\x1b\[[0-?]*[ -/]*[@-~])")
ANSI_COLORS = (
    curses.COLOR_BLACK,
    curses.COLOR_RED,
    curses.COLOR_GREEN,
    curses.COLOR_YELLOW,
    curses.COLOR_BLUE,
    curses.COLOR_MAGENTA,
    curses.COLOR_CYAN,
    curses.COLOR_WHITE,
)
FOREGROUNDS = {
    str(code + index): color + intensity
    for code, intensity in ((30, 0), (90, 8))
    for index, color in enumerate(ANSI_COLORS)
}
BACKGROUNDS = {
    str(int(code) + 10): color for code, color in FOREGROUNDS.items()
}
DEFAULT_COLORS = (-1, -1)
SGR = {"0", "1", "2", "22", "39", "49", *FOREGROUNDS, *BACKGROUNDS}

TITLE_BURGUNDY = 131  # xterm #af5f5f
WORDMARK = (
    " ███  █   █ █   █ █   █   █████  ███   ███  █",
    "█     █   █  █ █  ██  █     █   █   █ █   █ █",
    "█  ██ █ █ █   █   █ █ █     █   █   █ █   █ █",
    "█   █ ██ ██   █   █  ██     █   █   █ █   █ █",
    " ████ █   █   █   █   █     █    ███   ███  █████",
)
HOME_ITEMS = (
    ("\U000f03ec  Skill", "Install, remove or list skills"),
    ("\U000f0b8a  Rule", "Install, remove or list rules"),
    ("\U000f0493  Agent", "Install, clean up, uninstall or list agents"),
    ("\U000f081c  Exit", "Return to the shell"),
)


def paint(code, text):
    return f"\033[{code}m{text}\033[0m"


def number_shortcut(count):
    return "Number + Enter" if count >= 10 else "Number Select"


def wordmark_rows():
    for face, previous in zip_longest(WORDMARK, ("", *WORDMARK), fillvalue=""):
        # A block on the face covers its shadow, offset one cell down and right.
        row = "".join(
            front if front == "█" else "░" if behind == "█" else " "
            for front, behind in zip_longest(
                face, " " + previous, fillvalue=" "
            )
        ).rstrip()
        yield re.sub(
            r"█+|░+",
            lambda run: paint("1;97" if run[0][0] == "█" else "22;90", run[0]),
            row,
        )


WORDMARK_BANNER = (*wordmark_rows(), "")
COMPACT_WORDMARK = paint("1;97", "GWYN TOOL")


def selection_mark(picked, total=1):
    if not picked:
        return "[ ]"
    if picked == total:
        return paint("1;32", "[x]")
    return paint("1;33", "[-]")


def chunks(text):
    attrs = curses.A_NORMAL
    color = DEFAULT_COLORS
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
        return curses.A_NORMAL, DEFAULT_COLORS
    foreground, background = color
    if code == "39" or code in FOREGROUNDS:
        return attrs, (FOREGROUNDS.get(code, -1), background)
    if code == "49" or code in BACKGROUNDS:
        return attrs, (foreground, BACKGROUNDS.get(code, -1))
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
        text = abbreviate_home(text)
        text = (" " * tab_offset + text).expandtabs(4)[tab_offset:]
        tab_offset = (tab_offset + len(text)) % 4
        for char in text:
            # Nerd Font glyphs use Unicode's private-use ranges.
            if not char.isprintable() and unicodedata.category(char) != "Co":
                char = "?"
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


def enable_colors():
    if "NO_COLOR" in os.environ or not curses.has_colors():
        return False
    try:
        curses.use_default_colors()
    except curses.error:
        return False
    return True


def page_banner(rows, width):
    # Reserve room for the page title, four content rows, and the footer.
    minimum_page = 6
    if (
        rows >= minimum_page + len(WORDMARK_BANNER)
        and width >= max(map(len, WORDMARK)) + 1
    ):
        return WORDMARK_BANNER
    if rows > minimum_page:
        return (COMPACT_WORDMARK,)
    return ()


class Screen:
    def __init__(self, window):
        self.window = window
        self.color_enabled = enable_colors()
        self.color_pairs = {}
        # Keep enough time to decode arrow keys without delaying a bare Esc.
        if "ESCDELAY" not in os.environ:
            curses.set_escdelay(50)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def color_style(self, colors):
        if not self.color_enabled or colors == DEFAULT_COLORS:
            return 0
        foreground, background = colors
        attrs = 0
        if foreground >= curses.COLORS:
            foreground, attrs = (
                (-1, curses.A_DIM)
                if foreground == 8
                else (foreground - 8, curses.A_BOLD)
            )
        if background >= curses.COLORS:
            background -= 8
        pair = (foreground, background)
        if pair not in self.color_pairs:
            index = len(self.color_pairs) + 1
            if index >= min(curses.COLOR_PAIRS, 256):
                return attrs
            curses.init_pair(index, *pair)
            self.color_pairs[pair] = curses.color_pair(index)
        return attrs | self.color_pairs[pair]

    def draw_row(
        self,
        row,
        spans,
        base=curses.A_NORMAL,
        *,
        default_colors=DEFAULT_COLORS,
    ):
        column = 0
        for text, width, attrs, color in spans:
            if color == DEFAULT_COLORS:
                color = default_colors
            color_attr = 0 if base & curses.A_COLOR else self.color_style(color)
            style = base | attrs | color_attr
            if style & curses.A_BOLD:
                style &= ~curses.A_DIM
            self.window.addstr(row, column, text, style)
            column += width

    def body_height(self, *, action_rows=0):
        rows, columns = self.window.getmaxyx()
        banner = page_banner(rows, columns - 1)
        return max(0, rows - len(banner) - 2 - action_rows)

    def display(
        self,
        title,
        lines,
        footer,
        *,
        cursor=None,
        offset=0,
        actions=None,
        number_width=0,
    ):
        rows, columns = self.window.getmaxyx()
        self.window.erase()
        width = columns - 1
        if rows < 1 or width < 1:
            self.window.refresh()
            return

        banner = page_banner(rows, width)
        if not banner:
            title = f"{COMPACT_WORDMARK} · {title}"
        title_color = (
            TITLE_BURGUNDY
            if self.color_enabled and curses.COLORS >= 256
            else curses.COLOR_RED
        )
        headings = (*banner, title)
        for index, heading in enumerate(headings):
            self.draw_row(
                index,
                next(wrap(paint("1", heading), width)),
                default_colors=(title_color, -1),
            )
        row = len(headings)
        limit = max(0, rows - row - 1 - (actions is not None))
        for index, line in enumerate(lines[offset : offset + limit], offset):
            number = f"{index + 1}.".ljust(number_width) if number_width else ""
            self.draw_line(row, line, width, cursor, index, number)
            row += 1
        if actions is not None:
            self.draw_row(row, next(wrap(actions, width)))
            row += 1
        if rows > 1:
            footer_row = rows - 1
            if cursor is not None or actions is not None:
                footer_row = min(row + 1, footer_row)
            if len(footer) > width:
                footer = footer.replace("  │  ", " │ ")
            self.draw_row(footer_row, next(wrap(footer, width)), curses.A_DIM)
        self.window.refresh()

    def draw_line(self, row, line, width, cursor, index, number):
        style = curses.A_NORMAL
        check_spans = []
        if cursor is not None:
            if isinstance(line, tuple):
                line, check = line
                if width >= len(number) + 7:
                    # Leave room for the check mark when the name is clipped.
                    check_spans = next(wrap(f" {check}", width))
                    width -= sum(span[1] for span in check_spans)
            line = ("▸ " if index == cursor else "  ") + number + line
            if index == cursor:
                style = curses.A_BOLD | self.color_style(
                    (curses.COLOR_CYAN + 8, -1)
                )
        spans = next(wrap(line, width)) if isinstance(line, str) else line
        self.draw_row(row, spans + check_spans, style)

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
        numbered=True,
    ):
        def draw():
            return lines() if callable(lines) else lines

        cursor = min(cursor, len(draw()) - 1)
        offset = 0
        digits = ""
        while True:
            labels = draw()
            height = max(1, self.body_height())
            offset = max(
                0,
                cursor - height + 1,
                min(offset, len(labels) - height, cursor),
            )
            self.display(
                title,
                labels,
                self.menu_footer(footer, toggle, numbered, len(labels), digits),
                cursor=cursor,
                offset=offset,
                number_width=len(str(len(labels))) + 2 if numbered else 0,
            )
            key = self.key()
            self.navigate(key)
            if numbered:
                key, cursor, digits = self.numbered_key(
                    key, cursor, digits, labels
                )
            cursor = self.move(key, cursor, len(labels))
            if key == ord("c") and continue_key:
                return None
            if key in ENTER or (toggle is not None and key == ord("c")):
                return cursor
            if toggle is not None and key in (ord(" "), ord("a"), ord("n")):
                toggle(key, cursor)

    @staticmethod
    def menu_footer(footer, toggle, numbered, count, digits):
        if digits:
            return f"Number {digits}  │  Enter Select  │  Backspace Edit  │  Esc Back"
        if callable(footer):
            return footer()
        if footer is not None:
            return footer
        if toggle is None:
            footer = "↑↓ Move  │  Enter Select  │  Esc Back  │  q Exit"
        else:
            footer = (
                "↑↓ Move  │  Space Toggle  │  a All  │  n None  │  "
                "Enter Continue  │  Esc Back  │  q Exit"
            )
        return f"{number_shortcut(count)}  │  {footer}" if numbered else footer

    @staticmethod
    def numbered_key(key, cursor, digits, labels):
        count = len(labels)
        if ord("0") <= key <= ord("9"):
            digits += chr(key)
            if count >= 10:
                return None, cursor, digits
        elif digits and key in (curses.KEY_BACKSPACE, 8, 127):
            return None, cursor, digits[:-1]
        elif key == curses.KEY_RESIZE:
            return key, cursor, digits
        elif not digits or key not in ENTER:
            return key, cursor, ""

        choice = int(digits) if len(digits) <= len(str(count)) else 0
        if not 1 <= choice <= count or digits.startswith("0"):
            return None, cursor, ""
        cursor = choice - 1
        # Rows with check marks toggle. Plain rows use the menu's Enter action.
        key = ord(" ") if isinstance(labels[cursor], tuple) else ENTER[0]
        return key, cursor, ""

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

    def home(self):
        return self.choose("AGENT CONFIG", HOME_ITEMS, numbered=False)

    def choose(self, title, labels, default=0, *, numbered=True):
        if labels and isinstance(labels[0], tuple):
            width = max(sum(map(cells_for, label)) for label, _ in labels)
            labels = [
                paint("1", label)
                + " " * (width - sum(map(cells_for, label)) + 5)
                + paint("2", description)
                for label, description in labels
            ]
        return self.menu(title, labels, default, numbered=numbered)

    def multi(self, title, labels, selected):
        def lines():
            return [
                (label, selection_mark(index in selected))
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
        action = f"1. {action}"
        cancel = f"2. {cancel}"
        selected = default
        offset = 0
        while True:
            height, width = self.window.getmaxyx()
            if height < 4 or width <= max(22, len(action) + len(cancel) + 8):
                self.display("Resize terminal", [], "Esc Back  │  q Exit")
                self.navigate(self.key())
                continue
            action_color = "1;31" if destructive else "1;96"
            primary = (
                paint(action_color, f"▸ {action}")
                if selected
                else f"  {action}"
            )
            secondary = (
                f"  {cancel}" if selected else paint("1;96", f"▸ {cancel}")
            )
            lines = self.details(details)
            offset = self.scroll(-1, offset, lines, action_rows=1)
            self.display(
                title,
                lines,
                "←→ Choose  │  Enter Select  │  Esc Back  │  q Exit",
                offset=offset,
                actions=f"{primary}    {secondary}",
            )
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
            offset = self.scroll(key, offset, lines, action_rows=1)

    def scroll(self, key, offset, lines, *, action_rows=0):
        step = max(1, self.body_height(action_rows=action_rows))
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

    def page(self, title, details, *, start_at_end=False, alternate=None):
        offset = None if start_at_end else 0
        layout = 0
        footer = "↑↓ Scroll  │  Enter / Esc Main menu  │  q Exit"
        while True:
            lines = self.details(details)
            offset = self.scroll(
                -1, len(lines) if offset is None else offset, lines
            )
            self.display(
                title,
                lines,
                f"← {'AB'[layout]} →  │  {footer}"
                if alternate is not None
                else footer,
                offset=offset,
            )
            key = self.key()
            if key in (*BACK, *ENTER):
                return
            if key in QUIT:
                raise Quit
            if alternate is not None and key in (
                curses.KEY_LEFT,
                curses.KEY_RIGHT,
            ):
                details, alternate = alternate, details
                layout = 1 - layout
                offset = 0
                continue
            offset = self.scroll(key, offset, lines)

    def downloads(self, title, jobs, *, cancel=True):
        _, columns = self.window.getmaxyx()
        ordered = sorted(
            jobs, key=lambda job: (job.status is not None, job.process is None)
        )
        lines = [
            self.download_line(job, columns)
            for job in ordered[: self.body_height()]
        ]
        done = sum(job.status is not None for job in jobs)
        footer = (
            "Esc Cancel download  │  Ctrl+C Exit" if cancel else "Ctrl+C Exit"
        )
        self.display(f"{title}  {done}/{len(jobs)} finished", lines, footer)
        if self.key(0) in BACK and cancel:
            raise Back

    def download_line(self, job, columns):
        line = job_line(
            job, max(12, columns // 3), min(20, max(4, columns // 5)), columns
        )
        if job.status is not None:
            return paint("32" if job.status == 0 else "31", line)
        return line

    def busy(self, title, lines):
        height = self.body_height()
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


def command_lines(data):
    # Clack spinners return to column one and clear the row before repainting.
    data = re.sub(rb"(?m)^.*\x1b\[1G\x1b\[J", b"", data)
    return data.decode(errors="replace").splitlines()


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
                    chunk += data
                    if b"\n" in chunk:
                        lines, chunk = chunk.rsplit(b"\n", 1)
                        progress(command_lines(lines))
                    chunk = chunk[-65536:]
                progress([])
                if process.poll() is not None and not selector.select(0):
                    break
            if chunk:
                progress(command_lines(chunk))
            returncode = process.wait()
        except BaseException:
            stop_child(process)
            raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
