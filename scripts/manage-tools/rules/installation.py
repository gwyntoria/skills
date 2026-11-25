"""Append a selected rule to the existing Agent or project instructions."""

import os
import re
from pathlib import Path

from content.paths import safe_root


RULE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*")


def pi_rule_path(home):
    directory = os.environ.get("PI_CODING_AGENT_DIR") or str(home / ".pi/agent")
    if directory == "~" or directory.startswith("~/"):
        directory = str(home) + directory[1:]
    return Path(directory) / "AGENTS.md"


def destinations(home, project, scope, targets, name):
    if scope == "project":
        return {"project": project / "docs/rules" / f"{name}.md"}
    claude = (
        home / ".claude/CLAUDE.md"
        if name == "agent-behavior"
        else home / ".claude/rules" / f"{name}.md"
    )
    paths = {
        "codex": home / ".codex/AGENTS.md",
        "claude": claude,
        "pi": pi_rule_path(home),
    }
    return {target: paths[target] for target in targets}


def rule_body(path, waza=False):
    body = path.read_bytes()
    prefixes = (b"# ", b"## ") if waza else (b"# ",)
    if not body.startswith(prefixes):
        title = "H1 or H2" if waza else "H1"
        raise ValueError(f"Rule must start with {title}: {path}")
    return body


def names(directory):
    if not directory.is_dir():
        raise ValueError(f"Invalid rule directory: {directory}")
    result = []
    for path in sorted(directory.glob("*.md")):
        if path.is_file():
            if not RULE_NAME.fullmatch(path.stem):
                raise ValueError(f"Invalid rule name: {path}")
            rule_body(path)
            result.append(path.stem)
    return result


def headings(body, level):
    lines = body.splitlines()
    shift = level - len(lines[0].split(b" ", 1)[0])
    fence = None
    for line in lines:
        marker = re.match(rb" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if marker:
                run, tail = marker.groups()
                if (
                    run[:1] == fence[:1]
                    and len(run) >= len(fence)
                    and not tail.strip(b" \t")
                ):
                    fence = None
        elif marker:
            fence = marker[1]
        else:
            heading = re.match(rb"( {0,3})(#{1,6})(?=[ \t]|$)", line)
            if heading:
                indent, hashes = heading.groups()
                line = (
                    indent
                    + b"#" * min(6, len(hashes) + shift)
                    + line[heading.end() :]
                )
        yield line


def append_rule(path, body, level, global_header):
    existing = path.read_bytes() if path.is_file() else b""
    eol = b"\r\n" if b"\r" in existing else b"\n"
    if existing:
        trailing = existing.rsplit(b"\n", 2)
        if not existing.endswith(b"\n"):
            prefix = eol * 2
        elif trailing[-2].rstrip(b"\r"):
            prefix = eol
        else:
            prefix = b""
    else:
        prefix = b"# Global Rules" + eol * 2 if global_header else b""
    with path.open("ab") as output:
        output.write(prefix + eol.join(headings(body, level)) + eol)


def preflight(paths):
    resolved = {}
    for target, path in paths.items():
        destination = path.resolve()
        for parent in (path.parent, destination.parent):
            parent.mkdir(parents=True, exist_ok=True)
            if not os.access(parent, os.W_OK):
                raise OSError(f"Cannot write to {parent}")
        if destination.exists() and (
            not destination.is_file() or not os.access(destination, os.W_OK)
        ):
            raise OSError(f"Cannot write to {destination}")
        resolved[target] = destination
    return resolved


def install(home, project, scope, targets, name, source, waza=False):
    safe_root(str(home), "HOME")
    if scope == "project":
        safe_root(str(project), "project")
    if not RULE_NAME.fullmatch(name):
        raise ValueError(f"Invalid rule name: {name}")
    body = rule_body(source, waza)
    paths = destinations(home, project, scope, targets, name)
    resolved = preflight(paths)
    failed = []
    for target, destination in resolved.items():
        global_header = scope == "global" and target != "claude"
        if (
            global_header
            and (paths[target].parent / "AGENTS.override.md").is_file()
        ):
            print(f"AGENTS.override.md takes precedence over {paths[target]}")
        try:
            level = (
                1
                if target == "claude"
                or (scope == "project" and waza and body.startswith(b"# "))
                else 2
            )
            append_rule(destination, body, level, global_header)
            print(f"Installed ({target}, {scope}): {destination}")
        except OSError as error:
            failed.append(str(error))
    if failed:
        raise OSError("\n".join(failed))
