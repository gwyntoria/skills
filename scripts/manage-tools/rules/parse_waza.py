"""Validate Waza rule discovery data before it reaches the installer."""

import re
import json


def rule_name(name):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\.md", name):
        raise ValueError("Invalid Waza rule filename")
    return "waza-" + name[:-3]


def require_rules(names):
    if not names:
        raise ValueError("No Waza rules available")


def validate_commit(sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Invalid Waza commit")
    return sha


def commit(source):
    data = json.loads(source.read_text(encoding="utf-8"))
    return validate_commit(data.get("sha") if isinstance(data, dict) else None)


def catalog(source):
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Invalid Waza rule catalog")
    names = {
        rule_name(entry["name"])
        for entry in data
        if isinstance(entry, dict)
        and entry.get("type") == "file"
        and isinstance(entry.get("name"), str)
        and entry["name"].endswith(".md")
    }
    require_rules(names)
    return sorted(names)


def main(mode, source, output):
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
        (output / "names").write_text(
            "".join(f"{name}\n" for name, _ in entries), encoding="utf-8"
        )
        (output / "blobs").write_text(
            "".join(f"{blob}\t{name}\n" for name, blob in entries),
            encoding="utf-8",
        )
