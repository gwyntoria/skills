"""List installed rules and skills, including links and their provenance."""

import os
import re
import sys
from pathlib import Path

from .paths import (
    UNKNOWN,
    MISSING_TARGET,
    ANTIGRAVITY_RULES,
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
from .bundled_skills import claude_skills, antigravity_skills


BROKEN = " (broken link)"
BUILD_IN = "build-in"


def rule_source(file):
    text = file.read_text(encoding="utf-8", errors="replace")
    if "<!-- Installed from rules/" in text:
        return "gwyntoria/skills"
    match = re.search(
        r"<!-- Installed from https://github\.com/([\w.-]+/[\w.-]+)",
        text,
        re.ASCII,
    )
    return match[1] if match else ""


def rule_files(path, ancestors=frozenset()):
    info = target_stat(path)
    if info is None:
        if path.parent.exists() and symlink(entry_stat(path)):
            yield path.name, BROKEN, path
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
                origin = rule_source(file) if regular(target) else ""
                yield file.name, origin if target else BROKEN, file


def shared_skill_name(child, shared):
    try:
        real = child.resolve(strict=True)
        if real.parent == shared:
            return real.name
    except OSError as error:
        if error.errno not in MISSING_TARGET:
            raise
    except RuntimeError:
        pass  # pathlib 3.10 reports symlink loops as RuntimeError.
    return None


def standalone_pi_skill(path):
    with path.open(encoding="utf-8-sig", errors="replace") as source:
        if source.readline().rstrip() != "---":
            return False
        lines = []
        for line in source:
            if line.rstrip() == "---":
                break
            lines.append(line)
        else:
            return False

    description = re.search(
        r"""^(?:description|"description"|'description')[ \t]*:[ \t]*([^\n]*)([\s\S]*)""",
        "".join(lines),
        re.M,
    )
    if not description:
        return False
    value = description[1]
    quoted = re.match(r"""(?:"((?:[^"\\]|\\.)*)"|'((?:[^']|'')*)')""", value)
    if quoted:
        return bool((quoted[1] or quoted[2] or "").strip())
    value = re.split(r"(?:^|[ \t]+)#", value, maxsplit=1)[0].strip()
    if not value or re.fullmatch(r"[|>](?:[+-]?[1-9]?|[1-9][+-]?)", value):
        return bool(
            re.match(r"(?:\n|[ \t]*#[^\n]*\n)*[ \t]+[^\s#]", description[2])
        )
    return not value.startswith(("[", "{")) and not re.fullmatch(
        r"~|null|true|false|[+-]?(?:\.(?:inf|nan)|0[xo][0-9a-f]+|(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)",
        value,
        re.I,
    )


def nested_skill_entries(path, *, standalone=False, ancestors=frozenset()):
    info = target_stat(path)
    if not directory(info):
        return
    identity = (info.st_dev, info.st_ino)
    if identity in ancestors:
        return
    if regular(target_stat(path / "SKILL.md")):
        yield path
        return
    ancestors = ancestors | {identity}
    for entry in sorted(path.iterdir()):
        if entry.name == "node_modules" or (
            entry.name.startswith(".") and entry.name != ".system"
        ):
            continue
        if (
            standalone
            and entry.suffix == ".md"
            and regular(target_stat(entry))
            and standalone_pi_skill(entry)
        ):
            yield entry
        else:
            yield from nested_skill_entries(entry, ancestors=ancestors)


def skill_entries(path):
    if not directory(target_stat(path)):
        return
    for entry in sorted(path.iterdir()):
        if entry.name == ".system":
            yield from nested_skill_entries(entry)
        else:
            yield entry


def skill_files(path, entries, shared, records, *, codex_location=False):
    for child in entries:
        relative = child.relative_to(path)
        name = str(relative) if relative.parts else child.name
        if codex_location and relative.parts[:1] == (".system",):
            yield name, BUILD_IN, child
            continue
        canonical = shared_skill_name(child, shared)
        label = (
            f"{name} ({canonical})" if canonical and canonical != name else name
        )
        origin = UNKNOWN
        if canonical or not codex_location:
            origin = metadata_origin(records.get(canonical or name))
        yield label, "" if origin == UNKNOWN else origin, child


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


def print_skills(print_group, root, scope, selected, agy):
    shared = root / ".agents/skills"
    codex = root / ".codex"
    pi = root / ".pi"
    if scope == "global":
        codex = Path(os.environ.get("CODEX_HOME") or codex).expanduser()
        pi = Path(
            os.environ.get("PI_CODING_AGENT_DIR") or pi / "agent"
        ).expanduser()
    locations = (
        ("Shared", shared),
        ("Codex", codex / "skills"),
        ("Claude", root / SKILL_DIRECTORIES["claude"]),
        ("Pi", pi / "skills"),
    )
    bundled = {}
    if scope == "global":
        locations += (("Antigravity CLI", root / SKILL_DIRECTORIES["agy"]),)
        selected += (agy,)
        bundled = {
            "Claude": claude_skills,
            "Antigravity CLI": antigravity_skills,
        }
    records = skill_records(root, scope)
    shared_target = Path(os.path.realpath(shared))
    for (title, path), enabled in zip(locations, selected, strict=True):
        if enabled == "1":
            rows = (
                [(name, BUILD_IN, file) for name, file in bundled[title](root)]
                if title in bundled
                else []
            )
            if title == "Antigravity CLI" and path.is_symlink():
                name = (
                    "Shared skills directory link"
                    if Path(os.path.realpath(path)) == shared_target
                    else "Skills directory link"
                )
                print_group(f"Skills · {title}", [*rows, (name, "", path)])
                continue
            entries = (
                nested_skill_entries(path, standalone=True)
                if title == "Pi"
                else skill_entries(path)
            )
            print_group(
                f"Skills · {title}",
                [
                    *rows,
                    *skill_files(
                        path,
                        entries,
                        shared_target,
                        records,
                        codex_location=title == "Codex",
                    ),
                ],
            )


def print_rules(print_group, root, scope, codex, claude, pi, pi_path, agy):
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
        if agy == "1":
            print_group(
                "Rules · Antigravity CLI",
                shared_rules(root / ANTIGRAVITY_RULES),
            )


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
        if origin == BROKEN:
            source = paint("33", BROKEN)
        else:
            source = f"  [{display(origin)}]" if origin else ""
        print(
            f"  {paint('1', display(name))}{source}\n    {display(file)}{link}"
        )


def list_rules(paint, root, scope, codex, claude, pi, pi_path, agy):
    def group(title, rows):
        print_group(paint, title, rows)

    print(f"\n{paint('1;36', 'Installed · ' + scope.title())}\n{display(root)}")
    print_rules(group, root, scope, codex, claude, pi, pi_path, agy)


def skill_layouts(paint, root, scope, selected, agy):
    inline = ["", paint("1;36", f"Installed · {scope.title()}"), display(root)]
    stacked = inline.copy()

    def add(line):
        inline.append(line)
        stacked.append(line)

    def group(title, rows):
        sources = {}
        count = 0
        for name, origin, file in rows:
            path = display(file) if file is not None else ""
            if file is not None and symlink(entry_stat(file)):
                path += f" → {display(os.readlink(file))}"
            sources.setdefault(origin, []).append((name, path))
            count += 1

        add("")
        add(paint("1;36", f"{title} ({count})"))
        if not sources:
            add("  None")
        for index, (origin, entries) in enumerate(sources.items()):
            if index:
                add("")
            heading = (
                paint("1;33", display(origin))
                if origin
                else paint("2", "No source recorded")
            )
            add(f"  {heading}")
            digits = len(str(len(entries)))
            for number, (name, path) in enumerate(entries, 1):
                item = f"    {number:>{digits}}. {paint('1', display(name))}"
                if not path:
                    add(item)
                    continue
                arrow = f"{paint('2', '→')} {path}"
                inline.append(f"{item} {arrow}")
                stacked.extend((item, f"{' ' * (digits + 6)}{arrow}"))

    print_skills(group, root, scope, selected, agy)
    return inline, stacked
