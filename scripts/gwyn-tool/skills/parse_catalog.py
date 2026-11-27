"""Read names from the layouts used by the configured skill sources."""

import re
import sys
import tarfile
from pathlib import Path, PurePosixPath


NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*")


def homepage(text):
    section = re.search(
        r"""<section\b[^>]*\baria-labelledby=["']skill-set-heading["'][^>]*>(.*?)</section>""",
        text,
        re.I | re.S,
    )
    if not section:
        return []
    return re.findall(
        r"""<a\b[^>]*\bhref=["'](?:https://www\.aihero\.dev)?/skills-([a-z0-9][a-z0-9-]*)/?["'][^>]*>""",
        section[1],
    )


def skill_paths(paths):
    # Keep the root skill or the repository's published skills/ layout.
    # The configured repositories also have plugin mirrors of those skills.
    paths = set(paths)
    if "SKILL.md" in paths:
        return ["SKILL.md"]
    return sorted(
        path
        for path in paths
        if path.startswith("skills/")
        and path.endswith("/SKILL.md")
        and len(parts := PurePosixPath(path).parts) <= 5
        and not any(
            str(PurePosixPath(*parts[:index], "SKILL.md")) in paths
            for index in range(1, len(parts) - 1)
        )
    )


def skill_name(text):
    # These sources use scalar name fields in standard SKILL.md frontmatter.
    frontmatter = re.match(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not frontmatter:
        raise ValueError("Missing SKILL.md frontmatter")
    fields = frontmatter[1]
    metadata = re.search(
        r"^metadata:[ \t]*\n((?:[ \t]+[^\n]*\n?)*)", fields, re.M
    )
    if metadata and re.search(
        r"^\s*internal:\s*true\s*$", metadata[1], re.M | re.I
    ):
        return None
    match = re.search(
        r"""^name:[ \t]*(['"]?)([a-zA-Z0-9][a-zA-Z0-9._-]*)\1[ \t]*(?:#.*)?$""",
        fields,
        re.M,
    )
    if not match:
        raise ValueError("Missing or invalid SKILL.md name")
    return match[2]


def archive_names(path):
    with tarfile.open(path, mode="r:gz") as archive:
        members = {
            member.name.partition("/")[2]: member
            for member in archive
            if member.isfile() and member.name.endswith("/SKILL.md")
        }
        names = []
        for location in skill_paths(members):
            with archive.extractfile(members[location]) as source:
                names.append(
                    skill_name(
                        source.read().decode("utf-8").replace("\r\n", "\n")
                    )
                )
        return names


def main(mode, path):
    if mode == "archive":
        names = archive_names(path)
    else:
        names = homepage(path.read_text(encoding="utf-8"))
    names = list(
        dict.fromkeys(name for name in names if name and NAME.fullmatch(name))
    )
    if not names:
        raise ValueError("No installable skills found")
    print("\n".join(names))


if __name__ == "__main__":
    try:
        main(sys.argv[1], Path(sys.argv[2]))
    except (
        OSError,
        ValueError,
        tarfile.TarError,
        KeyError,
        TypeError,
        AttributeError,
    ) as error:
        sys.exit(str(error))
