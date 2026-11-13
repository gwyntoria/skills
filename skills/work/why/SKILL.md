---
name: why
description: "Use for 'why does X work this way', 'why we picked Y', design rationale, regressions, postmortems, or data-backed thresholds. Discovers available MCPs and queries each evidence category (source control, issue tracker, long-form docs, real-time chat, infrastructure observability, error tracking, product analytics warehouse) in parallel, then returns a cited read on decisions and tradeoffs. Use how for runtime behavior."
---

# Why

Investigate the motivation and intent behind code. The companion `how` skill answers what the code does and how it works. `why` answers what forces led to its shape.

## Codex execution

Resolve reference paths relative to this skill directory, not the target repository.

Use the subagent tools exposed by the current Codex session to spawn investigators and the synthesizer, wait for their results, and release finished agents. Leave model, reasoning, and speed overrides unset so each role inherits the current session configuration. Pass each role its complete assignment and repository location. Verify that its assigned tools are available to the child; discover deferred tools there if needed. Report access gaps rather than assuming parent tool access carries over.

All roles may read the repository and query evidence sources but must not edit files, commit, or modify external state. Keep tool access needed for investigation; enforce read-only behavior through the assignment rather than platform-specific mode parameters.

Run independent investigators in parallel within the session's concurrency limit. If necessary, use batches and release finished agents before starting more. Collect every investigator's findings or access failure before spawning the synthesizer. If subagent tools are unavailable, report that the required workflow is blocked; do not treat this as grounds for an inline answer.

## Operating Posture

Operate as a **careful, cautious, and precise investigator**. Be honest about what you know vs what you're inferring. Read `references/epistemics.md` for the full confidence framework and phrasing guide. The synthesizer must follow it.

## Step 1. Understand the Target and the Question

The **target** is usually a chunk of code, a pattern, a feature, or a named design decision. The **question** is usually a design rationale, a tradeoff, a motivating edge case, an external constraint, dead code, or a broad history sweep.

If the target is vague ("why do we do it this way?" with no clear referent), make your best guess from conversation context (user-provided files or selections, recent edits, what was just discussed). State your interpretation briefly so the user can redirect if you're off, then proceed.

## Step 2. Establish the Code Anchor

Before spawning investigators, build the seed context inline: file paths and line ranges, key symbols (functions, classes, constants), the last few commits touching the target, PR numbers from merge commits (pattern `(#1234)` in the subject line), and any linked ticket IDs. Where local git history is available, run `git blame -L <start>,<end> <file>` for last-touch commits, `git log --follow -p -- <file>` for full history with patches through renames, `git log --oneline -20 -- <file>` for recent commits with PR numbers visible, and `git log -1 --format=%B <commit>` to extract PR numbers.

Pull the PR bodies, reviews, and discussion for substantive commits using available GitHub connector or MCP tools first. If those lack the required capability, use `gh` when installed and authenticated, for example `gh pr view <number> --json title,body,author,createdAt,mergedAt,labels,closingIssuesReferences,comments,reviews`. Record missing history, tools, permissions, or authentication as gaps; continue with accessible evidence. This anchor, including its gaps, goes to every investigator and to the synthesizer.

## Step 3. Spawn Parallel Investigators

**Default to the full parallel investigation.** The goal is a complete coverage map, not a minimal one. Document the null, don't skip the search.

### Discovery

Before spawning investigators, discover the evidence tools available in the current Codex session. Inspect the exposed tool catalog and use the session's tool-discovery mechanism for deferred connectors or MCPs. Use MCP resource listing only for servers that expose resources; an empty resource list does not establish that no callable tools exist. Base availability on discovered capabilities and actual access, not on a presumed configuration directory.

Map each available connector or MCP to one evidence category:

1. Source control history
2. Issue / ticket tracker
3. Long-form documents
4. Real-time team chat
5. Infrastructure observability
6. Error / exception tracking
7. Product analytics warehouse

Check local git history and available GitHub tools for source control; neither git nor `gh` is guaranteed. For the other six categories, classify using connector or MCP names, server descriptions, tool schemas, and resource descriptors. If a source could fit more than one category, choose the one matching its primary evidence. Record ambiguous cases in the coverage map. A GitHub integration may serve both PR history and Issues through separate category assignments.

Spawn one investigator per available evidence category, concurrently within the session limit. Each owns one selected connector or MCP backend; the source-control investigator may combine local git with GitHub access for PR evidence. Do not ask one investigator to cover multiple categories or unrelated backends.

Each investigator's prompt is `references/investigator-prompt.md` filled in, plus:

- the tool-adaptation guidance in `references/source-playbook.md` and the category playbook selected from its table. Use that exact filename (for example, source control uses `sources/code-archaeology.md`); do not derive a filename from the category or tool name
- the assigned backend and available tool-discovery details, including known access limits
- `references/sources/incident-postmortem.md` **if the target code looks defensive** (null checks, retry logic, timeout handling, rate limiting, feature flags, egress guards, OOM handlers)
- the code anchor and the user's original question

### Investigator roster, one per available evidence category

Each category below is uniquely positioned to surface one shape of "why", shown after "Best at". Use it to know what to expect back, to name a gap when a category returns empty, and, only in the rare provably-irrelevant case, to justify a skip.

1. **Source control** (git history, available GitHub tools for PRs, code comments, tests). Always spawn when repository evidence is accessible; report any unavailable history or remote access. Best at *implementation-time rationale captured during review*.
2. **Issue / ticket tracker** (e.g. Linear, Jira, GitHub Issues, Plane, Shortcut MCP). Best at *the product or business forcing function*. Strongest when the why is external to engineering.
3. **Long-form documents** (e.g. Notion, Confluence, Google Docs, Coda MCP). Best at *long-form design rationale*, written out before it becomes code.
4. **Real-time team chat** (e.g. Slack, Discord, Microsoft Teams, Mattermost MCP). Best at *real-time deliberation that never reached a doc*. Especially important when the source control, ticket, and doc paper trail is thin.
5. **Infrastructure observability** (e.g. Datadog, New Relic, Honeycomb, Grafana, Splunk MCP). Best at *infrastructure and runtime reality that motivated the code*. Strongest when the target reacts to an infra signal (timeouts, retries, rate limits, circuit breakers).
6. **Error / exception tracking** (e.g. Sentry, Rollbar, Bugsnag, Airbrake MCP). Best at *the specific exceptions and error trajectories that motivated defensive or corrective code*. Strongest for catch blocks, null guards, type checks, retries, and other defenses.
7. **Product analytics warehouse** (e.g. Databricks, Snowflake, BigQuery, ClickHouse, dbt, Redshift MCP). Best at *product and data reality that shaped the code*. Strongest for flag-gated code, experiment-driven ships, data migrations, and "where did this number come from" questions.

### When to skip an investigator

Only with an **explicit, written justification** that goes in the final Sources Consulted. Two valid reasons:

- **No usable evidence access is available for that category** in this environment, including missing tools, history, permissions, or authentication. Flag it as a gap, not an empty search: "Real-time team chat skipped. No matching connector or MCP available, so the conversational record was not searchable." If access fails after dispatch, retain the investigator's failure report in the coverage map and continue the other investigations.
- **The source is provably irrelevant**, not just "probably irrelevant." A high bar: "Error / exception tracking skipped. Target is a build-time script with no runtime code path."

If your scope assessment suggests a single-commit trivial target where the PR description already contains the complete answer, you may answer inline **only after** confirming all seven available category searches would be redundant. Say so explicitly. This should be rare.

## Step 4. Synthesize

After all investigators have returned, spawn one synthesizer. It gets:

1. The investigator findings, including any null results and any categories skipped with justification
2. The code anchor
3. The user's original question
4. The epistemics framework from `references/epistemics.md`
5. The synthesizer prompt template from `references/synthesizer-prompt.md`

## Step 5. Present

Present the synthesizer's output to the user. You may lightly edit for clarity or add context from the conversation, but **do not rewrite the confidence language**.

## Output Format

The structure is the one in `references/synthesizer-prompt.md`: The Question, The Code in Question, What We Found, What We Can Reasonably Infer, Competing Hypotheses, What We Don't Know, Sources Consulted, Confidence Summary. Adapt as needed, but keep the confidence separation intact, and keep Sources Consulted as one line per investigator, including the ones that returned nothing or were skipped, with the reason.

After Sources Consulted, if the user's `why` question is a precursor to changing this code, convert the lineage findings into a Preserve / Change / Avoid / Risk constraint set for planning the change.

## Common Failure Modes to Avoid

- **Recency bias**. Assuming the most recent commit is authoritative. The current shape is often the accretion of many earlier decisions. Trace back.
