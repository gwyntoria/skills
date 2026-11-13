# Error / Exception Tracking

## Evidence to seek

Exception records, representative stack traces, affected releases, first/last-seen times, and resolution notes that may explain corrective or defensive code. Use available error-tracking tools or supplied event exports and exception logs; a particular service or MCP is not required.

## Investigation

1. Establish the relevant project, environment, and release from accessible records.
2. Search by exception class, message, function, file path, or an event ID linked from a PR or task.
3. Narrow to a time window around the code's introduction or release. Compare first/last-seen times, affected versions, and event frequency where recorded.
4. Inspect representative events. Check whether the stack, tags, and breadcrumbs match the target and the conditions it handles.
5. Read author comments and resolution notes for an explicit link to the fix. Pass linked PRs, tasks, and postmortems to their owning categories.

## Interpretation limits

- An error disappearing after a release supports a connection but does not by itself establish why the code was written. Seek an explicit task, commit, or resolution statement.
- Sampling, retention, release tagging, and partial exports can distort the timeline. Report their known limits.
- Automated root-cause summaries supply hypotheses; underlying events and human decision records supply evidence.

## Return

Event or issue ID, path or URL, project and environment, first/last-seen timestamps, affected releases, counts and sampling information when available, a relevant stack excerpt, resolution text, exact queries or supplied materials examined, and coverage limits.
