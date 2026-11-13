# Code Archaeology (git + in-repo)

## What this source contains

- Commit history (messages, dates, authors, diffs)
- PR descriptions, review comments, and discussion threads (via available GitHub connector or MCP tools, or `gh` as a fallback)
- Inline code comments, TODOs, FIXMEs, deprecation notes
- Tests, whose names and assertions often encode the edge cases that motivated a change
- Related files modified in the same commits (co-change signal)
- CHANGELOG entries and release notes in the repo
- Issue/ticket IDs in commit messages and PR bodies

Repository evidence ties changes to their implementation context. Explicit commit or review explanations can establish motivation; diffs and tests alone show mechanics, not intent. Pass ADR paths and relevant commits to the long-form document investigator.

## How to search it

Use readable repository files, available history and PR access, or supplied patches and PR exports. Missing git metadata, shallow history, unavailable PR access, and authentication failures are coverage gaps, not evidence that no rationale exists. Expand the seed commit list where local git history is accessible:

```bash
# History through renames
git log --follow --oneline -- <file>

# Pickaxe: commits that added or removed this exact text
git log -S '<exact_string_from_code>' -- <file>

# Or for patterns:
git log -G '<regex>' -- <file>

# Who wrote each line and when
git blame -L <start>,<end> <file>

# One commit's full diff
git show <hash>

# Commits between two points affecting this file
git log <old>..<new> -p -- <file>
```

Look for related implementation evidence:

```bash
# TODOs and FIXMEs near the target
rg -n -C2 '(TODO|FIXME|HACK|XXX|NOTE)' <target_file>

# Related tests
rg -l '<symbol>' --glob '*test*'
```

When investigating defensive code, look for incident-fix messages and revert/reapply sequences around its introduction. Pass linked tasks, postmortems, and exception records to their owning categories.
