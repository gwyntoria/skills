---
name: scan-codebase
description: "Inspect a Git repository's history before reading implementation code, then produce a current-stage risk map and a prioritized code-reading order. Invoke manually with $scan-codebase."
disable-model-invocation: true
---

# Scan Codebase

Build a **risk map** from repository history before opening implementation files. Treat every conclusion as a time-bounded hypothesis, then stop after reporting what code should be read first.

## 1. Set The Boundary

Read repository agent instructions that govern command execution. Defer implementation-code reading until the history scan is complete.

Resolve these inputs:

- Repository: use the current repository unless the user names another one.
- Window: use `1 year ago` unless the user specifies another period.
- Scope: use the current subdirectory when invoked inside one; otherwise use the repository root. Prefer a clear source root such as `src/`, `app/`, or `lib/` when the repository layout makes one unambiguous.
- Result count: use the top 20 paths.

Completion criterion: the repository, time window, and path scope are explicit before collection begins.

## 2. Collect The Five Signals

Run:

```bash
python3 <skill-base-dir>/scripts/collect_git_signals.py --repo <repository> --since "1 year ago"
```

Replace `<skill-base-dir>`, `<repository>`, and the time window with resolved values. Use repeatable `--scope PATH` and `--exclude PATH` arguments when the scan boundary needs adjustment.

The script emits structured JSON for:

1. File churn in the selected window.
2. Lifetime and recent contributor concentration.
3. Paths touched by bug-related commits.
4. Monthly commit activity.
5. Revert, hotfix, emergency, and rollback commits.

Read the complete JSON. If lockfiles, generated outputs, vendored dependencies, changelogs, or bulk-generated paths dominate the churn list, narrow the scope and rerun. Report both the final scope and any excluded paths.

Completion criterion: all five signal objects are present, the command reports no errors, and obvious non-source noise does not dominate the final hotspots.

## 3. Build The Risk Map

Interpret signals together:

- Prioritize paths present in both `churn.files` and `bug_hotspots.files`. These are investigation targets, not proven defects.
- Treat high churn without bug overlap as active-development or architectural-change evidence until code inspection distinguishes them.
- Treat contributor concentration as continuity risk when one author dominates lifetime history or a former leading author is absent from the current window.
- Compare recent six-month activity with the preceding six months. Classify the current stage as `growth`, `steady delivery`, `release-batched`, `maintenance`, `contracting`, `dormant`, or `indeterminate`.
- Interpret crisis commits relative to the number of commits in the same window. A list of matching subjects is evidence about commit language and delivery events, not direct proof of test or deployment quality.

For every material conclusion, name the supporting field or path, give `high`, `medium`, or `low` confidence, and state the strongest plausible alternative explanation.

Apply these evidence limits:

- Absolute file-touch counts are not normalized by file size or complexity.
- Bug hotspots depend on commit-message discipline.
- Squash merges, bots, aliases, and shared accounts distort contributor counts.
- Commit volume measures repository activity, not productivity or team health.
- The current calendar month may be incomplete and should be interpreted as partial data.
- Renames, generated changes, monorepos, and migrations can dominate path counts.

Completion criterion: the stage hypothesis and every priority path are supported by at least two compatible signals, or are explicitly labeled single-signal and low confidence.

## 4. Report And Stop

Use this shape:

```markdown
## Scan boundary
- Repository, branch, HEAD, window, scope, exclusions

## Current stage
- Hypothesis: <stage>
- Confidence: <high|medium|low>
- Evidence: <monthly activity, contributor continuity, crisis frequency>
- Alternative explanation: <strongest competing interpretation>

## Risk map
| Priority | Path or area | Churn | Bug touches | Why it matters | Confidence |

## Team and delivery signals
- Contributor concentration
- Maintainer continuity
- Crisis pattern

## Read first
1. <path>: <question to answer while reading>
2. <path>: <question to answer while reading>
3. <path>: <question to answer while reading>

## Evidence limits
- <limitations that materially affect this run>
```

Use exact counts from the JSON. Keep observations separate from interpretations. Ask to continue only when implementation reading is required; this skill's endpoint is the history-grounded analysis and reading order.

Completion criterion: the report accounts for all five signals, identifies the current stage with calibrated confidence, provides up to three concrete reading targets, and exposes material blind spots.
