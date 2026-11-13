# Databricks Analytics & System Tables

## What this source contains

Databricks is the product-analytics, data-pipeline, and warehouse-telemetry layer. It complements Datadog. Datadog is the *infra/runtime* view, Databricks is the *product/data* view (what users did, which experiments ran, how feature usage evolved, where a threshold constant came from).

- **Product analytics events.** `your_warehouse.events.analytics_track_event` (raw) and typed, deduplicated per-event dbt models in `<your_analytics_db>.<schema>.<table>`. User behavior: feature invocations, clicks, accepts/rejects, submissions, client-reported errors.
- **Usage & billing events.** `your_warehouse.events.usage_event` / `<your_analytics_db>.<schema>.stg_usage_events`, `your_warehouse.events.raw_model_event` / `<your_analytics_db>.<schema>.stg_raw_model_events`. For cost- or volume-driven decisions.
- **Experiment / feature-flag data.** Exposure and outcome tables. **Schema is company-specific.** Probe with `SHOW TABLES` before assuming names.
- **System tables.** `system.query.history`, `system.compute.warehouses`, `system.billing.*`, `system.access.audit`. Answer "was this query expensive?", "how often did anyone run this?", "when did warehouse load spike?"
- **dbt lineage.** Models in `<your_analytics_db>.<schema>` reveal what pipelines depend on a table/field. Upstream changes frequently motivate consumer-code changes.
- **Databricks notebooks.** Exploratory analyses engineers wrote before code changes. A SQL-only backend may not expose them; check the assigned backend's capabilities and report missing access as a gap.

## How to search it

Use the Databricks SQL MCP. Primary tool: `execute_sql_read_only`. If it returns a `statement_id`, poll with `poll_sql_result` rather than re-running.

**Orient before querying.** Schemas are company-specific. Probe before trusting a table name:

```sql
SHOW TABLES IN <your_analytics_db>.<schema> LIKE '*<keyword>*';
DESCRIBE TABLE <your_analytics_db>.<schema>.stg_<event>;
```

**Time-bound every query.** Large tables can time out on unconstrained scans. Verify the timestamp column before filtering; examples include `_timestamp` (events) or `start_time` (`system.query.history`). Use a window bracketing the ship date, typically ~30 days before and after, wider only for strong reason.

**Prefer verified typed dbt models over raw tables.** Confirm their deduplication, types, clustering, and freshness rather than assuming these properties. Names such as `your_warehouse.events.analytics_track_event` and `stg_<source>_<event_name_with_underscores>` are examples, not known tables. Discover actual names with `SHOW TABLES` and inspect their schemas. Use raw events when no suitable model exists or freshness requires them, verifying the deduplication key and property encoding.

**Example column conventions on typed dbt models.** Verify with schema inspection such as `DESCRIBE TABLE` before using any of these:

- `_timestamp`, `_id`, `_auth_id`, `_request_id`, `event_name`. Possible event metadata
- `properties_<name>`. Typed, underscore-cased event properties (`properties_entrypoint`, `properties_size_bytes`, …)
- `context_team_id`, `context_client_version`, `context_country`, `context_client_os`. Pre-extracted client context

### Investigation patterns that tend to pay off

Pick the table + column combination that matches the target:

1. **Event usage trajectory.** Daily counts on the relevant `stg_*` model across a ±30d window around the PR merge. A step function from zero to steady volume within a day or two of the merge is strong circumstantial evidence the PR launched the feature. A decay to zero suggests a deprecation or deletion.
2. **Guard-rail / defensive-check origin.** Distribution (median / p99 / max) of the relevant `properties_<name>` column in the 14 days *before* the PR. A p99 that matches the target's threshold constant suggests the number was chosen from data.
3. **Experiment / feature-flag lookup.** `SHOW TABLES ... LIKE '*experiment*'` to find the exposure table, then pull exposure counts by variant for the relevant flag key near the PR date.
4. **Query-history evidence for migrations, backfills, or perf rewrites.** `system.query.history` filtered by `statement_text ILIKE '%<table_or_symbol>%'` with a tight `start_time` window surfaces the expensive queries that likely motivated the change (sort by `total_duration_ms` or aggregate `SUM(read_bytes)`, `COUNT(*)`).
5. **dbt lineage.** If the target reads from or writes into a `<your_analytics_db>.<schema>` model, the model's own git history (in this repo) often carries the rationale. Hand that lead back to the git investigator rather than chasing it yourself.

## What good evidence looks like here

Beyond the pattern shapes above:

- An error-classifying event's count drops to near zero in the days after a defensive-code PR. Suggests the PR resolved that error class
- An exposure table row names the target's feature-flag key with a "shipped" / "concluded" decision around the PR ship date

## Common pitfalls

- **Instrumented ≠ caused.** An event's existence means someone cared enough to log it, not that the target code exists *because* of it. Pair with a PR/commit citation from the git investigator before claiming causation.
- **Silent instrumentation changes.** A step function in event volume may mean a new event started being logged, not that user behavior changed. Check for instrumentation PRs in the same window before reading the ramp as a feature-launch signal.
- **Schema drift.** Event properties evolve. A column on the typed dbt model today may not have existed when the target was written. Older data may carry the property only inside raw `properties_json`.
- **dbt refresh lag.** Check the actual model refresh schedule. For events newer than the last refresh, query verified raw-event tables and deduplicate using the confirmed event key.
- **Company-specific tables.** Experiment, feature-flag, billing, and usage tables vary. Reporting a result from a table whose existence you never confirmed is a classic failure mode. Probe with `SHOW TABLES` / `DESCRIBE TABLE` first.
- **Retention cliff.** If the relevant window predates the table's retention or the dbt model's creation date, that's a *gap*, not a null result. Name it explicitly so the synthesizer doesn't read "no results" as "no activity."
- **Notebook access varies.** If the assigned backend cannot retrieve a relevant notebook, return that access gap rather than assuming its contents.

## What to return

For each relevant finding:

- Type (product event / experiment exposure / usage or billing event / system-table row / dbt model)
- Fully-qualified table name and the exact query you ran
- Time window queried
- Compact numeric summary (counts, percentiles, first/last-seen timestamps). **Don't dump raw rows.**
- Temporal correlation with the target's ship date (e.g., "first row 2024-08-15, PR #49074 merged 2024-08-14")
- Relevance + strength: direct / circumstantial / weak
