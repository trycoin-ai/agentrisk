# Integration guide

## The enforcement contract (read this first)

**AgentRisk verdicts are advisory data. AgentRisk cannot physically prevent an
order.** It is only a guardrail if your execution path is gated on the verdict.
The entire value of the tool depends on this one integration point:

```python
from agentrisk import check_trade_risk

result = check_trade_risk(portfolio, trade, policy_path=".agentrisk/policy.yaml")

if not result.proceed:
    refuse(result.summary)              # BLOCK: never call the broker
elif result.acknowledgements_required:
    if user_confirms(result):           # WARN: surface warnings, get an OK
        execute(trade)
        show_user(order_confirmation + " " + result.summary)
else:
    execute(trade)                      # PASS
    show_user(order_confirmation + " " + result.summary)
```

If you call the broker regardless of the verdict, you do not have a guardrail;
you have a logger. See [`../examples/agent_loop.py`](../examples/agent_loop.py)
for a runnable version.

## Handling each verdict

| Verdict | `proceed` | What the integrator should do |
| --- | --- | --- |
| PASS | `true` | Execute. Optionally append `summary` to the order confirmation. |
| WARN | `true` | Surface every item in `acknowledgements_required`; execute only after the user acknowledges. |
| BLOCK | `false` | Do not execute. Relay `summary` (and, if useful, the blocking `checks[]`). |
| OVERRIDDEN | `true` | A BLOCK the user explicitly bypassed once (see below). Execute, and tell the user a guardrail was bypassed for this trade. |

`acknowledgements_required` is intentionally an explicit list rather than a buried
flag: the intended UX is that the user sees the warnings before the order goes out.

## One-time bypass

Sometimes a user genuinely wants a single blocked trade to go through without
loosening their policy for everything after it. That is what `override` is for, and
it is deliberately safer than raising the limit, because the policy is left intact.

The rules the reference integration follows:

- Never pass `override` on your own initiative, and never with no human present. It
  requires explicit, in-the-moment approval of that specific trade.
- Read `override_tier` on the blocking check before offering anything:
  - `soft` (order size, concentration, min-cash, staleness): offer the bypass directly.
  - `hard` (block crypto/options/margin, never-trade): offer to edit the policy first;
    only bypass if the user declines the edit and insists, and always record an
    `override_reason`.
  - `none` (insufficient cash/holdings, invalid snapshot, no policy): cannot be
    bypassed; fix the underlying problem.
- After a successful bypass (`verdict="OVERRIDDEN"`), the order may proceed, but the
  confirmation you show the user must state that a guardrail was bypassed. Every
  bypass is also written to the audit log as a `trade_override` record.

## Providing state

- **Portfolio:** pass a fresh snapshot with an accurate `as_of`. Stale snapshots
  WARN; internally inconsistent ones BLOCK. AgentRisk fetches no prices, so the
  numbers you pass are the numbers it reasons about.
- **Policy:** either let AgentRisk resolve the file (default `./.agentrisk/policy.yaml`,
  or `AGENTRISK_HOME`, or a per-call `policy_path`), or pass a `policy` object
  inline for a fully stateless deployment.

## Pairing AgentRisk with a broker MCP server

If your agent already talks to a broker through an MCP server (Robinhood, Alpaca,
or similar), AgentRisk slots in as a second server in the same client. The broker
server supplies positions and places orders; AgentRisk validates in between.

Register both servers in your MCP client config:

```json
{
  "mcpServers": {
    "robinhood": { "command": "your-robinhood-mcp" },
    "agentrisk": { "command": "agentrisk-mcp" }
  }
}
```

Then tell the agent how the two fit together. For a Claude agent, install the
AgentRisk Agent Skill (see the README's "Agent Skill" section, or the plugin, which
registers this server for you) and it will follow this protocol on its own. For any
other agent, put the equivalent in the client's system prompt or project instructions:

```text
Before placing ANY order with the broker tools, you must:
1. Fetch current positions and cash from the broker, plus current prices.
2. Build an AgentRisk portfolio snapshot from them:
   {"as_of": <now>, "cash": <cash>, "positions":
     [{"symbol": ..., "quantity": ..., "price": ...}, ...]}
3. Call agentrisk's check_trade_risk with that snapshot and the proposed trade.
4. If proceed is false, do not place the order. Tell the user the summary.
5. If acknowledgements_required is non-empty, show those warnings and wait for
   the user's explicit OK before placing the order.
6. Append the AgentRisk summary to the order confirmation you show the user.
```

Two caveats to keep in mind:

- This wiring relies on the agent following instructions. A prompt-level gate is
  much better than nothing, but the strongest setup is code that sits between the
  agent and the broker and refuses to forward orders when `proceed` is false
  (see the wrapper at the top of this guide).
- Test with a paper-trading account first, and start with a `conservative` preset
  so blocks are easy to trigger and observe.

## Where AgentRisk cannot help (yet)

- **Runaway behavior across many trades.** Each call is stateless, so 50 individually
  passing trades can add up to something you didn't intend. Behavioral limits are a
  v0.2 roadmap item; the audit log already captures the raw data.
- **Options notional.** v1 sizes option orders by premium cost, which understates
  the controlled notional. The WARN message says so; delta/notional checks are v0.3.

See [threat-model.md](threat-model.md) for the full picture.

## The audit log

Every verdict on a file-backed policy and every policy change is appended to
`.agentrisk/audit.jsonl` (one JSON record per line). Use it for after-the-fact
review of what the guardrail decided and when a guardrail was relaxed.
