# Project Agent Rules

## Folder Structure

Skill source documents are organized into bucket folders under `skills/` and are used by the `npx skills` and Claude marketplace installation paths.

Agent rules are under `./rules`.

## Agent skills

### Issue tracker

Issues and PRDs are tracked in this repo's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical labels. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses the single-context layout. See `docs/agents/domain.md`.

<!-- gwyn-space-skills: code-comments:start -->
<!-- Installed from rules/code-comments.md by setup-agents.sh. Edits inside this block are overwritten on reinstall. -->
## Code Comment Guidelines

**Core principle:** Would removing this comment cause a maintainer to lose important information? Keep comments that preserve such information; omit those that merely repeat the code.

- Explain implementation decisions, business rules, and historical compatibility reasons that the code alone cannot reveal.
- State concurrency, timing, and performance constraints that maintainers must preserve.
- Document public API behavior, errors or exceptions, and boundary conditions that callers depend on. Keep each contract in one authoritative location unless the project requires duplication.
- Explain complex algorithms and cite relevant papers or references when they help readers understand or verify the implementation.
- Use clear names and structure to make operations self-explanatory. Prefer improving them within the authorized scope over compensating with comments; omit repeated names and line-by-line narration.
- Make TODO and FIXME comments identify the unresolved problem, preferably linking to an issue. Usually remove commented-out old code; version control preserves its history.
- Follow the project's comment format and language. Otherwise use the programming language's standard documentation format and the user's requested language, defaulting to English.
- Verify factual claims and design reasons against available evidence. Update affected comments when behavior changes, and keep edits within the task's scope.
<!-- gwyn-space-skills: code-comments:end -->
