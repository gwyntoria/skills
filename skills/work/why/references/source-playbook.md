# Evidence routing

Select evidence by its content and relevance. Access channels are interchangeable where their actual capabilities allow it; these playbooks describe investigation methods rather than vendor APIs.

| Category | Evidence and purpose | Access examples | Playbook |
| --- | --- | --- | --- |
| Source and version history | Code changes, commits, PRs, and review discussion: implementation-time rationale | Local files, git, GitHub tools, `gh`, supplied patches or PR exports | [code-archaeology.md](sources/code-archaeology.md) |
| Issue / task tracking | Requirements, business constraints, problem background, and scope changes | GitHub Issues, Linear or Jira tools, supplied issue exports | [issue-tracking.md](sources/issue-tracking.md) |
| Long-form documents | Repository ADRs, RFCs, and internal or external design documents: reasons, alternatives, and architectural tradeoffs | Local files, repository search, document tools, supplied documents | [design-documents.md](sources/design-documents.md) |
| Error / exception tracking | Exception records, stack traces, affected releases, and resolution notes: background of fixes or defensive logic | Error-tracking tools such as Sentry, supplied event exports or exception logs | [error-tracking.md](sources/error-tracking.md) |

## Access guidance

Use available capabilities, following the target project's documented access conventions. Prefer connector or MCP capabilities where sufficient; use installed and authenticated CLIs when needed. Inspect actual tool schemas before calling them. Keep all queries read-only.

A category may combine local evidence and external records, and one tool may serve multiple categories. Assign documents by content: an ADR belongs to long-form documents even when stored in git. Source-history investigators pass its path and relevant commits to the document investigator.

When a capability is absent or access fails, record the affected source and reason, then continue with other readable evidence in the category. Distinguish an empty search from inaccessible records and from a category not selected. Supplied exports cover only their included content and time range; report that limit rather than implying a live search. The synthesizer uses the same access rules for citation checks.
