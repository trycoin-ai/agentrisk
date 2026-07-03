# Concepts

## The mental model

AgentRisk is a pure function of three inputs:

```
(portfolio snapshot, proposed trade, risk policy)  ->  verdict
(portfolio snapshot, risk policy)                  ->  risk report
(policy fields or changes)                          ->  policy + diff
```

There is no hidden state beyond the policy file and the audit log, no network
access, and no LLM inside the core. The same inputs always produce the same
output. This determinism is the whole product promise, and it's what makes the
verdicts trustworthy and testable.

## Division of labor with the calling agent

AgentRisk deliberately does **not** understand natural language. The calling
agent (Claude or your own) owns that translation:

| The user says... | The agent calls... |
| --- | --- |
| "Am I overexposed to AI?" | `analyze_portfolio_risk(focus={"tag": "ai"})` |
| "Don't let any stock exceed 25%." | `generate_risk_policy(fields={"limits": {"max_single_position_pct": 25}})` |
| "Block leverage." | `... fields={"asset_rules": {"margin": "block"}}` |
| "Buy 20 NVDA." | `check_trade_risk(portfolio, {"action": "buy", "symbol": "NVDA", ...})` |

AgentRisk owns the math, the policy storage, and the verdicts. Because the agent's
translation is a structured tool call, it's visible in logs and auditable.

## What a verdict means

- **PASS**: no check was violated. `proceed = true`.
- **WARN**: no blocking violation, but at least one warning. `proceed = true`, and
  `acknowledgements_required` lists what to surface to the user first.
- **BLOCK**: at least one blocking violation. `proceed = false`.

A PASS is **not** a statement that a trade is safe, wise, or profitable, only
that it did not violate the rules *you* wrote. See [../DISCLAIMER.md](../DISCLAIMER.md).

## Classification

To reason about "AI exposure" or "sector concentration", AgentRisk needs to know
what each holding *is*. Resolution order is strict:

1. Metadata you put on the position/trade (always wins).
2. A bundled, versioned seed dataset.
3. Otherwise: **unclassified**, reported honestly, never guessed.

See [classification-data.md](classification-data.md).

## Determinism and time

The only time-dependent check is snapshot staleness. Both tools accept an optional
evaluation timestamp so tests (and reproducible runs) can pin "now"; in production
it defaults to the current UTC time.
