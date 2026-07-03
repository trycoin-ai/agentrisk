# Tool reference

All three tools are available as Python functions (`from agentrisk import ...`) and
as MCP tools of the same name. Inputs may be dicts or the corresponding pydantic
models. Outputs are pydantic models; call `.model_dump(mode="json")` for plain JSON.

---

## `check_trade_risk(portfolio, trade, *, policy=None, policy_path=None, home=None, now=None, audit=True, override=None, override_reason=None)`

Validate a proposed trade before execution.

**Returns** a `Verdict`:

| Field | Meaning |
| --- | --- |
| `verdict` | `"PASS"` / `"WARN"` / `"BLOCK"` / `"OVERRIDDEN"` |
| `proceed` | Boolean the integrator gates on. `false` only for BLOCK. |
| `summary` | One-line message suitable for an order confirmation. |
| `checks[]` | Per-rule results: `id`, `status`, `message`, `details`. |
| `acknowledgements_required[]` | Warning messages to surface before proceeding. |
| `overrides[]` | Block tokens bypassed for this trade (empty unless `override` was used). |
| `override_rejected[]` | Requested tokens that cannot be bypassed. |
| `evaluated` | Price used, order value, snapshot `as_of`, and policy `{path, revision, sha256}`. |
| `data_quality` | `unclassified_pct`, `snapshot_age_hours`, `warnings`. |
| `engine` | `agentrisk_version`, `classification_data_version`. |

**Fail-closed behavior:** invalid input results in BLOCK (`invalid_snapshot` / `invalid_trade`);
a missing policy results in BLOCK (`no_policy`).

```python
from agentrisk import check_trade_risk

v = check_trade_risk(portfolio, {"action": "buy", "symbol": "NVDA", "quantity": 20,
                                 "order_type": "market", "estimated_price": 120},
                     policy_path=".agentrisk/policy.yaml")
if not v.proceed:
    print(v.summary)          # do not execute
```

### One-time bypass (`override`)

`override` is a list of block tokens the user has explicitly approved bypassing
for this single call. It never edits the policy. Each blocking entry in `checks[]`
exposes in its `details` how it may be bypassed:

| `details` field | Meaning |
| --- | --- |
| `overridable` | Whether this block can be bypassed at all. |
| `override_tier` | `"soft"` (tunable limit), `"hard"` (explicit prohibition), or `"none"` (feasibility block). |
| `override_token` | The exact string to pass in `override`. |
| `override_guidance` | Present as `"prefer_policy_edit"` on hard blocks. |

- **soft** (order size, concentration, min-cash, staleness): bypass directly with user approval.
- **hard** (block crypto/options/margin, never-trade): offer a policy edit first; only bypass if the user declines the edit and approves the exception. Always pass an `override_reason`.
- **none** (insufficient cash/holdings, invalid snapshot, no policy): listed in `override_rejected`; the trade stays BLOCK.

A bypass that clears all blocks returns `verdict="OVERRIDDEN"`, `proceed=true`, the
bypassed tokens in `overrides[]`, and writes a distinct `trade_override` audit record.

```python
# First call blocks; the user approves a one-time bypass of the order-size cap.
v = check_trade_risk(portfolio, trade, policy_path=".agentrisk/policy.yaml",
                     override=["max_order_size"], override_reason="user approved once")
```

---

## `analyze_portfolio_risk(portfolio, *, analyses=None, focus=None, policy=None, policy_path=None, home=None, now=None)`

Read-only portfolio risk report. Writes nothing.

- `analyses`: subset of `["concentration", "compliance"]` (default: both).
- `focus`: one of `{"tag": ...}`, `{"sector": ...}`, `{"asset_class": ...}`, `{"symbol": ...}`.

**Returns** a `RiskReport`: `totals`, `positions_by_weight`, `breakdowns`
(`by_sector` / `by_asset_class` / `by_tag`), `concentration` (`hhi` + `band`),
`top_risks`, `compliance` (if a policy is found), `focus` (if requested),
`data_quality`, and `limitations`.

---

## `generate_risk_policy(mode="create", *, preset=None, fields=None, changes=None, confirm=False, policy_path=None, home=None, now=None)`

Create, update, or show the policy.

- `mode="create"`: `preset` + `fields` produce a proposal; writes only when `confirm=True`;
  never overwrites an existing file.
- `mode="update"`: `changes` (partial) produces a proposal with a `diff[]` classifying each
  change as `tightening` / `loosening` / `neutral`; writes + archives the prior
  revision only when `confirm=True`.
- `mode="show"`: current policy + plain-English `summary[]`.

**Returns** a `PolicyResult`: `mode`, `written`, `requires_confirmation`, `message`,
`policy` (dict), `yaml` (string), `summary[]`, and `diff[]` (updates only).

```python
# Propose, inspect the diff, then confirm.
r = generate_risk_policy("update", changes={"limits": {"max_single_position_pct": 20}})
assert r.requires_confirmation
generate_risk_policy("update", changes={"limits": {"max_single_position_pct": 20}}, confirm=True)
```
