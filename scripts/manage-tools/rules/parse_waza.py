"""Validate Waza rule discovery data before it reaches the installer."""

import re
import sys
import json
from pathlib import Path


def rule_name(name):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\.md", name):
        raise ValueError("Invalid Waza rule filename")
    return "waza-" + name[:-3]


def require_rules(names):
    if not names:
        raise ValueError("No Waza rules available")


def main(mode, source, *args):
    if mode == "tree":
        entries = []
        for row in source.read_text(encoding="utf-8").split("\0"):
            match = re.fullmatch(
                r"100(?:644|755) blob ([a-f0-9]{40})\t(.*)", row, re.S
            )
            if match and match[2].endswith(".md"):
                entries.append((rule_name(match[2]), match[1]))
        require_rules(entries)
        entries.sort()
        output = Path(args[0])
        (output / "names").write_text(
            "".join(f"{name}\n" for name, _ in entries), encoding="utf-8"
        )
        (output / "blobs").write_text(
            "".join(f"{blob}\t{name}\n" for name, blob in entries),
            encoding="utf-8",
        )
    elif mode == "commit":
        data = json.loads(source.read_text(encoding="utf-8"))
        sha = data.get("sha") if isinstance(data, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("Invalid Waza commit")
        print(sha)
    else:
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Invalid Waza rule catalog")
        names = set()
        for entry in data:
            name = entry.get("name")
            if (
                entry.get("type") == "file"
                and isinstance(name, str)
                and name.endswith(".md")
            ):
                names.add(rule_name(name))
        require_rules(names)
        print("\n".join(sorted(names)))


if __name__ == "__main__":
    try:
        main(sys.argv[1], Path(sys.argv[2]), *sys.argv[3:])
    except (OSError, ValueError, AttributeError) as error:
        sys.exit(str(error))
