# Threat model

AgentRisk is a seatbelt, not a cage. Being explicit about what it can and cannot
protect against is part of using it responsibly.

## What AgentRisk protects against

- **Accidental limit breaches.** Trades that would push concentration, sector,
  theme, or asset-class exposure past the user's caps are blocked (when worsening)
  or warned (when approaching).
- **Disallowed instrument classes.** Crypto / options / margin can be warned or
  blocked per policy.
- **Fat-finger and runaway single orders.** Order-size and cash-floor checks catch
  a single order that's far too large or would drain cash.
- **Trading explicitly-restricted symbols.** A never-trade list hard-blocks.
- **Acting on bad data.** Stale snapshots warn; internally inconsistent snapshots
  block. Unclassified instruments are surfaced, never silently passed.
- **Silent guardrail relaxation.** Policy loosening requires a two-call confirm and
  is flagged in the diff and the audit log.
- **Casual bypass of a block.** A one-time `override` is scoped to a single trade,
  leaves the policy intact, and is written to the audit log as a `trade_override`
  record. Feasibility blocks (insufficient cash, invalid snapshot, no policy) can
  never be overridden, and hard prohibitions are tiered so the agent steers toward a
  policy edit first.

## What AgentRisk does NOT protect against

- **Integrator bypass.** AgentRisk returns advice; if your code calls the broker
  without gating on `proceed`, nothing was enforced. This is the single most
  important thing to get right; see the [integration guide](integration-guide.md).
- **A malicious or compromised agent.** The `confirm` flag on policy updates is set
  by the calling agent. A misbehaving agent could set it without asking the user.
  The gate provides **friction and an audit trail**, not cryptographic enforcement.
  Out-of-band confirmation is a roadmap item.
- **Prompt injection into the agent.** If untrusted content steers the agent into
  proposing bad trades, loosening the policy, or invoking a one-time `override`,
  AgentRisk's checks and audit log raise the bar but cannot fully prevent it. The
  `override` argument, like the policy-confirm flag, is set by the agent and assumes
  the agent honestly requires human approval; an autonomous agent that bypasses a
  hard block on its own is misusing the tool. Keep the policy file under your control
  and review `trade_override` and loosening records.
- **Death by a thousand cuts.** Each check is stateless (per-trade). Many small
  trades that each pass can aggregate into unintended exposure or churn. Behavioral
  limits (trades/day, turnover) are a v0.2 item; the audit log already records the
  data needed to analyze this after the fact.
- **Bad input data.** Verdicts are only as good as the snapshot and prices you
  supply. AgentRisk fetches nothing.
- **Options tail risk.** v1 sizes options by premium, understating notional/leverage.
  Delta/notional checks are v0.3.

## Hardening recommendations

- Gate execution on `verdict.proceed`. Always.
- Treat any LOOSENING diff as a human-in-the-loop decision.
- Keep `.agentrisk/` (policy + history + audit) under version control or backup so
  changes are reviewable.
- Provide fresh, complete snapshots; keep `max_snapshot_age_hours` tight.
