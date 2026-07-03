"""AgentRisk: pre-execution risk checks for AI trading agents.

Public API (the three tools plus the models you pass to them):

    from agentrisk import (
        analyze_portfolio_risk,   # "what risk am I holding?"
        check_trade_risk,         # "should this trade go through?"  -> PASS/WARN/BLOCK
        generate_risk_policy,     # "what are my rules?"  create / update / show
    )

The core is pure: no network calls, no LLM calls, no API keys. The calling agent
translates a user's words into these structured calls; AgentRisk does the math,
stores the policy, and returns verdicts.

AgentRisk never recommends trades and never executes them. A PASS means a trade
did not violate the rules *you* wrote, not that it is safe or advisable. See
DISCLAIMER.md.
"""

from __future__ import annotations

from .analyze import analyze_portfolio_risk
from .check import check_trade_risk
from .models import (
    AssetClass,
    CheckResult,
    CheckStatus,
    OptionDetail,
    OrderType,
    Policy,
    PolicyResult,
    Portfolio,
    Position,
    RiskReport,
    RuleAction,
    Trade,
    TradeAction,
    Verdict,
)
from .policy import generate_risk_policy
from .version import __version__

__all__ = [
    "analyze_portfolio_risk",
    "check_trade_risk",
    "generate_risk_policy",
    # models
    "Portfolio",
    "Position",
    "Trade",
    "Policy",
    "OptionDetail",
    "Verdict",
    "RiskReport",
    "PolicyResult",
    "CheckResult",
    # enums
    "AssetClass",
    "OrderType",
    "TradeAction",
    "RuleAction",
    "CheckStatus",
    "__version__",
]
