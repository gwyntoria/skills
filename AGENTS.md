# Project Agent Rules

This repo mainly contains personal rules and skills used by agents, as well as some common scripts.

## Code Comments

When writing or modifying codes or scripts comments, see `rules/code-comments.md`

## Files Check

- After editing Python files, follow `rules/check-python.md` to fix and format them with Ruff.
- After editing shell scripts, follow `rules/check-shell.md` to format and lint each changed script.

## Testing

Run tests inline or in a temporary directory outside the repository. Keep new test code, fixtures, and test output out of repository files.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repo's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

For domain terminology, start at `GLOSSARY-MAP.md`. See `docs/agents/domain.md` for glossary and ADR conventions.
