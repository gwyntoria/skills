"""List installed rules and skills, including links and their provenance."""

import os
import re
import sys
from pathlib import Path

from paths import (
    UNKNOWN,
    MISSING_TARGET,
    SKILL_DIRECTORIES,
    display,
    regular,
    symlink,
    directory,
    lock_path,
    read_json,
    entry_stat,
    target_stat,
    metadata_origin,
)


BROKEN = " (broken link)"


def rule_source(file):
    text = file.read_text(encoding="utf-8", errors="replace")
    if "<!-- Installed from rules/" in text:
        return "gwyntoria/skills"
    match = re.search(
        r"<!-- Installed from https://github\.com/([\w.-]+/[\w.-]+)",
        text,
        re.ASCII,
    )
    return match[1] if match else UNKNOWN


def rule_files(path, ancestors=frozenset()):
    info = target_stat(path)
    if info is None:
        if path.parent.exists() and symlink(entry_stat(path)):
            yield path.name, UNKNOWN + BROKEN, path
    elif regular(info):
        yield path.name, rule_source(path), path
    elif directory(info):
        real = path.resolve(strict=True)
        if real not in ancestors:
            for child in sorted(path.iterdir()):
                yield from rule_files(child, ancestors | {real})


def shared_rules(path):
    if directory(target_stat(path)):
        for file in sorted(path.iterdir()):
            if not file.name.endswith(".md"):
                continue
            info = entry_stat(file)
            if regular(info) or symlink(info):
                target = target_stat(file)
                origin = rule_source(file) if regular(target) else UNKNOWN
                yield file.name, origin if target else origin + BROKEN, file


def canonical_skill_name(child, root, name):
    canonical = name
    try:
        real = child.resolve(strict=True)
        if real.parent == root / ".agents/skills":
            canonical = real.name
    except OSError as error:
        if error.errno not in MISSING_TARGET:
            raise
    except RuntimeError:
        pass  # pathlib 3.10 reports symlink loops as RuntimeError.
    return canonical


def skill_files(root, scope, agent, records):
    locations = [SKILL_DIRECTORIES[agent]]
    if agent == "codex" and scope == "global":
        locations.append(".codex/skills")
    for location in locations:
        path = root / location
        if not directory(target_stat(path)):
            continue
        for entry in sorted(path.iterdir()):
            children = [entry]
            if entry.name == ".system" and directory(target_stat(entry)):
                children = sorted(entry.iterdir())
            for child in children:
                name = str(child.relative_to(path))
                canonical = canonical_skill_name(child, root, name)
                label = name if name == canonical else f"{name} ({canonical})"
                yield label, metadata_origin(records.get(canonical)), child


def skill_records(root, scope):
    records = {}
    lock = root / lock_path(scope)
    try:
        records = read_json(lock).get("skills") or {}
        if not isinstance(records, dict):
            records = {}
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError):
        print(
            f"Warning: unreadable skill lock: {display(lock)}",
            file=sys.stderr,
        )
    return records


def print_rules(print_group, root, scope, codex, claude, pi, pi_path):
    if scope == "project":
        print_group(
            "Rules · Shared project rules",
            shared_rules(root / "docs/rules"),
        )
    else:
        if codex == "1":
            print_group("Rules · Codex", rule_files(root / ".codex/AGENTS.md"))
        if claude == "1":
            rows = [
                *rule_files(root / ".claude/CLAUDE.md"),
                *rule_files(root / ".claude/rules"),
            ]
            print_group("Rules · Claude", rows)
        if pi == "1":
            print_group("Rules · Pi", rule_files(Path(pi_path)))


def print_group(paint, title, rows):
    rows = list(rows)
    print(f"\n{paint('1;36', f'{title} ({len(rows)})')}")
    if not rows:
        print("  None")
    for name, origin, file in rows:
        link = (
            f" -> {display(os.readlink(file))}"
            if symlink(entry_stat(file))
            else ""
        )
        provenance = display(origin)
        if origin.endswith(BROKEN):
            provenance = display(origin[: -len(BROKEN)]) + paint("33", BROKEN)
        print(
            f"  {paint('1', display(name))}  [{provenance}]\n    {display(file)}{link}"
        )


def main(
    home, project, scope, rules, skills, codex, claude, pi, pi_path, color
):
    def paint(code, text):
        return f"\033[{code}m{text}\033[0m" if color == "1" else text

    def group(title, rows):
        print_group(paint, title, rows)

    for label, root in (("global", Path(home)), ("project", Path(project))):
        if scope not in (label, "both"):
            continue
        print(
            f"\n{paint('1;36', 'Installed · ' + label.title())}\n{display(root)}"
        )
        records = skill_records(root, label) if skills == "1" else {}
        if rules == "1":
            print_rules(group, root, label, codex, claude, pi, pi_path)
        if skills == "1":
            for agent, enabled, title in (
                ("codex", codex, "Shared"),
                ("claude", claude, "Claude"),
            ):
                if enabled == "1":
                    group(
                        f"Skills · {title}",
                        skill_files(root, label, agent, records),
                    )


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except OSError as error:
        sys.exit(str(error))
