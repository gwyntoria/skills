"""List supported Agent command entries in PATH order."""

import os
import sys

from .user_paths import show


AGENTS = (("codex", "Codex"), ("claude", "Claude Code"), ("pi", "Pi"))


def executable_entries(command, directories):
    entries = dict.fromkeys(
        os.path.join(directory, command) for directory in directories
    )
    for entry in entries:
        try:
            executable = os.path.realpath(entry, strict=True)
        except OSError:
            continue
        if os.path.isfile(executable) and os.access(executable, os.X_OK):
            yield entry, executable


def main():
    terminal = sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
    use_color = terminal and not os.environ.get("NO_COLOR")
    if terminal:
        print("\033[H\033[2J", end="")

    def color(value, code):
        return f"\033[{code}m{value}\033[0m" if use_color else value

    print("Agent / List")
    cwd = os.getcwd()
    directories = [
        os.path.join(cwd, directory) for directory in os.get_exec_path()
    ]
    found = False
    for command, name in AGENTS:
        for index, (entry, executable) in enumerate(
            executable_entries(command, directories)
        ):
            if index == 0:
                found = True
                print(f"\n{color(name, '1;36')}")
            active = " (Active)" if index == 0 else ""
            print(f"  Command entry: {color(show(entry), '33')}{active}")
            print(f"  Executable:    {color(show(executable), '32')}")
    if not found:
        print("\nNo supported Agents found on PATH.")
