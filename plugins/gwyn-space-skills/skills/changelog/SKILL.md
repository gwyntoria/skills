---
name: changelog
description: Write, update, or review CHANGELOG.md files and release change summaries using Keep a Changelog conventions. Use when users ask to 编写 changelog, 更新 CHANGELOG, 审核版本记录, prepare an Unreleased section, or check release entries. Not for commit-message review or general code review.
---

# Changelog

Produce a human-readable record of notable project changes, grounded in the
requested release scope and consistent with the existing changelog. Use
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) as the standard.

## Select The Mode

- **Write:** create a draft or edit the requested changelog. A request to
  update a named file authorizes edits to that file; a request for wording or
  a draft returns text only.
- **Review:** inspect and report findings without editing. Edit only when the
  user also asks to fix the changelog.

Read repository instructions and the existing changelog before either mode.
Preserve its language and established formatting unless they conflict with the
standard or the user requests a migration.

## Establish The Evidence Range

Identify the version or `Unreleased` scope and the evidence available for it:
release tags, comparison range, commits, pull requests, issues, diffs, or
user-provided notes. Prefer product behavior and compatibility evidence over
commit subjects. Inspect ambiguous changes before classifying them.

Do not invent a version, release date, impact, compatibility claim, security
claim, or completed work. When the release boundary is missing, write under
`Unreleased` or state that completeness cannot be verified. Keep uncommitted or
unverified work out of a released version unless the user explicitly defines it
as part of that release.

Build an internal coverage ledger that maps every notable change in scope to an
entry or to a reason for omission. Merge commits and multiple implementation
commits may support one user-facing entry.

## Apply The Standard

- Keep the file at `CHANGELOG.md` unless the repository already establishes a
  different name.
- Start with a short statement that all notable changes are documented there.
- Keep `Unreleased` at the top for upcoming changes.
- Add one section for every released version and order releases newest first.
- Format released headings as `## [version] - YYYY-MM-DD`, using ISO 8601 dates.
- Group entries under only the applicable canonical headings:
  - `Added` for new features.
  - `Changed` for changes to existing functionality.
  - `Deprecated` for features planned for removal.
  - `Removed` for removed features.
  - `Fixed` for bug fixes.
  - `Security` for vulnerability-related changes.
- Omit empty category sections.
- Make version headings and comparison ranges linkable when the repository has
  a stable release or comparison URL.
- State whether the project follows Semantic Versioning when that policy is
  established by project evidence.
- Retain withdrawn releases and append `[YANKED]` to their headings.
- Correct published entries when an important change, especially a deprecation,
  removal, security issue, or breaking change, was omitted.

Deprecations, removals, breaking changes, and security-relevant changes are
mandatory when present. Describe the affected interface or behavior and the
upgrade action when evidence supports it. A deprecation should appear in a
release before the corresponding removal whenever the release history permits.

## Write Entries For Readers

Each bullet should describe one notable, observable difference. Name the
affected feature or interface and the effect on users. Include migration or
configuration action when needed.

Synthesize across commits. Exclude merge noise, mechanical refactors,
format-only edits, routine dependency churn, and internal implementation detail
unless they change supported behavior, compatibility, performance, operations,
or security. Do not paste a Git log into the changelog.

Match the existing file's tense and punctuation. Keep each bullet concise, but
retain qualifiers needed to avoid overstating the evidence.

## Write Mode

1. Inspect the evidence range and existing release history.
2. Identify notable changes and classify each one.
3. Draft entries in the existing style and place them in `Unreleased` or the
   specified release.
4. Add or update version and comparison links when their targets are known.
5. Reconcile the draft against the coverage ledger. Every notable change must
   be represented, and every entry must be supported by evidence.
6. If a file was edited, run only the repository-required checks for that file
   and report their results.

## Review Mode

Review both format and release content. Check:

- every released version has a linkable version heading and ISO 8601 date;
- releases are in reverse chronological order and `Unreleased` is first;
- entries use the six canonical categories and empty categories are absent;
- withdrawn versions retain a visible `[YANKED]` marker;
- deprecations, removals, breaking changes, and security changes are explicit;
- entries describe user-facing outcomes instead of copying commit messages;
- every claim is supported by the supplied evidence range;
- every notable change in that range is covered;
- version and comparison links resolve to the intended ranges when they can be
  checked;
- the Semantic Versioning statement agrees with documented project policy.

Report findings in severity order with a precise location, the violated rule,
the user impact, and the smallest correction. Use these verdicts:

- `合格`: no material standard or coverage defect was found.
- `修改后合格`: at least one required correction remains.
- `无法确认完整性`: the release boundary or change evidence is insufficient to
  assess coverage; still report format defects that can be established.

Separate required corrections from optional wording improvements. If no
required correction exists, say so directly. Do not manufacture findings to
fill a report.
