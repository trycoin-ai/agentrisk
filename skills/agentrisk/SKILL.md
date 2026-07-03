---
name: agentrisk
description: Pre-trade risk guardrails. Use before submitting, placing, changing, or canceling any trade or order through Robinhood MCP, Alpaca MCP, a broker API, or any custom execution tool. Every proposed trade goes through an AgentRisk risk check, and execution is gated on the verdict.
---

# AgentRisk pre-trade guardrails

Never place an order without a risk check first. This applies to every order,
however small, on every execution path: Robinhood MCP, Alpaca MCP, a broker API,
or a custom execution tool. AgentRisk itself never recommends or executes trades;
it only reports whether a proposed trade breaks the user's own policy.

Follow these four steps, in order, for every trade.

## 1. Classify

Translate the proposed trade into the structured proposal that `check_trade_risk`
expects: `action`, `symbol`, `quantity`, `order_type`, and `estimated_price`. Add
an `option` block for options orders, and set `uses_margin: true` for any margin
or leveraged order.

## 2. Check

Build a fresh portfolio snapshot from the execution venue's read tools (current
positions, cash, and prices, with `as_of` set to now), then call the `agentrisk`
MCP server's `check_trade_risk` with that snapshot and the proposal.

## 3. Respect the verdict

Read `proceed` and act on it:

- **PASS**: execution may continue.
- **WARN**: relay every item in `acknowledgements_required`, explain the risk in
  plain language, and proceed only after the user explicitly confirms.
- **BLOCK**: do not execute. Relay `summary`. Never bypass a block on your own
  initiative; if the user asks for a one-time exception, follow the override
  guidance in the `check_trade_risk` tool description.

## 4. Record

Append the returned `summary` to the order confirmation you show the user. When
the policy is file-backed, every verdict is written to `.agentrisk/audit.jsonl`
automatically, so there is no separate logging step.

## Hard rules

- If `check_trade_risk` is unavailable or errors, treat the trade as BLOCKED and
  stop. Say so plainly; do not guess a verdict.
- Never reorder or skip these steps, and never check after executing.
- A PASS means the trade did not break the user's own policy, not that it is safe
  or profitable.
- AgentRisk never recommends or executes trades. This skill only gates them.
