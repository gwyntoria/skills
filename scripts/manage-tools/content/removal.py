"""Scan and apply a scoped, confirmed Skill / Rule removal plan."""

import os
import re
import sys
import json
import stat
import shutil
import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile

from .paths import (
    UNKNOWN,
    MISSING_TARGET,
    SKILL_DIRECTORIES,
    display,
    regular,
    symlink,
    directory,
    lock_path,
    read_json,
    safe_root,
    entry_stat,
    metadata_origin,
    reject_json_constant,
)


AGENTS = {
    "codex": "Codex",
    "claude": "Claude",
    "pi": "Pi",
    "project": "Project",
}


def red(text):
    return f"\033[31m{text}\033[0m"


def green(text):
    return f"\033[32m{text}\033[0m"


def yellow(text):
    return f"\033[33m{text}\033[0m"


def repository(record):
    if not isinstance(record, dict):
        return UNKNOWN
    source = metadata_origin(record)
    source_type = record.get("sourceType")
    if source_type != "github" and not (
        source_type == "download" and source.startswith("https://github.com/")
    ):
        return UNKNOWN
    source = re.sub(
        r"^(https?://github\.com/|git@github\.com:)",
        "",
        source,
    )
    match = re.match(r"^([\w.-]+)/([\w.-]+)(?:/|$)", source, re.ASCII)
    return (
        f"{match[1]}/{match[2].removesuffix('.git')}".lower()
        if match
        else UNKNOWN
    )


def skill_groups(entries):
    groups = {}
    for entry in entries:
        name = entry.get("skillName", entry["name"])
        group = entry["group"]
        key = (
            (group, name)
            if group != UNKNOWN
            else entry.get("skillSource", entry["relative"])
        )
        groups.setdefault(key, (name, group, []))[2].append(entry)
    return groups.values()


def entry_type(info):
    if symlink(info):
        return "link"
    return "directory" if directory(info) else "file"


def label(entry):
    return f"[{AGENTS[entry['agent']]}:{entry['type']}]"


def rule_label(entry):
    return f"{display(entry['name'])} {label(entry)}"


class Removal:
    def __init__(self, home, project, scope, manifest, pi_rule):
        self.home = safe_root(home, "HOME")
        if scope not in ("global", "project"):
            raise ValueError("Invalid removal scope")
        self.scope = scope
        self.root = safe_root(
            project if scope == "project" else home, "removal root"
        )
        self.root_id = self.root_identity()
        self.lock = lock_path(scope)
        self.manifest = Path(manifest)
        self.pi_rule = os.path.abspath(pi_rule)

    def root_identity(self):
        info = entry_stat(self.root)
        if not directory(info):
            raise ValueError("Unsafe removal root directory")
        return [info.st_dev, info.st_ino]

    def full(self, relative):
        path = Path(os.path.abspath(self.root / relative))
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("Path outside removal root")
        return path

    def parents(self, relative):
        result = []
        for parent in self.full(relative).parents:
            if parent == self.root:
                break
            info = entry_stat(parent)
            if not directory(info):
                raise ValueError(f"Unsafe parent directory: {parent}")
            result.append([str(parent), info.st_dev, info.st_ino])
        return result

    def fingerprint(self, relative):
        digest = hashlib.sha256()

        def walk(path):
            info = entry_stat(path)
            if info is None:
                digest.update(b"missing")
                return
            digest.update(
                json.dumps(
                    [
                        str(path),
                        info.st_dev,
                        info.st_ino,
                        info.st_mode,
                        info.st_size,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                    ]
                ).encode()
            )
            if symlink(info):
                digest.update(os.fsencode(os.readlink(path)))
            elif directory(info):
                for child in sorted(path.iterdir()):
                    walk(child)
            elif regular(info):
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    current = os.fstat(stream.fileno())
                    if not regular(current) or (
                        current.st_dev,
                        current.st_ino,
                    ) != (info.st_dev, info.st_ino):
                        raise ValueError(
                            f"Content changed; rescan and select again: {path}"
                        )
                    while block := stream.read(128 * 1024):
                        digest.update(block)
            else:
                raise ValueError(f"Unsupported entry: {path}")

        walk(self.full(relative))
        return digest.hexdigest()

    def read_lock(self):
        path = self.full(self.lock)
        info = entry_stat(path)
        if info is None:
            return {"skills": {}}
        if not regular(info):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, encoding="utf-8") as stream:
                current = os.fstat(stream.fileno())
                if not regular(current) or (current.st_dev, current.st_ino) != (
                    info.st_dev,
                    info.st_ino,
                ):
                    return None
                data = json.load(stream, parse_constant=reject_json_constant)
            if isinstance(data, dict) and isinstance(
                data.get("skills", {}), dict
            ):
                return data
        except (OSError, ValueError):
            pass
        return None

    def link_destination(self, path):
        immediate = Path(os.path.abspath(path.parent / os.readlink(path)))
        # A named Codex entry remains the reference even when it is another link.
        if self.scope != "global" or immediate.parent == self.full(
            ".agents/skills"
        ):
            return immediate
        try:
            return path.resolve(strict=True)
        except RuntimeError:
            return (
                immediate  # pathlib 3.10 reports symlink loops as RuntimeError.
            )
        except OSError as error:
            if error.errno not in MISSING_TARGET:
                raise
            return immediate

    def snapshot(self, relative):
        parents = self.parents(relative)
        return {"snapshot": self.fingerprint(relative), "parents": parents}

    def scan(self, codex, claude, rules, skills, pi=False):
        global_scope = self.scope == "global"
        pi_relative = (
            os.path.relpath(self.pi_rule, self.root)
            if pi and rules and global_scope
            else None
        )
        self.verify_scan_paths(codex, claude, rules, skills, pi_relative)

        entries = []
        has_skills = skills and (codex or claude)
        lock = self.read_lock() if has_skills else {}
        records = (lock or {}).get("skills", {})

        def add(kind, agent, relative, name, info, **metadata):
            entries.append(
                dict(
                    kind=kind,
                    agent=agent,
                    relative=relative,
                    name=name,
                    type=entry_type(info),
                    id=len(entries),
                    **metadata,
                    **self.snapshot(relative),
                )
            )

        if rules and not global_scope:
            self.scan_project_rules(add)

        for agent, enabled, rule in (
            ("codex", codex, ".codex/AGENTS.md"),
            ("claude", claude, ".claude/CLAUDE.md"),
            ("pi", pi, pi_relative),
        ):
            if not enabled or (agent == "pi" and not global_scope):
                continue
            if rules and global_scope:
                info = entry_stat(self.full(rule))
                if regular(info) or symlink(info):
                    add("rules", agent, rule, Path(rule).name, info)
                if agent == "claude":
                    self.scan_claude_rules(".claude/rules", add)
            if not skills or agent == "pi":
                continue
            self.scan_skills(agent, records, add)

        if has_skills and lock is None:
            print(
                yellow(
                    "Skill lock is unreadable; skills are grouped under Unknown / local. Codex deletion requires a valid lock."
                ),
                file=sys.stderr,
            )
        return dict(
            scope=self.scope,
            root=str(self.root),
            rootIdentity=self.root_id,
            entries=entries,
            selected=[],
            piRulePath=self.pi_rule if pi_relative is not None else None,
            lockSnapshot=self.fingerprint(self.lock) if has_skills else None,
        )

    def verify_scan_paths(self, codex, claude, rules, skills, pi_relative):
        global_scope = self.scope == "global"
        if pi_relative is not None:
            self.full(pi_relative)
        for enabled, name in (
            (skills and (codex or claude), ".agents"),
            (claude and (skills or global_scope), ".claude"),
            (rules and codex and global_scope, ".codex"),
        ):
            if enabled and symlink(entry_stat(self.full(name))):
                raise ValueError(
                    f"Refusing symlinked directory: {self.full(name)}"
                )

    def scan_project_rules(self, add):
        folder = self.full("docs/rules")
        info = entry_stat(folder)
        if symlink(info):
            raise ValueError(f"Refusing symlinked directory: {folder}")
        if directory(info):
            self.parents("docs/rules/entry")
            for child in sorted(folder.iterdir()):
                info = entry_stat(child)
                if child.name.endswith(".md") and (
                    regular(info) or symlink(info)
                ):
                    add(
                        "rules",
                        "project",
                        f"docs/rules/{child.name}",
                        child.name,
                        info,
                    )

    def scan_claude_rules(self, relative, add):
        path = self.full(relative)
        info = entry_stat(path)
        if directory(info):
            for child in sorted(path.iterdir()):
                self.scan_claude_rules(f"{relative}/{child.name}", add)
        elif regular(info) or symlink(info):
            add(
                "rules",
                "claude",
                relative,
                relative.removeprefix(".claude/"),
                info,
            )

    def scan_skills(self, agent, records, add):
        relative = SKILL_DIRECTORIES[agent]
        folder = self.full(relative)
        info = entry_stat(folder)
        if symlink(info):
            if agent == "codex":
                raise ValueError(f"Refusing symlinked directory: {folder}")
            add(
                "skills",
                agent,
                relative,
                "skills directory link",
                info,
                group=UNKNOWN,
            )
        elif directory(info):
            self.parents(f"{relative}/entry")
            for child in sorted(folder.iterdir()):
                if child.name == ".system":
                    continue
                name = child.name
                skill_name = name
                location = f"{relative}/{name}"
                source = location
                info = entry_stat(child)
                record = records.get(name) if agent == "codex" else None
                if agent == "claude" and symlink(info):
                    destination = self.link_destination(child)
                    if destination.parent == self.full(".agents/skills"):
                        skill_name = destination.name
                        source = f".agents/skills/{skill_name}"
                        record = records.get(skill_name)
                add(
                    "skills",
                    agent,
                    location,
                    name,
                    info,
                    skillName=skill_name,
                    skillSource=source,
                    group=repository(record),
                )

    def verify(self, data, items):
        if self.root_identity() != data["rootIdentity"]:
            raise ValueError("Removal root changed; rescan and select again")
        for entry in items:
            relative = entry["relative"]
            if (
                self.parents(relative) != entry["parents"]
                or self.fingerprint(relative) != entry["snapshot"]
            ):
                raise ValueError(
                    f"Content changed; rescan and select again: {self.full(relative)}"
                )
        if (
            any(entry["kind"] == "skills" for entry in items)
            and self.fingerprint(self.lock) != data["lockSnapshot"]
        ):
            raise ValueError("Skill lock changed; rescan and select again")

    def related_links(self, items):
        removed = {self.full(entry["relative"]) for entry in items}
        sources = [
            self.full(entry["relative"])
            for entry in items
            if entry["kind"] == "skills" and entry["agent"] == "codex"
        ]

        def walk(path):
            info = entry_stat(path)
            if symlink(info) and path not in removed:
                target = self.link_destination(path)
                shared = any(
                    source != target and source.is_relative_to(target)
                    for source in sources
                )
                if shared or any(
                    target.is_relative_to(source) for source in sources
                ):
                    yield path, target, shared
            elif directory(info):
                for child in path.iterdir():
                    yield from walk(child)

        # A symlinked agent parent may point outside the removal root.
        if sources and not symlink(entry_stat(self.full(".claude"))):
            yield from walk(self.full(".claude/skills"))

    def atomic_lock_write(self, lock):
        self.parents(self.lock)
        destination = self.full(self.lock)
        info = entry_stat(destination)
        if not regular(info):
            raise ValueError(f"Not a regular file: {destination}")
        with NamedTemporaryFile(
            "w", dir=destination.parent, encoding="utf-8", delete=False
        ) as temporary:
            path = Path(temporary.name)
            try:
                json.dump(lock, temporary, indent=2, ensure_ascii=False)
                temporary.write("\n")
                os.fchmod(
                    temporary.fileno(), stat.S_IMODE(info.st_mode) & 0o777
                )
                temporary.close()
                path.replace(destination)
            finally:
                path.unlink(missing_ok=True)

    def save(self, data):
        fd = os.open(
            self.manifest,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream)

    def rows(self, entries):
        for entry in entries:
            if entry["kind"] == "rules":
                print(f"{entry['id']}\trules\t-\t{rule_label(entry)}")
        skills = [entry for entry in entries if entry["kind"] == "skills"]
        if self.scope == "global":
            for name, group, members in skill_groups(skills):
                ids = ",".join(str(entry["id"]) for entry in members)
                print(
                    f"{ids}\tskills\t{display(group)}\t{display(name)} {' '.join(map(label, members))}"
                )
        else:
            for entry in skills:
                print(
                    f"{entry['id']}\tskills\t{display(entry['group'])}\t{AGENTS[entry['agent']]} / "
                    f"{display(entry['name'])} [{entry['type']}]"
                )

    def preview(self, items):
        print(len(items))
        print(
            f"\033[1;36mRemoval scope:\033[0m {self.scope} ({display(self.root)})"
        )
        print("\033[1;36mRemoval targets:\033[0m")
        for entry in items:
            if entry["kind"] == "rules":
                path = red(display(self.full(entry["relative"])))
                print(f"  {rule_label(entry)}\n    {label(entry)} {path}")
        for entry in items:
            if entry["kind"] == "skills":
                path = red(display(self.full(entry["relative"])))
                print(
                    f"  {entry['agent']} / {display(entry['name'])} [{entry['type']}]: {path}"
                )
        lock = self.read_lock() or {}
        names = [
            display(entry["name"])
            for entry in items
            if entry["kind"] == "skills"
            and entry["agent"] == "codex"
            and entry["name"] in lock.get("skills", {})
        ]
        if names:
            action = yellow("Remove lock entries")
            print(
                f"  {action} ({', '.join(names)}): {red(display(self.full(self.lock)))}"
            )
        for path, target, shared in self.related_links(items):
            link = f"{display(path)} -> {display(target)}"
            if self.scope == "global" and shared:
                print(
                    yellow(
                        f"WARNING: Shared Claude skills directory link will be kept: {link}; removing the selected skills also affects Claude."
                    )
                )
            else:
                print(
                    yellow(
                        f"WARNING: Claude link will be kept: {link}; it will become broken if its target is removed."
                    )
                )

    def remove(self, data, items):
        lock = self.read_lock()
        codex = [
            entry
            for entry in items
            if entry["kind"] == "skills" and entry["agent"] == "codex"
        ]
        if codex and lock is None:
            raise ValueError("Invalid skill lock; nothing removed")
        lock_records = lock.get("skills", {}) if lock is not None else {}
        updates_lock = any(entry["name"] in lock_records for entry in codex)
        rules = [entry for entry in items if entry["kind"] == "rules"]
        self.verify(data, items)

        succeeded, failed, removed_skills, outcomes = self.remove_entries(items)
        self.print_rule_results(rules, outcomes)
        if updates_lock and removed_skills:
            failed += self.update_skill_lock(
                data, lock, lock_records, removed_skills
            )
        note = (
            " (installation targets"
            + (" / lock update" if updates_lock else "")
            + ")"
            if rules
            else ""
        )
        print(f"\nResults: {succeeded} succeeded, {failed} failed{note}")
        if any(entry["kind"] == "skills" for entry in items):
            print(
                "Remove skills for the selected agents; preserve .system entries."
            )
        return int(failed > 0)

    def remove_entries(self, items):
        succeeded = failed = 0
        removed_skills = []
        outcomes = {}
        for entry in items:
            relative = entry["relative"]
            path = self.full(relative)
            info_label = f"{entry['agent']} / {display(entry['name'])}"
            try:
                if (
                    self.parents(relative) != entry["parents"]
                    or self.fingerprint(relative) != entry["snapshot"]
                ):
                    raise ValueError(
                        f"Content changed; rescan and select again: {path}"
                    )
                if entry["type"] == "directory" and entry["kind"] == "skills":
                    shutil.rmtree(path)
                else:
                    path.unlink()
                succeeded += 1
                outcomes[entry["id"]] = None
                if entry["kind"] == "skills":
                    print(
                        f"  {green('OK removed')} {info_label}: {display(path)}"
                    )
                    if entry["agent"] == "codex":
                        removed_skills.append(entry["name"])
            except (OSError, ValueError) as error:
                failed += 1
                outcomes[entry["id"]] = str(error)
                if entry["kind"] == "skills":
                    print(
                        red(f"  FAIL {info_label}: {display(path)}: {error}"),
                        file=sys.stderr,
                    )

        return succeeded, failed, removed_skills, outcomes

    def print_rule_results(self, rules, outcomes):
        for entry in rules:
            error = outcomes[entry["id"]]
            path = display(self.full(entry["relative"]))
            status = red("FAIL") if error else green("OK removed")
            print(f"  {status} {rule_label(entry)}")
            if error:
                print(
                    red(f"    FAIL {label(entry)} {path}: {display(error)}"),
                    file=sys.stderr,
                )
            else:
                print(f"    {green('OK')} {label(entry)} {path}")
        if rules:
            complete = sum(outcomes[entry["id"]] is None for entry in rules)
            print(
                f"Rules: {complete} removed, 0 partial, {len(rules) - complete} failed"
            )

    def update_skill_lock(self, data, lock, lock_records, removed_skills):
        try:
            if self.fingerprint(self.lock) != data["lockSnapshot"]:
                raise ValueError("Skill lock changed during deletion")
            for name in removed_skills:
                lock_records.pop(name, None)
            self.atomic_lock_write(lock)
            print(f"{green('Updated lock:')} {display(self.full(self.lock))}")
        except (OSError, ValueError) as error:
            print(red(f"  FAIL lock update: {error}"), file=sys.stderr)
            return 1
        return 0

    def select(self, data, args):
        data["entries"] = [
            entry for entry in data["entries"] if not entry.get("external")
        ]
        data["externalLinks"] = []
        data["selected"] = list(
            dict.fromkeys(
                int(value) for group in args for value in group.split(",")
            )
        )
        if not set(data["selected"]) <= {
            entry["id"] for entry in data["entries"]
        }:
            raise ValueError("Invalid removal selection")
        self.save(data)

    def collect_linked_skills(self, data, items):
        links = []
        for path, _, shared in (
            self.related_links(items) if self.scope == "global" else ()
        ):
            if shared or path.is_relative_to(
                self.full(".claude/skills/.system")
            ):
                continue
            relative = str(path.relative_to(self.root))
            links.append(
                dict(
                    kind="skills",
                    type="link",
                    agent="claude",
                    relative=relative,
                    name=str(path.relative_to(self.full(".claude/skills"))),
                    external=True,
                    **self.snapshot(relative),
                )
            )
            print(f"  {red(display(path))} -> {display(os.readlink(path))}")
        data["externalLinks"] = links
        self.save(data)

    def load_manifest(self):
        data = read_json(self.manifest)
        if (
            data["scope"] != self.scope
            or data["root"] != str(self.root)
            or data["rootIdentity"] != self.root_id
        ):
            raise ValueError(
                "Removal scope or root changed; rescan and select again"
            )
        if data["piRulePath"] and data["piRulePath"] != self.pi_rule:
            raise ValueError("Pi rule path changed; rescan and select again")
        return data

    def run(self, action, args):
        if action == "scan":
            self.save(self.scan(*(value == "1" for value in args)))
            return 0
        data = self.load_manifest()
        if action == "rows":
            self.rows(data["entries"])
            return 0
        if action == "select":
            self.select(data, args)
            return 0

        items = [
            entry
            for entry in data["entries"]
            if entry["id"] in data["selected"]
        ]
        if not items:
            print("No removal targets selected.")
            return 0
        self.verify(data, items)
        if action == "linked-skills":
            self.collect_linked_skills(data, items)
        elif action == "include-links":
            links = data.get("externalLinks", [])
            self.verify(data, links)
            for entry in links:
                entry["id"] = len(data["entries"])
                data["entries"].append(entry)
                data["selected"].append(entry["id"])
            data["externalLinks"] = []
            self.save(data)
        elif action == "preview":
            self.preview(items)
        elif action == "remove":
            return self.remove(data, items)
        else:
            raise ValueError("Unknown removal action")
        return 0
