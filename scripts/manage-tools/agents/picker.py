"""Terminal selection for optional Agent cleanup and uninstall steps."""

import os
import sys
import tty
import select
import termios


def read_key(fd):
    key = os.read(fd, 1)
    if key == b"\x1b":
        if select.select([fd], [], [], 0.05)[0] and os.read(fd, 1) in (
            b"[",
            b"O",
        ):
            if select.select([fd], [], [], 0.05)[0]:
                return {b"A": b"up", b"B": b"down"}.get(
                    os.read(fd, 1), b"unknown"
                )
        return b"q"
    return key


def pick_optional(action, agent, optional):
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    selected = set()
    rows = os.get_terminal_size(sys.stdout.fileno()).lines or 24
    page_size = max(1, min(8, rows - 7))
    cursor = 0

    tty.setraw(fd, termios.TCSANOW)
    try:
        while True:
            start = cursor - cursor % page_size
            print(
                f"\033[?25l\033[H\033[2JAgent / {action} / {agent} / Optional items",
                end="\r\n\r\n",
            )
            for index in range(start, min(start + page_size, len(optional))):
                marker = ">" if index == cursor else " "
                checked = "x" if index in selected else " "
                print(
                    f"{marker} [{checked}] {optional[index].description}",
                    end="\r\n",
                )
            print(
                f"\r\nItem {cursor + 1}/{len(optional)} | Selected: {len(selected)}\r\n"
                "↑↓ Move   Space Toggle   Enter Continue\r\n"
                "a All   n None   Esc/q Cancel",
                end="\r\n",
                flush=True,
            )
            key = read_key(fd)
            if key in (b"q", b"Q", b"\x03", b"\x04", b""):
                return None
            if key == b"up":
                cursor = (cursor - 1) % len(optional)
            elif key == b"down":
                cursor = (cursor + 1) % len(optional)
            elif key == b" ":
                selected.symmetric_difference_update({cursor})
            elif key in (b"a", b"A"):
                selected = set(range(len(optional)))
            elif key in (b"n", b"N"):
                selected.clear()
            elif key in (b"\r", b"\n"):
                return [optional[index] for index in sorted(selected)]
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        print("\033[?25h", end="", flush=True)
