"""Start the config TUI or run a catalog worker."""

import os
import sys
import curses
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from config.screen import Quit, Screen
from config.session import Session
from content.catalog import InvalidRule, worker


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def start(mode, archive_url):
    if mode not in ("local", "archive"):
        sys.exit(f"Error: invalid config source: {mode}")
    if (
        not sys.stdin.isatty()
        or not sys.stdout.isatty()
        or os.environ.get("TERM", "dumb") == "dumb"
    ):
        print(
            "Error: Agent configuration requires an interactive terminal with a usable TERM.",
            file=sys.stderr,
        )
        return 2
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    root = Path(__file__).resolve().parents[2]
    try:
        with TemporaryDirectory(prefix="manage-tools-") as work:
            return curses.wrapper(
                lambda window: Session(
                    Screen(window), root, mode, archive_url, Path(work)
                ).run()
            )
    except Quit:
        return 0
    except KeyboardInterrupt:
        return 130
    except curses.error as error:
        print(f"Error: unable to run the config TUI: {error}", file=sys.stderr)
        return 2


def main(args):
    if args[0] == "--worker":
        root, mode, archive_url, kind, value, ref, directory = args[1:]
        try:
            worker(
                kind, value, ref, Path(directory), Path(root), mode, archive_url
            )
        except InvalidRule as error:
            print(error, file=sys.stderr)
            return 2
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            subprocess.SubprocessError,
        ) as error:
            print(error, file=sys.stderr)
            return 1
        return 0
    return start(*args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
