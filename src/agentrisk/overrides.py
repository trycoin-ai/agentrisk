"""One-time override tiering for blocking checks.

A block can be bypassed for a single trade without editing the policy. This module
decides whether and how each block may be bypassed (its tier), annotates blocks with
that metadata, and applies an approved bypass by downgrading the block to
'overridden'. No verdict math lives here.
"""

from __future__ import annotations

from . import messages
from .models import CheckResult, CheckStatus

_B = CheckStatus.block
_O = CheckStatus.overridden

# Override tiers, keyed by the base check id (the part before any ':').
#   none : feasibility / validity blocks that must never be bypassed.
#   hard : explicit prohibitions the user set; bypassable only with a human in the
#          loop, and the agent should offer a policy edit first.
#   soft : tunable numeric limits; a one-time bypass is offered directly.
_NON_OVERRIDABLE_BASE = {
    "no_policy", "invalid_policy", "invalid_snapshot", "invalid_trade",
    "insufficient_cash", "insufficient_holdings",
}
_HARD_BASE = {"restricted", "asset_rule"}


def _override_tier(check_id: str) -> str:
    base = check_id.split(":", 1)[0]
    if base in _NON_OVERRIDABLE_BASE:
        return "none"
    if base in _HARD_BASE:
        return "hard"
    return "soft"


def _override_token(check: CheckResult) -> str:
    """The exact string a caller passes to ``override`` to bypass this block."""
    if check.id in ("max_sector", "max_tag", "max_asset_class"):
        key = check.details.get("key")
        return f"{check.id}:{key}" if key else check.id
    return check.id


def annotate_block(check: CheckResult) -> None:
    """Tag a blocking check with whether and how it can be bypassed."""
    if check.status is not _B:
        return
    tier = _override_tier(check.id)
    check.details["override_tier"] = tier
    check.details["overridable"] = tier != "none"
    check.details["override_token"] = _override_token(check)
    if tier == "hard":
        # Guidance the agent surfaces: change the policy rather than bypass casually.
        check.details["override_guidance"] = "prefer_policy_edit"


def apply_overrides(
    checks: list[CheckResult], tokens: set[str]
) -> tuple[list[str], list[str]]:
    """Downgrade approved block(s) to 'overridden'. Returns (overridden, rejected)."""
    overridden: list[str] = []
    rejected: list[str] = []
    for c in checks:
        if c.status is not _B:
            continue
        token = c.details.get("override_token", c.id)
        if token not in tokens and c.id not in tokens:
            continue
        if _override_tier(c.id) == "none":
            rejected.append(token)
            continue
        c.status = _O
        c.message = messages.overridden_message(c.id, c.details)
        overridden.append(token)
    return overridden, rejected
