"""Session catalogs and their isolated download workers."""

import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import dataclass

from rules import parse_waza, installation
from skills import parse_catalog

from content.loading import Job, run


GITHUB = "https://github.com/"
API = "https://api.github.com/repos/"
RAW = "https://raw.githubusercontent.com/"
WAZA = "tw93/Waza"
GWYNTORIA = "gwyntoria/skills"


@dataclass(frozen=True)
class SkillSource:
    repository: str
    kind: str = "skill_archive"
    defaults: str = ""


SKILL_SOURCES = (
    SkillSource(
        "tw93/waza", defaults="check health hunt learn read think ui write"
    ),
    SkillSource("tw93/kami", "skill_kami"),
    SkillSource(
        "mattpocock/skills",
        "skill_homepage",
        "setup-matt-pocock-skills grill-with-docs to-spec to-tickets "
        "improve-codebase-architecture implement-spec writing-for-agents codebase-design wayfinder",
    ),
    SkillSource("humanlayer/skills", "skill_fixed", "show-me"),
    SkillSource(GWYNTORIA, defaults="how why"),
    SkillSource("titanwings/distilly"),
)
WAZA_DEFAULTS = {"waza-waza-anti-patterns", "waza-waza-durable-context"}


class InvalidRule(ValueError):
    pass


def download(url, target, phase):
    transfer = target.parent / "transfer"
    staging = transfer.with_name("next-transfer")
    staging.write_text(f"{phase}\n{target}\n")
    staging.replace(transfer)
    subprocess.run(
        [
            "curl",
            "-fLsS",
            "--no-compressed",
            "--connect-timeout",
            "10",
            "--no-buffer",
            "-D",
            f"{target}.headers",
            "-o",
            str(target),
            url,
        ],
        check=True,
    )
    return target


def skill_worker(kind, repository, directory):
    if kind == "skill_fixed":
        print("show-me")
    elif kind == "skill_homepage":
        path = download(
            "https://www.aihero.dev/skills",
            directory / "skills.html",
            "Downloading catalog",
        )
        parse_catalog.main("homepage", path)
    elif kind == "skill_archive":
        path = download(
            f"https://codeload.github.com/{repository}/tar.gz/HEAD",
            directory / "skills.tar.gz",
            "Downloading archive",
        )
        parse_catalog.main("archive", path)
    elif kind == "skill_kami":
        path = download(
            f"{RAW}{repository}/HEAD/skills/kami/SKILL.md",
            directory / "SKILL.md",
            "Downloading SKILL.md",
        )
        name = parse_catalog.skill_name(path.read_text(encoding="utf-8"))
        if name is not None:
            print(name)


def git_snapshot(directory, pinned):
    (directory / "transfer").write_text("Git fallback\n\n")
    rules = directory / "rules"
    rules.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=directory) as checkout:
        repo = Path(checkout) / "repo"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--no-checkout",
                "--single-branch",
                "--branch",
                "main",
                f"{GITHUB}{WAZA}.git",
                str(repo),
            ],
            check=True,
        )
        command = ["git", "-C", str(repo)]
        commit = subprocess.check_output(
            [*command, "rev-parse", "HEAD"], text=True
        ).strip()
        if pinned and pinned != commit:
            subprocess.run(
                [
                    *command,
                    "fetch",
                    "--quiet",
                    "--depth",
                    "1",
                    "origin",
                    pinned,
                ],
                check=True,
            )
            commit = pinned
        parse_waza.validate_commit(commit)
        tree = directory / "waza-tree"
        tree.write_bytes(
            subprocess.check_output(
                [*command, "ls-tree", "-z", f"{commit}:rules"]
            )
        )
        parse_waza.main("tree", tree, directory)
        for row in (directory / "blobs").read_text().splitlines():
            blob, name = row.split("\t")
            (rules / f"{name}.md").write_bytes(
                subprocess.check_output([*command, "cat-file", "blob", blob])
            )
    (directory / "resolved-commit").write_text(commit)


def waza_catalog(directory):
    pinned = ""
    (directory / "rules").mkdir()
    try:
        commit_data = download(
            f"{API}{WAZA}/commits/main",
            directory / "commit.json",
            "Resolving commit",
        )
        pinned = parse_waza.commit(commit_data)
        catalog = download(
            f"{API}{WAZA}/contents/rules?ref={pinned}",
            directory / "catalog.json",
            "Downloading catalog",
        )
        names = parse_waza.catalog(catalog)
    except (OSError, ValueError, subprocess.CalledProcessError):
        git_snapshot(directory, pinned)
    else:
        (directory / "names").write_text("\n".join(names))
        (directory / "resolved-commit").write_text(pinned)


def worker(kind, value, ref, directory, root, mode, archive_url):
    if kind.startswith("skill_"):
        skill_worker(kind, value, directory)
    elif kind == "rules-waza":
        waza_catalog(directory)
    elif kind == "waza-fallback":
        git_snapshot(directory, ref)
    elif kind == "waza-body":
        path = download(
            f"{RAW}{WAZA}/{parse_waza.validate_commit(ref)}/rules/{value.removeprefix('waza-')}.md",
            directory / "rule.md",
            "Downloading rule",
        )
        try:
            installation.rule_body(path, waza=True)
        except ValueError as error:
            raise InvalidRule(str(error)) from error
    else:
        if mode == "local" and kind == "rules-published":
            path = download(
                archive_url, directory / "source.tar.gz", "Downloading archive"
            )
            subprocess.run(
                [
                    "tar",
                    "-xzf",
                    str(path),
                    "-C",
                    str(directory),
                    "--",
                    "skills-main/rules",
                ],
                check=True,
            )
            root = directory / "skills-main"
        for name in installation.names(root / "rules"):
            print(name)


class Catalogs:
    def __init__(self, root, mode, archive_url, work):
        self.root = root
        self.mode = mode
        self.archive_url = archive_url
        self.work = work
        self.cache = {}

    def load(self, title, specs, draw):
        pending = [spec for spec in specs if spec not in self.cache]
        errors = {}
        if pending:
            with TemporaryDirectory(dir=self.work) as batch:
                jobs = [
                    Job(kind, label, value, ref, Path(batch) / str(index))
                    for index, (kind, label, value, ref) in enumerate(pending)
                ]
                run(
                    jobs,
                    [
                        sys.executable,
                        "-B",
                        str(self.root / "scripts/manage-tools/main.py"),
                        "--worker",
                        str(self.root),
                        self.mode,
                        self.archive_url,
                    ],
                    lambda jobs: draw(title, jobs),
                )
                for spec, job in zip(pending, jobs):
                    result = self.collect(spec, job)
                    if result:
                        errors[spec] = result
        return {
            spec: self.cache[spec] for spec in specs if spec in self.cache
        }, errors

    def collect(self, spec, job):
        if job.status:
            return job.status, error_text(job)
        filename = "names" if job.kind == "rules-waza" else "output"
        lines = list(
            dict.fromkeys((job.directory / filename).read_text().splitlines())
        )
        if job.kind.startswith("skill_") and not lines:
            return 1, f"{job.label}: empty catalog"
        directory = job.directory
        if job.kind.startswith("waza-") or job.kind == "rules-waza":
            retained = self.work / f"catalog-{len(self.cache)}"
            directory.rename(retained)
            directory = retained
        self.cache[spec] = (
            lines,
            directory if directory != job.directory else None,
        )
        return None


def error_text(job):
    detail = (job.directory / "error").read_text(errors="replace").strip()
    return f"{job.label}: {detail or f'exit {job.status}'}"
