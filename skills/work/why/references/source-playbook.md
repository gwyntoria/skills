# Source playbooks

The why skill spawns one investigator per available evidence category, each reading a single source-specific playbook below. The playbooks are concrete examples for common MCPs. Adapt them for a different connector or MCP in the same category.

## Adapt tools to the session

Inspect the assigned backend's actual tool schemas before calling it. Tool names, parameters, authentication mechanisms, and SQL capabilities below are examples, not guaranteed APIs. Use the exposed equivalent without changing the investigation's purpose. Prefer available connector or MCP capabilities; use `gh` for missing GitHub capabilities only when installed and authenticated. Keep all queries read-only.

Verify environment-specific table names, columns, and data conventions before relying on them. If a capability is absent or access fails, record what could not be searched and why; do not label it an empty result or invent an equivalent tool. Continue other accessible searches in the assigned category. The synthesizer must also use actual available tools when spot-checking citations.

## Category playbooks

| Category | Playbook | Example MCP it documents |
| --- | --- | --- |
| Source control history | [`code-archaeology.md`](./sources/code-archaeology.md) | git, `gh` |
| Issue / ticket tracker | [`linear.md`](./sources/linear.md) | Linear (adapt for Jira, GitHub Issues, Plane, Shortcut) |
| Long-form documents | [`notion.md`](./sources/notion.md) | Notion (adapt for Confluence, Google Docs, Coda) |
| Real-time team chat | [`slack.md`](./sources/slack.md) | Slack (adapt for Discord, Microsoft Teams, Mattermost) |
| Infrastructure observability | [`datadog.md`](./sources/datadog.md) | Datadog (adapt for New Relic, Honeycomb, Grafana, Splunk) |
| Error / exception tracking | [`sentry.md`](./sources/sentry.md) | Sentry (adapt for Rollbar, Bugsnag, Airbrake) |
| Product analytics warehouse | [`databricks.md`](./sources/databricks.md) | Databricks SQL (adapt for Snowflake, BigQuery, ClickHouse, dbt) |

Cross-cutting:

- [`incident-postmortem.md`](./sources/incident-postmortem.md). Add this if the target code looks defensive (null checks, retry, timeout, rate limit, feature flag, egress guard, OOM handler).
