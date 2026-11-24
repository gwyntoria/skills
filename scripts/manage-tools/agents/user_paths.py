"""Verify user-owned Agent paths and construct rechecked removal steps."""

import os
import re
import json
import stat
import shutil
from typing import Callable
from dataclasses import dataclass


def info(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def is_dir(entry):
    return entry is not None and stat.S_ISDIR(entry.st_mode)


def is_file(entry):
    return entry is not None and stat.S_ISREG(entry.st_mode)


def is_link(entry):
    return entry is not None and stat.S_ISLNK(entry.st_mode)


def within(root, path):
    return path.startswith(root + os.sep)


def show(value):
    return json.dumps(value, ensure_ascii=False)


def reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def identity(path):
    entry = info(path)
    if entry is None:
        return None
    return (
        entry.st_dev,
        entry.st_ino,
        entry.st_mode,
        entry.st_uid,
        None if is_dir(entry) else entry.st_mtime_ns,
    )


@dataclass
class Step:
    description: str
    check: Callable[[], None]
    apply: Callable[[], None]
    needs_cli: bool = False


def checked_command(description, executable, apply, *, needs_cli=False):
    before = identity(executable)
    target = os.path.realpath(executable, strict=True)
    target_before = identity(target)

    def check():
        if (
            identity(executable) != before
            or os.path.realpath(executable, strict=True) != target
            or identity(target) != target_before
        ):
            raise ValueError(f"Executable changed {show(executable)}")

    return Step(description, check, apply, needs_cli)


class UserPaths:
    def __init__(self, home, uninstall, warnings):
        if not home or home == "/" or os.getuid() == 0:
            raise ValueError("Unsafe user home")
        if os.path.realpath(home, strict=True) != home:
            raise ValueError("Unsafe user home")
        entry = info(home)
        self.uid = os.getuid()
        if not is_dir(entry) or entry.st_uid != self.uid:
            raise ValueError("Unsafe user home")
        self.home = home
        self.device = entry.st_dev
        self.uninstall = uninstall
        self.warnings = warnings
        self.seen = set()

    def owned(self, entry):
        return entry.st_uid == self.uid and entry.st_dev == self.device

    def safe(self, path):
        if (
            not os.path.isabs(path)
            or os.path.normpath(path) != path
            or not within(self.home, path)
            or re.search(r"[\x00-\x1f\x7f]", path)
        ):
            return False
        shared = os.path.join(self.home, ".agents")
        if path == shared or within(shared, path):
            return False
        entry = info(path)
        if entry is not None and not self.owned(entry):
            return False
        parent = os.path.dirname(path)
        while parent != self.home:
            entry = info(parent)
            if entry is not None and (
                not is_dir(entry)
                or not self.owned(entry)
                or info(os.path.join(parent, ".git"))
            ):
                return False
            parent = os.path.dirname(parent)
        return True

    def json(self, path):
        if not self.safe(path) or not is_file(info(path)):
            return {}
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, encoding="utf-8") as stream:
            if not is_file(os.fstat(stream.fileno())):
                raise ValueError(f"Path changed {show(path)}")
            result = json.load(stream, parse_constant=reject_json_constant)
        return result if isinstance(result, dict) else {}

    def protected_descendant(self, root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            entry = info(path)
            if entry is None:
                continue
            if not self.owned(entry) or name == ".git":
                return path
            if is_dir(entry):
                protected = self.protected_descendant(path)
                if protected:
                    return protected
        return None

    def removal(self, path, label="Delete", recursive=False):
        entry = info(path)
        if entry is None or path in self.seen:
            return None
        if (
            self.uninstall
            and is_link(entry)
            and label.startswith("Delete user")
        ):
            self.warnings[
                f"Only the link can be deleted; target remains for {show(path)}"
            ] = None
        if (
            not self.safe(path)
            or (
                is_dir(entry)
                and (not recursive or info(os.path.join(path, ".git")))
            )
            or not (is_dir(entry) or is_file(entry) or is_link(entry))
        ):
            self.warnings[f"Unprocessed path {show(path)}"] = None
            return None
        protected = self.protected_descendant(path) if is_dir(entry) else None
        if protected:
            self.warnings[
                f"Unprocessed directory {show(path)} contains protected entry {show(protected)}"
            ] = None
            return None

        return self.removal_step(path, label, entry, recursive)

    def removal_step(self, path, label, entry, recursive):
        before = identity(path)
        parent = os.path.dirname(path)
        parent_before = identity(parent)
        self.seen.add(path)

        def check():
            if not self.safe(path) or identity(path) != before:
                raise ValueError(f"Path changed {show(path)}")

        def apply():
            current = info(path)
            if current is None:
                return
            # Credential commands can rewrite files in place. Recheck their
            # permitted location and type after those commands have run.
            if (
                not self.safe(path)
                or identity(parent) != parent_before
                or stat.S_IFMT(current.st_mode) != stat.S_IFMT(entry.st_mode)
                or (
                    is_dir(current)
                    and (not recursive or self.protected_descendant(path))
                )
            ):
                raise ValueError(f"Path changed {show(path)}")
            if is_dir(current):
                shutil.rmtree(path)
            else:
                os.unlink(path)

        return Step(f"{label} {show(path)}", check, apply)
