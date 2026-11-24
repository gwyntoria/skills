"""Extract names from the supported Skills catalog formats."""

import re
import sys


def skills_cli(text):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    section = text.split("Available Skills", 2)
    return (
        re.findall(
            r"^[│|] {3,4}([a-zA-Z0-9][a-zA-Z0-9._-]*)[ \t]*$", section[1], re.M
        )
        if len(section) > 1
        else []
    )


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


def main():
    mode = sys.argv[1]
    text = sys.stdin.read()
    if mode == "cli":
        names = skills_cli(text)
        error = "skills --list returned no recognisable skill names."
    else:
        names = homepage(text)
        error = "no main skills found on the Matt Pocock skills page."
    if not names:
        sys.exit(f"Error: {error}")
    print("\n".join(dict.fromkeys(names)))


if __name__ == "__main__":
    main()
