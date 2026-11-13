---
name: daily-weekly-reporting
description: Use when writing Chinese daily reports, weekly reports, 日报, 周报, 工作总结, or Git-based status updates, especially when all-branch commits, local uncommitted changes, or previous-day unfinished work must be covered.
disable-model-invocation: false
---

# Daily Weekly Reporting

## Overview

Write concise Chinese work reports from repository evidence in the style of
`log/daily-work.md`. Default to a daily report unless the user explicitly asks
for a weekly report. Do not ask for non-Git context; state uncertainty and give
the final draft for review.

## Quick Reference

| Mode | Trigger | Work evidence | Previous report |
| --- | --- | --- | --- |
| Daily | Default, or explicit `日报` | Today's all-branch commits plus current staged, unstaged, and untracked changes | Carry yesterday's `未完成` state forward |
| Weekly | Explicit `周报` or `weekly` | Current-week all-branch commits only | Read for style only |

## Workflow

1. Run `date` and use the repository's local timezone.
2. Read `AGENTS.md` and the recent relevant entries in `log/daily-work.md`.
   Use the document only for structure and tone unless the daily carry-forward
   rule below applies.
3. Set the evidence window:
   - Daily: today `00:00:00` through `23:59:59` by commit date.
   - Weekly: current Monday `00:00:00` through now by commit date.
4. Collect all-branch commits with:

   ```bash
   rtk proxy git log --all --since='<start>' --until='<end>' \
       --date=iso-strict \
       --format='%H%x09%cd%x09%an%x09%D%x09%s'
   ```

   Use plain `git` if `rtk` is unavailable. Expand unclear commits with
   `git show --stat --format=fuller <hash>` and targeted diffs.
5. Build an internal coverage ledger. Every unique commit hash must map to an
   output bullet or be marked as a merge/duplicate already represented by that
   bullet. Do not silently drop branch-only commits.
6. Gather mode-specific evidence, synthesize outcomes, then return only the
   finished report. Do not edit `log/daily-work.md` unless asked.

## Daily Evidence

In addition to today's all-branch commits, inspect all current local changes:

```bash
rtk proxy git status --short --branch -uall
rtk proxy git diff --cached --stat
rtk proxy git diff --stat
rtk proxy git ls-files --others --exclude-standard
```

Read targeted staged, unstaged, and untracked files when the statistics do not
explain their purpose. Report them under `未完成` or explicit local-progress
wording; never present uncommitted work as delivered.

Find yesterday's dated entry in `log/daily-work.md` and read its `未完成` list:

- Move an item to `已完成` only when today's Git evidence proves completion.
- Keep it under `未完成` when no completion evidence exists.
- Rewrite it with current status when evidence shows partial progress.
- Do not infer completion from a related commit title alone.

If the worktree is clean, omit local-change commentary. If there is no entry
for yesterday or no `未完成` section, continue without inventing carry-over work.

Example: when today's commit adds a CPU sampling window but yesterday's item
was "verify whether CPU load affects USB throughput", report the sampling tool
as completed and keep the causal verification unfinished. Related work is not
proof of the original result.

## Weekly Evidence

Use only commits in the current-week all-branch window as work evidence. Do not
include the current worktree, yesterday's unfinished list, stash contents, or
claims copied from earlier reports. Merge commits may support an integration
bullet but must not cause their child commits to be counted twice.

Derive `下周工作计划` only from validation gaps, incomplete implementation, or
follow-up work visible in those commits. If Git does not support a specific
plan, use a restrained verification-oriented plan rather than inventing scope.

## Synthesis And Style

- Group commits by delivered capability, investigation result, or engineering
  outcome. Do not translate one commit into one bullet.
- Distinguish implementation, integration, documentation, testing, and design.
- Preserve exact measurements only when supported by evidence.
- Treat hardware, firmware, network, and long-duration behavior as unverified
  unless commits or test artifacts show validation.
- Write concrete work-log prose with `完成`, `修复`, `新增`, `优化`, `正在验证`,
  and `待继续跟进`. Avoid management-report filler and repetitive summaries.
- Use `思考总结` or `本周工作总结` for causal findings, constraints, tradeoffs,
  and validation gaps grounded in the evidence.
- Follow repository punctuation and mixed Chinese-English spacing rules.

Daily with unfinished work:

```markdown
### YY/MM/DD

#### 工作内容

##### 已完成

1. ...

##### 未完成

1. ...

#### 思考总结

1. ...
```

When no unfinished work exists, omit `已完成` and `未完成` subheadings and list
work directly under `工作内容`.

Weekly:

```markdown
### YY/M/D（周报）

#### 本周完成工作

1. ...

#### 本周工作总结

1. ...

#### 下周工作计划

1. ...
```

## Red Flags

- Using only the current branch because it appears to contain merged work.
- Treating a related commit as proof that yesterday's unfinished item is done.
- Mixing worktree or old-report claims into a weekly report.
- Calling design, local changes, or unverified firmware behavior completed.
- Dropping commits to keep the report short instead of grouping them.
- Asking the user for missing non-Git information.

## Common Mistakes And Rationalizations

| Rationalization | Correction |
| --- | --- |
| "The current branch contains everything important." | Query `--all`; branch-only commits otherwise disappear. |
| "This commit probably closes yesterday's item." | Verify the diff and validation evidence; otherwise keep it unfinished. |
| "The weekly report needs old daily notes for context." | Use old reports for style only; weekly work evidence is this week's commits. |
| "Uncommitted code is functionally complete." | It is still local progress and belongs under `未完成`. |
