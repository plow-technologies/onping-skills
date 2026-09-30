---
name: onping-line-graph-create
description: Mint a fresh empty OnPing line-graph widget via POST /content/widgets/line-graph/config. Returns a new `o…` LineGraphWidgetId. MUTATING, requires --yes. The resulting widget is orphaned (not attached to a dashboard). Use with onping-line-graph-import to populate; there is no delete route for cleanup.
allowed-tools: Bash(uv run *)
---

# OnPing Line Graph Widget — Create

> **⚠️ WARNING: this skill changes live data, and some changes cannot be undone.**
> It creates a new, empty line-graph widget on OnPing. This cannot be undone: OnPing has no line-graph delete route, so the widget stays even if you never use it. It previews by default and changes nothing until you pass `--yes`; `--dry-run` also previews and wins over `--yes`.

Mint a fresh, empty line-graph widget and print its new `LineGraphWidgetId`.
This is the mint half of the `-import --new` two-step (there is no client-side
id generation because widget ids are server-assigned Mongo `o…` ids).

> **MUTATING — requires `--yes`.** By default, and with `--dry-run`, the skill
> prints a preview of the server defaults and does NOT call `POST /config`.
> `--dry-run` wins if both are passed.

> **The new widget is orphaned.** It exists but is not attached to a dashboard,
> so it doesn't appear in any HMI panel until wired in. Use with
> `onping-line-graph-import` (which supports `--new` to combine mint + populate
> atomically), or attach via the HMI panel config.

> **NO DELETE ROUTE.** OnPing has no `DELETE /content/widgets/line-graph/*`
> endpoint — see [_line_graph_routes/SKILL.md](../_line_graph_routes/SKILL.md).
> A wrongly-minted widget can only be cleaned up by deleting the parent
> dashboard once it's attached, or by leaving it orphaned. **Only mint when
> you're going to use the id.**

## Server defaults for a freshly minted widget

`onping/Handler/Highcharts/LineGraphWidget.hs`:

| Field | Value |
|---|---|
| title | `"New Chart"` |
| timePeriod | `3` |
| timeUnit | `"hour"` |
| updateInterval | `60` |
| yAxes | one linear axis, no parameters |
| eventParameters | `[]` |
| maxStep | `0` |
| normalizeValue | `False` |
| latestValueLine | `Just False` |
| legendWithCurrentValue | `False` |

## Related Skills

- **onping-login** — Authenticate and get an access token
- **onping-line-graph-import** — Populate the fresh widget (supports `--new` for atomic mint + populate)
- **onping-line-graph-get** — Read the widget after minting (to confirm defaults)

## Usage

```bash
ACCESS_TOKEN=$(uv run ~/.claude/skills/onping-login/scripts/login.py)
# Preview server defaults, no network write
uv run ~/.claude/skills/onping-line-graph-create/scripts/create_line_graph.py "$ACCESS_TOKEN"
# Mint (prints the new widget id on success)
uv run ~/.claude/skills/onping-line-graph-create/scripts/create_line_graph.py "$ACCESS_TOKEN" --yes
```

Typical mint + populate flow (prefer `onping-line-graph-import --new` for atomicity):

```bash
NEW_ID=$(uv run …/create_line_graph.py "$ACCESS_TOKEN" --yes)
uv run …/onping-line-graph-import/scripts/import_line_graph.py "$ACCESS_TOKEN" --id "$NEW_ID" --input chart.dhall --yes
```

## Flags

- `--yes` — perform the mint. **Required** for any write.
- `--dry-run` — explicit preview (default). Wins over `--yes` if both are passed.

## Output

- **Preview:** the default-values table; no network call; exit 0.
- **Apply:** the new `LineGraphWidgetId` (a Mongo `o…` id) as JSON to stdout; exit 0 on success.

## API Reference

| Endpoint | Method | Request | Response |
|----------|--------|---------|----------|
| `/content/widgets/line-graph/config` | POST | empty body | JSON-quoted `LineGraphWidgetId` string |

Handler: `onping/Handler/Highcharts/LineGraphWidget.hs` (defaults at `:47`).

## Authentication

Accepts **Bearer token auth** from `onping-login`. Any authenticated user can mint.

## Error Handling

- **Token expired** — a `303 → /auth/login` redirect or an HTML login body fails fast (non-zero exit); no widget is minted.
- **Server error** — a non-2xx surfaces the `{"error": "..."}` message (if any) verbatim.
