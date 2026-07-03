# Architecture

AgentRisk is a small pure core with three surfaces in front of it. The core does
the risk math and owns every user-facing word; the surfaces only translate inputs
and format outputs. Nothing in the core reaches the network, calls an LLM, or holds
hidden state.

## The layers

```
surfaces      cli.py            mcp_server.py         (library import)
                 \                   |                    /
public API              analyze_portfolio_risk   check_trade_risk   generate_risk_policy
                                 |                    |                    |
engines                       analyze.py           check.py            policy.py
                                  \                  /                    |
shared                        exposures.py     classify.py          store.py + audit.py
                                       \            |                     |
foundation                             models.py   data/            messages.py
```

- **models.py** is the type layer: pydantic models for `Portfolio`, `Trade`,
  `Policy`, `Verdict`, and `RiskReport`, plus the enums. Money is `Decimal`. Every
  other module speaks in these types.
- **classify.py** resolves an instrument to an asset class, sector, and tags. Caller
  metadata wins; otherwise it reads the bundled dataset in `data/`; otherwise the
  instrument is reported as unclassified. It never guesses.
- **exposures.py** turns a portfolio into a `PortfolioView`: post-trade weights,
  concentration, and per-bucket exposure. This is the shared arithmetic that both
  engines build on.
- **check.py** and **analyze.py** are the two engines. `check.py` simulates the
  post-trade portfolio, runs each rule, tiers any blocks for override, and returns a
  `Verdict`. `analyze.py` produces a read-only `RiskReport`. Neither writes anything.
- **policy.py** is the policy lifecycle (create, update, show). Updates return a diff
  that flags loosening changes and only write on confirm. It uses **store.py** for
  atomic writes and revision history and **audit.py** for the append-only log.
- **messages.py** holds all user-facing wording. Limits are always attributed to the
  user, and the words "safe", "approved", and "recommended" never appear in output.

## How a `check_trade_risk` call flows

1. The surface hands `check.py` a portfolio, a trade, and a policy reference.
2. `policy.py` resolves the policy (inline object, explicit path, or default
   location). A missing policy fails closed to BLOCK.
3. `classify.py` fills any gaps in the trade and holdings from `data/`.
4. `exposures.py` simulates the post-trade `PortfolioView`.
5. `check.py` runs the rules against that view, then tiers each block (soft, hard,
   or none) and applies any explicit one-time override.
6. `messages.py` composes the summary; `audit.py` records the event; the surface
   formats the `Verdict`.

## Where to make a change

| If you are changing... | Edit |
| --- | --- |
| A risk rule or the verdict math | `check.py` (and `exposures.py` if it is a new exposure) |
| A report section | `analyze.py` |
| Any wording a user sees | `messages.py` |
| A policy field or the diff logic | `models.py` and `policy.py` |
| How instruments are classified | `classify.py` and the dataset under `data/` |
| The public schema surface | the models, then run `python scripts/export_schemas.py` |

The invariants that must survive any change (fail closed, exits never trapped,
determinism, wording rules) are listed in [AGENTS.md](../AGENTS.md).
