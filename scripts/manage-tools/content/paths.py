"""Paths and provenance shared by the installed-content views."""

import os
import json
import stat
import errno
from pathlib import Path


UNKNOWN = "Unknown / local"
ANTIGRAVITY_CONFIG = ".gemini/config"
ANTIGRAVITY_RULES = f"{ANTIGRAVITY_CONFIG}/rules"
SKILL_DIRECTORIES = {
    "codex": ".agents/skills",
    "claude": ".claude/skills",
    "agy": f"{ANTIGRAVITY_CONFIG}/skills",
}
MISSING_TARGET = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}


def entry_stat(path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def target_stat(path):
    try:
        return os.stat(path)
    except OSError as error:
        if error.errno not in MISSING_TARGET:
            raise
        return None


def directory(info):
    return info is not None and stat.S_ISDIR(info.st_mode)


def regular(info):
    return info is not None and stat.S_ISREG(info.st_mode)


def symlink(info):
    return info is not None and stat.S_ISLNK(info.st_mode)


def lock_path(scope):
    return (
        "skills-lock.json" if scope == "project" else ".agents/.skill-lock.json"
    )


def metadata_origin(record):
    if isinstance(record, dict):
        return str(record.get("source") or record.get("sourceUrl") or UNKNOWN)
    return UNKNOWN


def reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def read_json(file):
    return json.loads(
        Path(file).read_text(encoding="utf-8"),
        parse_constant=reject_json_constant,
    )


def display(value):
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def safe_root(value, label):
    if not os.path.isabs(value) or os.path.abspath(value) == "/":
        raise ValueError(f"Unsafe {label}")
    return Path(value)
