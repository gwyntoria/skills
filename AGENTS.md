# Project Agent Instructions

## Markdown File Format

After finishing edits to a Markdown file, format only the files that was changed with `markdownlint-cli2`, then run `textlint` to apply typography fixes and terminology replacements.

```bash
npx markdownlint-cli2 --fix --no-globs path/to/file.md
npx textlint --fix path/to/file.md
```

Avoid running broad auto-fix commands unless the task is specifically to clean up formatting across the repository.

## Folder Structure

Skill source documents are organized into bucket folders under `skills/` and are used by the `npx skills` and Claude marketplace installation paths.

Agent instructions are under `./instructions`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repo's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses the single-context layout. See `docs/agents/domain.md`.
