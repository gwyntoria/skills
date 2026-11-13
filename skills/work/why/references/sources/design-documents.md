# Long-form Design Documents

## Evidence to seek

Repository ADRs, RFCs, specifications, PRDs, design-review notes, and postmortems that explain motivations, alternatives, constraints, or architectural tradeoffs. Local documents and supplied materials are usable without external document tools.

## Investigation

1. Follow the repository's guide index to its design documents and ADRs. Search local documents by feature name, symbols, business terms, and error strings; do not assume a fixed document directory.
2. Read linked or supplied documents fully. Use available external document search when relevant, including keyword searches for unlinked designs.
3. Follow appendices, related decisions, and superseding documents. Record status, authorship, and dates; a newer draft does not automatically replace an accepted decision.
4. Extract the problem, constraints, alternatives considered, chosen approach, and consequences. Compare the document's decision date with the code change.
5. For defensive logic, inspect postmortems and runbooks for a stated connection to the fix. Pass linked tasks, PRs, or exception events to their owning categories.

## Interpretation limits

- A proposal records intended work, not necessarily the final decision. Flag differences between documents and shipped code.
- A design's absence from search results does not establish that no design existed. Note inaccessible pages, partial exports, and unsearched locations.
- Boilerplate motivation sections are weaker than concrete constraints and recorded tradeoffs.

## Return

Title, local path or URL, section or line location, relevant quoted text, authors and dates when available, draft/accepted/superseded status, related decisions, queries performed, and access or version limits.
