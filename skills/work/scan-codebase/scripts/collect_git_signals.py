#!/usr/bin/env python3
"""Collect five Git-history signals without reading implementation files."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


CRISIS_PATTERN = re.compile(r"revert|hotfix|emergency|rollback", re.IGNORECASE)


class ScanError(RuntimeError):
    """Raised when Git cannot produce a complete scan."""


def run_git(repo: Path, args: list[str]) -> str:
    """Run Git and return decoded stdout.

    Args:
        repo: Repository root passed to Git.
        args: Git arguments excluding the executable and working directory.

    Returns:
        Command stdout with invalid bytes replaced.

    Raises:
        ScanError: Git exits unsuccessfully.
    """
    command = ["git", "-C", str(repo), *args]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise ScanError(
            f"{' '.join(shlex.quote(part) for part in command)}: {stderr}"
        )
    return result.stdout.decode("utf-8", errors="replace")


def git_command(args: list[str]) -> str:
    """Render a reproducible Git command for the evidence record.

    Args:
        args: Git arguments excluding the executable.

    Returns:
        Shell-readable command text.
    """
    return "git " + " ".join(shlex.quote(part) for part in args)


def normalize_scope(root: Path, repo_arg: Path, scopes: list[str]) -> list[str]:
    """Resolve the default Git pathspec scope.

    Args:
        root: Resolved Git repository root.
        repo_arg: User-provided repository or subdirectory.
        scopes: Explicit scope arguments.

    Returns:
        Relative Git pathspecs.
    """
    if scopes:
        return scopes
    try:
        relative = repo_arg.resolve().relative_to(root)
    except ValueError:
        return ["."]
    return [relative.as_posix()] if relative.as_posix() != "." else ["."]


def pathspecs(scopes: list[str], excludes: list[str]) -> list[str]:
    """Build inclusive and exclusive Git pathspecs.

    Args:
        scopes: Included paths.
        excludes: Excluded paths.

    Returns:
        Git pathspec arguments.
    """
    result = list(scopes)
    result.extend(f":(exclude){path}" for path in excludes)
    return result


def count_paths(output: str, top: int) -> list[dict[str, Any]]:
    """Count path occurrences in name-only Git output.

    Args:
        output: Newline-separated paths.
        top: Maximum result count.

    Returns:
        Ranked path/count objects.
    """
    counts = collections.Counter(
        line for line in output.splitlines() if line.strip()
    )
    return [
        {"path": path, "touches": count}
        for path, count in counts.most_common(top)
    ]


def parse_shortlog(output: str) -> list[dict[str, Any]]:
    """Parse `git shortlog -sn` output.

    Args:
        output: Shortlog text.

    Returns:
        Contributor commit counts and shares.
    """
    contributors: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)", line)
        if match:
            contributors.append(
                {"name": match.group(2), "commits": int(match.group(1))}
            )
    total = sum(item["commits"] for item in contributors)
    for item in contributors:
        item["share_percent"] = (
            round(item["commits"] * 100 / total, 1) if total else 0.0
        )
    return contributors


def shift_month(month: str, offset: int) -> str:
    """Shift a YYYY-MM value by a number of months.

    Args:
        month: Calendar month in YYYY-MM form.
        offset: Signed month offset.

    Returns:
        Shifted calendar month.
    """
    year, number = (int(value) for value in month.split("-"))
    index = year * 12 + number - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def activity_summary(
    months: collections.Counter[str], max_months: int
) -> dict[str, Any]:
    """Summarize lifetime and recent monthly activity.

    Args:
        months: Commit counts keyed by YYYY-MM.
        max_months: Maximum monthly rows included in output.

    Returns:
        Lifetime bounds, recent rows, and adjacent six-month totals.
    """
    if not months:
        return {
            "first_month": None,
            "last_month": None,
            "months": [],
            "recent_6": 0,
            "previous_6": 0,
        }
    ordered = sorted(months)
    current = dt.date.today().strftime("%Y-%m")
    visible = [
        shift_month(current, offset) for offset in range(-(max_months - 1), 1)
    ]
    recent_keys = [shift_month(current, offset) for offset in range(-5, 1)]
    previous_keys = [shift_month(current, offset) for offset in range(-11, -5)]
    return {
        "first_month": ordered[0],
        "last_month": ordered[-1],
        "months": [
            {"month": month, "commits": months.get(month, 0)}
            for month in visible
        ],
        "recent_6": sum(months.get(month, 0) for month in recent_keys),
        "previous_6": sum(months.get(month, 0) for month in previous_keys),
    }


def commit_count(repo: Path, since: str | None = None) -> int:
    """Count commits in the repository or a time window.

    Args:
        repo: Git repository root.
        since: Optional Git date expression.

    Returns:
        Commit count.
    """
    args = ["rev-list", "--count", "HEAD"]
    if since:
        args.append(f"--since={since}")
    return int(run_git(repo, args).strip())


def collect(args: argparse.Namespace) -> dict[str, Any]:
    """Collect and structure all scan signals.

    Args:
        args: Parsed command-line options.

    Returns:
        JSON-serializable scan evidence.
    """
    repo_arg = Path(args.repo).resolve()
    root_text = run_git(repo_arg, ["rev-parse", "--show-toplevel"]).strip()
    root = Path(root_text)
    run_git(root, ["rev-parse", "--verify", "HEAD"])

    scopes = normalize_scope(root, repo_arg, args.scope)
    paths = pathspecs(scopes, args.exclude)

    churn_args = [
        "log",
        "--format=",
        "--name-only",
        f"--since={args.since}",
        "--",
        *paths,
    ]
    churn = count_paths(run_git(root, churn_args), args.top)

    lifetime_shortlog_args = ["shortlog", "-sn", "--no-merges", "HEAD"]
    recent_shortlog_args = [
        "shortlog",
        "-sn",
        "--no-merges",
        f"--since={args.since}",
        "HEAD",
    ]
    lifetime_contributors = parse_shortlog(
        run_git(root, lifetime_shortlog_args)
    )
    recent_contributors = parse_shortlog(run_git(root, recent_shortlog_args))

    bug_args = [
        "log",
        "--regexp-ignore-case",
        "--extended-regexp",
        "--grep=fix|bug|broken",
        "--name-only",
        "--format=",
        f"--since={args.since}",
        "--",
        *paths,
    ]
    bug_files = count_paths(run_git(root, bug_args), args.top)
    bug_commit_args = [
        "log",
        "--regexp-ignore-case",
        "--extended-regexp",
        "--grep=fix|bug|broken",
        "--format=%H",
        f"--since={args.since}",
        "--",
        *paths,
    ]
    bug_keyword_commits = len(run_git(root, bug_commit_args).splitlines())

    monthly_args = ["log", "--format=%ad", "--date=format:%Y-%m"]
    month_counts = collections.Counter(run_git(root, monthly_args).splitlines())

    crisis_args = [
        "log",
        "--format=%h%x09%ad%x09%s",
        "--date=short",
        f"--since={args.since}",
    ]
    crisis_lines = []
    for line in run_git(root, crisis_args).splitlines():
        if CRISIS_PATTERN.search(line):
            commit_hash, date, subject = (line.split("\t", 2) + ["", ""])[:3]
            crisis_lines.append(
                {"commit": commit_hash, "date": date, "subject": subject}
            )

    branch = run_git(root, ["branch", "--show-current"]).strip() or "DETACHED"
    head = run_git(root, ["rev-parse", "HEAD"]).strip()
    overlap = sorted(
        set(item["path"] for item in churn)
        & set(item["path"] for item in bug_files),
        key=lambda path: (
            -next(item["touches"] for item in churn if item["path"] == path),
            path,
        ),
    )

    recent_names = {item["name"] for item in recent_contributors}
    absent_lifetime_leaders = [
        item["name"]
        for item in lifetime_contributors[:5]
        if item["name"] not in recent_names
    ]

    return {
        "scan": {
            "repository": str(root),
            "branch": branch,
            "head": head,
            "since": args.since,
            "scope": scopes,
            "exclude": args.exclude,
            "top": args.top,
            "path_scoped_signals": ["churn", "bug_hotspots"],
            "repository_wide_signals": [
                "contributors",
                "monthly_activity",
                "crisis_commits",
            ],
            "lifetime_commits": commit_count(root),
            "window_commits": commit_count(root, args.since),
        },
        "churn": {
            "command": git_command(churn_args),
            "files": churn,
        },
        "contributors": {
            "lifetime_command": git_command(lifetime_shortlog_args),
            "window_command": git_command(recent_shortlog_args),
            "lifetime": lifetime_contributors,
            "window": recent_contributors,
            "absent_lifetime_leaders": absent_lifetime_leaders,
        },
        "bug_hotspots": {
            "command": git_command(bug_args),
            "matching_commit_command": git_command(bug_commit_args),
            "matching_commits": bug_keyword_commits,
            "files": bug_files,
            "churn_overlap": overlap,
        },
        "monthly_activity": {
            "command": git_command(monthly_args),
            **activity_summary(month_counts, args.max_months),
        },
        "crisis_commits": {
            "command": git_command(crisis_args)
            + " | filter: revert|hotfix|emergency|rollback",
            "count": len(crisis_lines),
            "commits": crisis_lines,
        },
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line options.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=".",
        help="Git repository or a subdirectory used as the default scope",
    )
    parser.add_argument(
        "--since",
        default="1 year ago",
        help="Git date expression for the current window",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Included repository-relative path; repeat as needed",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Excluded repository-relative path; repeat as needed",
    )
    parser.add_argument(
        "--top", type=int, default=20, help="Number of hotspot paths to retain"
    )
    parser.add_argument(
        "--max-months",
        type=int,
        default=24,
        help="Recent calendar months to include",
    )
    parsed = parser.parse_args()
    if parsed.top < 1 or parsed.max_months < 12:
        parser.error(
            "--top must be positive and --max-months must be at least 12"
        )
    return parsed


def main() -> int:
    """Run the collector and emit JSON.

    Returns:
        Process exit status.
    """
    try:
        evidence = collect(parse_args())
    except (OSError, ScanError, ValueError) as error:
        print(f"scan-codebase: {error}", file=sys.stderr)
        return 1
    json.dump(evidence, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
