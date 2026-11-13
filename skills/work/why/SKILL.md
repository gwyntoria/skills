---
name: why
description: "Investigate code design rationale, historical decisions, tradeoffs, and the background of fixes. Uses source history, issues, design documents, and relevant error records to return cited findings with calibrated confidence. Use how for runtime behavior."
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

### Select evidence categories

Use the four-category routing table in [references/source-playbook.md](references/source-playbook.md). Select categories by the question and readable evidence, then discover only the tools needed to access them. Local files, installed and authenticated CLIs, connectors or MCPs, and user-provided materials can supply evidence. A missing MCP does not make local evidence unavailable.

Check source history and repository design documents by default when the repository is accessible. Search issue records when an access channel or supplied material is available. Include error tracking when the question involves exceptions, fixes, defensive logic, or an explicit error reference. Expand searches within these four categories when evidence is insufficient or contradictory.

Spawn one investigator per selected category with accessible evidence, concurrently within the session limit. Each investigator may use multiple access channels within its category. A single connector may serve multiple categories: GitHub PRs belong to source history, Issues to task tracking, and repository ADRs to long-form documents. Route cross-category leads to their owning investigator or a follow-up pass.

Each investigator receives:

- `references/investigator-prompt.md`, filled in with its assignment
- the access guidance and exact category playbook linked from `references/source-playbook.md`
- assigned evidence locations and available tools, including known access limits
- the code anchor and the user's original question

### Coverage and stopping

Record categories searched, searches with no results, access failures, and categories not selected with a brief reason. If access fails, retain the failure report and continue accessible investigations. Reading a playbook is preparation, not a search of that evidence source.

When searches have covered the selected scope and relevant cross-category leads have been followed or recorded as inaccessible, collect the findings for synthesis. Unsupported motivation remains unknown; accessible evidence need not exist in all four categories.

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

The structure is the one in `references/synthesizer-prompt.md`: The Question, The Code in Question, What We Found, What We Can Reasonably Infer, Competing Hypotheses, What We Don't Know, Sources Consulted, Confidence Summary. Adapt as needed, but keep the confidence separation intact, and keep Sources Consulted as one line per searched category, including empty results. Name unsearched categories and access gaps that materially limit the answer, with the reason.

After Sources Consulted, if the user's `why` question is a precursor to changing this code, convert the lineage findings into a Preserve / Change / Avoid / Risk constraint set for planning the change.

## Common Failure Modes to Avoid

- **Recency bias**. Assuming the most recent commit is authoritative. The current shape is often the accretion of many earlier decisions. Trace back.
