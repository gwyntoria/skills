"""Start the config TUI or run a catalog worker."""

import os
import sys
import signal
import argparse
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


SOURCE_ARCHIVE_URL = (
    "https://codeload.github.com/gwyntoria/skills/tar.gz/refs/heads/main"
)


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def start(mode, archive_url):
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
    try:
        import curses
    except ImportError:
        print(
            "Error: config requires Python with curses support.",
            file=sys.stderr,
        )
        return 2
    from config.screen import Quit, Screen
    from config.session import Session

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
    if sys.version_info < (3, 10):
        print("Error: config requires Python 3.10 or later.", file=sys.stderr)
        return 2
    if args and args[0] == "--worker":
        from content.catalog import InvalidRule, worker

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
    if len(args) == 2 and args[0] in ("local", "archive"):
        return start(*args)
    argparse.ArgumentParser(
        description="Open the Agent configuration menu from this checkout."
    ).parse_args(args)
    return start("local", SOURCE_ARCHIVE_URL)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
