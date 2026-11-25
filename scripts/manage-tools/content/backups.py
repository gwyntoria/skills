"""Manage backup directories created by Skill / Rule removal."""

import re
import sys
import shutil
import secrets
from string import digits, ascii_letters

from paths import directory, safe_root, entry_stat


BACKUP_NAME = re.compile(r"\.agent-(skills|rules)-backup-[A-Za-z0-9]{6}")


def new_backup(home, kind):
    # Retain the existing six-character suffix so old and new backups share
    # the same discovery and cleanup rules.
    while True:
        suffix = "".join(
            secrets.choice(ascii_letters + digits) for _ in range(6)
        )
        folder = home / f".agent-{kind}-backup-{suffix}"
        try:
            folder.mkdir(mode=0o700)
            return folder / "removal.tar"
        except FileExistsError:
            continue


def list_backups(home, kind):
    return [
        entry.name
        for entry in sorted(home.iterdir())
        if entry.name.startswith(f".agent-{kind}-backup-")
        and BACKUP_NAME.fullmatch(entry.name)
        and directory(entry_stat(entry))
    ]


def remove_backups(home, kind, names):
    folders = []
    for name in names:
        match = BACKUP_NAME.fullmatch(name)
        if not match or match[1] != kind:
            raise ValueError("Invalid backup directory name")
        folder = home / name
        info = entry_stat(folder)
        if not directory(info):
            raise ValueError(f"Backup is no longer a directory: {name}")
        folders.append((folder, info.st_dev, info.st_ino))

    for folder, device, inode in folders:
        current = entry_stat(folder)
        if not directory(current) or (current.st_dev, current.st_ino) != (
            device,
            inode,
        ):
            raise ValueError(f"Backup changed: {folder}")
        shutil.rmtree(folder)
        print(f"Removed backup: \033[31m{folder}\033[0m")


if __name__ == "__main__":
    try:
        action, home_arg, kind, *names = sys.argv[1:]
        if kind not in ("skills", "rules"):
            raise ValueError("Invalid backup category")
        home = safe_root(home_arg, "HOME")
        if action == "list":
            for name in list_backups(home, kind):
                print(name)
        elif action == "remove":
            remove_backups(home, kind, names)
        else:
            raise ValueError("Unknown backup action")
    except (OSError, ValueError) as error:
        sys.exit(str(error))
