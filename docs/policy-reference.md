# Policy reference

A policy is human-readable YAML validated against a strict schema. Unknown fields
are **errors**, not ignored, so a misspelled rule will never silently vanish. All
percentages are on a 0-100 scale. Absence of a limit means that limit is not
enforced.

Default location: `./.agentrisk/policy.yaml` (override with the `AGENTRISK_HOME`
environment variable or a per-call `policy_path`).

## Full example

```yaml
schema_version: 1
revision: 3
preset: balanced
created_at: "2026-07-01"
updated_at: "2026-07-01"
notes: "User accepts high growth; caps single-name concentration."

limits:
  max_single_position_pct: 20      # any one symbol's % of portfolio value
  max_sector_pct:
    technology: 50
  max_tag_pct:
    ai: 40
  max_asset_class_pct:
    crypto: 10
  warn_at_utilization: 80          # % of a limit at which WARN fires

asset_rules:                       # allow | warn | block (applies to INCREASING exposure)
  crypto: block
  options: warn
  margin: block

order_rules:
  max_order_pct_of_portfolio: 10   # single-order size cap, % of portfolio value
  max_order_value: 25000           # optional absolute cap, base currency
  min_cash_pct: 5                  # post-trade cash floor (buys)

restricted:
  never_trade: ["GME"]             # BLOCK list (both buy and sell)
  warn_list: []                    # WARN list

data_rules:
  max_snapshot_age_hours: 24
```

## Field reference

| Field | Type | Effect |
| --- | --- | --- |
| `limits.max_single_position_pct` | 0-100 | BLOCK a buy that pushes the traded symbol above the cap; WARN as it nears `warn_at_utilization`. |
| `limits.max_sector_pct.<sector>` | map | Per-sector cap (sectors from the AgentRisk taxonomy). |
| `limits.max_tag_pct.<tag>` | map | Per-theme cap (tags from caller/seed data, e.g. `ai`). |
| `limits.max_asset_class_pct.<class>` | map | Per-asset-class cap: `equity`, `etf`, `crypto`, `option`, `cash`. |
| `limits.warn_at_utilization` | 0-100 | Utilization at which an approaching limit WARNs (default 80). |
| `asset_rules.crypto` / `.options` / `.margin` | `allow`/`warn`/`block` | Applied to trades that **increase** that exposure. Reducing/closing always passes. |
| `order_rules.max_order_pct_of_portfolio` | 0-100 | BLOCK oversized single orders (fat-finger / runaway-agent protection). |
| `order_rules.max_order_value` | >= 0 | Optional absolute single-order cap. |
| `order_rules.min_cash_pct` | 0-100 | BLOCK a buy that would leave cash below this floor. |
| `restricted.never_trade` | list | BLOCK any trade in these symbols. |
| `restricted.warn_list` | list | WARN on any trade in these symbols. |
| `data_rules.max_snapshot_age_hours` | >= 0 | WARN when the snapshot is older than this. |

## Presets

`generate_risk_policy(mode="create", preset=...)` seeds defaults you then override:

| Preset | Single-name | crypto / options / margin | order cap / min cash |
| --- | --- | --- | --- |
| `conservative` | 10% | block / block / block | 5% / 10% |
| `balanced` (default) | 20% | warn / warn / block | 10% / 5% |
| `aggressive` | 35% | allow / allow / warn | 20% / 0% |

Presets are starting points, never silent recommendations; the generated file
records which preset seeded it.

## Semantics worth knowing

- **Pre-existing breaches:** if the portfolio already exceeds a cap, a trade that
  *worsens* the breach is BLOCKed, a trade that *reduces* it PASSes (with a note),
  and an unrelated trade is judged on its own merits (the standing breach is
  reported as a warning).
- **Exits are never trapped:** selling / closing is never BLOCKed by a
  concentration or asset-class rule (a blocked asset class still allows sells).
- **Unverifiable exposure:** if you trade an unclassified instrument while
  sector/tag/asset-class caps exist, the trade WARNs; it cannot silently pass on
  unknown data.

## Deferred (not in v1)

Behavioral limits (trades/day, turnover), loss/drawdown rules, options analytics
(delta/notional), and time-window rules are planned for later releases.
