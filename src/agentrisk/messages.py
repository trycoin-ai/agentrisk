"""Templated wording for every user-facing string.

Keeping the wording in one module makes the language rules enforceable in review
(limits are always the user's; never "safe" or "approved") and lets golden tests
pin each message. ``check_message`` renders a standalone sentence for a check;
``summary_clause`` renders the clause spliced into the one-line summary.
"""

from __future__ import annotations

from typing import Any

from .models import CheckResult, CheckStatus

# --------------------------------------------------------------------------- #
# Formatting helpers                                                          #
# --------------------------------------------------------------------------- #


def fmt_pct(x: float | int) -> str:
    """`25.0 -> "25%"`, `31.2 -> "31.2%"` (drop a trailing .0 for round limits)."""
    xf = float(x)
    if xf == int(xf):
        return f"{int(xf)}%"
    return f"{xf:.1f}%"


def fmt_money(x: float | int) -> str:
    """`1680 -> "$1,680"`, `8.4 -> "$8.40"`, `25000 -> "$25,000"`."""
    xf = float(x)
    if abs(xf) < 10:
        return f"${xf:,.2f}"
    return f"${xf:,.0f}"


_TAG_DISPLAY = {
    "ai": "AI",
    "ev": "EV",
    "broad-market": "broad-market",
}
_ASSET_CLASS_DISPLAY = {
    "equity": "equity",
    "etf": "ETF",
    "crypto": "crypto",
    "option": "options",
    "cash": "cash",
}


def bucket_label(kind: str, key: str) -> str:
    """Human display noun for a sector / tag / asset-class bucket."""
    if kind == "tag":
        return _TAG_DISPLAY.get(key, key.upper() if len(key) <= 3 else key)
    if kind == "asset_class":
        return _ASSET_CLASS_DISPLAY.get(key, key)
    return key  # sector name as-is


def _bucket_noun(kind: str, key: str) -> str:
    label = bucket_label(kind, key)
    if kind == "sector":
        return f"{label} sector"
    if kind == "tag":
        return f"{label} theme"
    return label  # asset class


# --------------------------------------------------------------------------- #
# Per-check messages (standalone) + summary clauses (spliced)                 #
# --------------------------------------------------------------------------- #


def check_message(cid: str, status: CheckStatus, d: dict[str, Any]) -> str:
    """Standalone sentence for ``verdict.checks[].message``."""
    base = cid.split(":", 1)[0]

    if base == "insufficient_cash":
        return (
            f"This buy needs {fmt_money(d['order_value'])} but only "
            f"{fmt_money(d['cash_available'])} cash is available."
        )
    if base == "insufficient_holdings":
        return (
            f"This order sells more {d['symbol']} than you hold "
            f"({fmt_money(d['held_value'])} of exposure)."
        )
    if base == "restricted":
        if status is CheckStatus.block:
            return f"{d['symbol']} is on your never-trade list."
        return f"{d['symbol']} is on your watch list."
    if base == "asset_rule":
        return _asset_rule_message(status, d)
    if base == "max_single_position":
        return _single_position_message(status, d)
    if base in ("max_sector", "max_tag", "max_asset_class"):
        return _bucket_message(status, d)
    if base == "unverifiable_exposure":
        if "sector" in d.get("dimensions", []):
            return (
                f"{d['symbol']}'s sector is unknown, so it could not be checked "
                f"against your sector limits."
            )
        return (
            f"{d['symbol']} could not be classified, so it could not be checked "
            f"against your sector, theme, or asset-class limits."
        )
    if base == "unrelated_breach":
        noun = _bucket_noun(d["kind"], d["key"])
        return (
            f"{noun.capitalize()} exposure is already {fmt_pct(d['post_trade_pct'])}, "
            f"above your {fmt_pct(d['limit_pct'])} limit (this trade does not change it)."
        )
    if base == "max_order_size":
        return _order_size_message(status, d)
    if base == "min_cash":
        return (
            f"This trade would leave cash at {fmt_pct(d['post_cash_pct'])}, below your "
            f"{fmt_pct(d['floor_pct'])} minimum."
            if status is CheckStatus.block
            else f"Cash stays at {fmt_pct(d['post_cash_pct'])}, above your "
            f"{fmt_pct(d['floor_pct'])} minimum."
        )
    if base == "data_quality":
        return (
            f"Your portfolio snapshot is {d['snapshot_age_hours']:.0f} hours old and may "
            f"not reflect current prices."
        )
    return d.get("message", "Check completed.")  # pragma: no cover


def summary_clause(cid: str, status: CheckStatus, d: dict[str, Any]) -> str:
    """Lower-cased clause for the one-line summary headline."""
    base = cid.split(":", 1)[0]

    if base == "insufficient_cash":
        return (
            f"this buy needs {fmt_money(d['order_value'])} but only "
            f"{fmt_money(d['cash_available'])} cash is available"
        )
    if base == "insufficient_holdings":
        return f"this order sells more {d['symbol']} than you hold"
    if base == "restricted":
        if status is CheckStatus.block:
            return f"{d['symbol']} is on your never-trade list"
        return f"{d['symbol']} is on your watch list"
    if base == "asset_rule":
        return _asset_rule_clause(status, d)
    if base == "max_single_position":
        if status is CheckStatus.block:
            return (
                f"this trade would increase {d['symbol']} to "
                f"{fmt_pct(d['post_trade_pct'])} of your portfolio, above your "
                f"{fmt_pct(d['limit_pct'])} single-name limit"
            )
        return (
            f"this trade brings {d['symbol']} to {fmt_pct(d['post_trade_pct'])} of your "
            f"portfolio, which is {fmt_pct(d['utilization_pct'])} of your "
            f"{fmt_pct(d['limit_pct'])} single-name limit"
        )
    if base in ("max_sector", "max_tag", "max_asset_class"):
        noun = _bucket_noun(d["kind"], d["key"])
        if status is CheckStatus.block:
            return (
                f"this trade would increase {noun} exposure to "
                f"{fmt_pct(d['post_trade_pct'])}, above your {fmt_pct(d['limit_pct'])} limit"
            )
        return (
            f"this trade brings {noun} exposure to {fmt_pct(d['post_trade_pct'])}, which is "
            f"{fmt_pct(d['utilization_pct'])} of your {fmt_pct(d['limit_pct'])} limit"
        )
    if base == "unverifiable_exposure":
        if "sector" in d.get("dimensions", []):
            return (
                f"{d['symbol']}'s sector is unknown, so it could not be checked "
                f"against your sector limits"
            )
        return (
            f"{d['symbol']} could not be classified, so it could not be checked "
            f"against your sector, theme, or asset-class limits"
        )
    if base == "unrelated_breach":
        noun = _bucket_noun(d["kind"], d["key"])
        return (
            f"{noun} exposure is already {fmt_pct(d['post_trade_pct'])}, above your "
            f"{fmt_pct(d['limit_pct'])} limit (unchanged by this trade)"
        )
    if base == "max_order_size":
        if d.get("over") == "value":
            return (
                f"this order is {fmt_money(d['order_value'])}, above your "
                f"{fmt_money(d['limit_value'])} single-order cap"
            )
        return (
            f"this order is {fmt_pct(d['order_pct'])} of your portfolio value, above your "
            f"{fmt_pct(d['limit_pct'])} single-order cap"
        )
    if base == "min_cash":
        return (
            f"this trade would leave cash at {fmt_pct(d['post_cash_pct'])}, below your "
            f"{fmt_pct(d['floor_pct'])} minimum"
        )
    if base == "data_quality":
        return (
            f"your portfolio snapshot is {d['snapshot_age_hours']:.0f} hours old and may "
            f"not reflect current prices"
        )
    return "a policy check produced a result"  # pragma: no cover


# -- sub-renderers ---------------------------------------------------------- #


def _single_position_message(status: CheckStatus, d: dict[str, Any]) -> str:
    sym = d["symbol"]
    limit = fmt_pct(d["limit_pct"])
    post = fmt_pct(d["post_trade_pct"])
    pre = fmt_pct(d["pre_trade_pct"])
    if status is CheckStatus.block:
        return f"{sym} would rise from {pre} to {post} of portfolio value, above your {limit} limit."
    if status is CheckStatus.warn:
        if d.get("reducing"):
            return f"{sym} falls to {post} of your portfolio but remains above your {limit} limit."
        return (
            f"{sym} would reach {post} of your portfolio, which is "
            f"{fmt_pct(d['utilization_pct'])} of your {limit} limit."
        )
    # pass
    if d.get("reducing"):
        return f"This trade reduces {sym} from {pre} to {post} of your portfolio, within your {limit} limit."
    return f"{sym} stays at {post} of your portfolio, under your {limit} limit."


def _bucket_message(status: CheckStatus, d: dict[str, Any]) -> str:
    noun = _bucket_noun(d["kind"], d["key"])
    limit = fmt_pct(d["limit_pct"])
    post = fmt_pct(d["post_trade_pct"])
    if status is CheckStatus.block:
        return f"{noun.capitalize()} exposure would rise to {post}, above your {limit} limit."
    if status is CheckStatus.warn:
        return (
            f"{noun.capitalize()} exposure would reach {post}, which is "
            f"{fmt_pct(d['utilization_pct'])} of your {limit} limit."
        )
    return f"{noun.capitalize()} exposure stays at {post}, under your {limit} limit."


def _asset_rule_message(status: CheckStatus, d: dict[str, Any]) -> str:
    kind = d["kind"]
    if d.get("reducing"):
        if kind == "crypto":
            return "This reduces crypto exposure and is allowed (you can always exit)."
        if kind == "options":
            return "This closes/reduces an options position and is allowed."
        return "This reduces leveraged exposure and is allowed."
    if kind == "crypto":
        if status is CheckStatus.block:
            return "Your policy blocks new crypto exposure."
        if status is CheckStatus.warn:
            return "Your policy asks to be warned before increasing crypto exposure."
        return "Crypto trades are allowed by your policy."
    if kind == "options":
        if status is CheckStatus.block:
            return "Your policy blocks options trades."
        if status is CheckStatus.warn:
            return "Your policy asks to be warned before options trades."
        return "Options trades are allowed by your policy."
    if kind == "margin":
        if status is CheckStatus.block:
            return "This margin order is not allowed because your policy blocks leverage."
        if status is CheckStatus.warn:
            return "Your policy asks to be warned before margin/leverage is used."
        return "Margin use is allowed by your policy."
    if kind == "equity":  # the "nothing special applies" case
        return "This trade is in an asset class your policy allows."
    return "Asset-class rules checked."  # pragma: no cover


def _asset_rule_clause(status: CheckStatus, d: dict[str, Any]) -> str:
    kind = d["kind"]
    if kind == "crypto":
        if status is CheckStatus.block:
            return "your policy blocks new crypto exposure"
        return "your policy asks to be warned before increasing crypto exposure"
    if kind == "options":
        if status is CheckStatus.block:
            return "your policy blocks options trades"
        return "your policy asks to be warned before options trades"
    if kind == "margin":
        if status is CheckStatus.block:
            return "this margin order is not allowed because your policy blocks leverage"
        return "your policy asks to be warned before margin/leverage is used"
    return "an asset-class rule applies"  # pragma: no cover


def _order_size_message(status: CheckStatus, d: dict[str, Any]) -> str:
    if status is CheckStatus.block:
        if d.get("over") == "value":
            return (
                f"This order is {fmt_money(d['order_value'])}, above your "
                f"{fmt_money(d['limit_value'])} single-order cap."
            )
        return (
            f"This order is {fmt_pct(d['order_pct'])} of your portfolio value, above your "
            f"{fmt_pct(d['limit_pct'])} single-order cap."
        )
    return f"Order is {fmt_pct(d['order_pct'])} of your portfolio value, within your single-order cap."


# --------------------------------------------------------------------------- #
# One-line verdict summary                                                    #
# --------------------------------------------------------------------------- #

# Lower index = higher priority when choosing the decisive check for the headline.
_PRIORITY = {
    "insufficient_cash": 1,
    "insufficient_holdings": 1,
    "invalid_snapshot": 0,
    "no_policy": 0,
    "restricted": 2,
    "asset_rule": 3,
    "max_single_position": 4,
    "max_sector": 5,
    "max_tag": 5,
    "max_asset_class": 5,
    "unverifiable_exposure": 6,
    "max_order_size": 7,
    "min_cash": 8,
    "data_quality": 9,
    "unrelated_breach": 10,
}


def _priority(cid: str) -> int:
    return _PRIORITY.get(cid.split(":", 1)[0], 50)


def compose_summary(
    level: str,
    checks: list[CheckResult],
    ctx: dict[str, Any],
) -> str:
    if level == "BLOCK":
        blockers = sorted(
            (c for c in checks if c.status is CheckStatus.block),
            key=lambda c: _priority(c.id),
        )
        clause = summary_clause(blockers[0].id, blockers[0].status, blockers[0].details)
        return f"Blocked by AgentRisk: {clause}."

    if level == "OVERRIDDEN":
        ov = [c for c in checks if c.status is CheckStatus.overridden]
        labels = [override_label(c.id, c.details) for c in ov]
        hard = any(c.details.get("override_tier") == "hard" for c in ov)
        if len(labels) == 1:
            body = f"your {labels[0]}"
        else:
            body = "your " + ", ".join(labels[:-1]) + f", and {labels[-1]}"
        msg = (
            f"Overridden by user: this trade bypassed {body} "
            f"(one-time bypass; your policy is unchanged)."
        )
        if hard:
            msg += " This bypassed a hard block you set, so review it carefully."
        return msg

    if level == "WARN":
        warns = sorted(
            (c for c in checks if c.status is CheckStatus.warn),
            key=lambda c: _priority(c.id),
        )
        n = len(warns)
        head = summary_clause(warns[0].id, warns[0].status, warns[0].details)
        plural = "s" if n > 1 else ""
        return f"Risk check passed with {n} warning{plural}: {head}."

    # PASS
    return f"Risk check passed. {_pass_headline(checks, ctx)}"


def override_label(cid: str, d: dict[str, Any]) -> str:
    """Short noun phrase naming the guardrail that was bypassed (for summaries)."""
    base = cid.split(":", 1)[0]
    if base == "max_order_size":
        if d.get("over") == "value":
            return f"{fmt_money(d['limit_value'])} single-order cap"
        return f"{fmt_pct(d['limit_pct'])} single-order cap"
    if base == "max_single_position":
        return f"{fmt_pct(d['limit_pct'])} single-name limit"
    if base in ("max_sector", "max_tag", "max_asset_class"):
        return f"{fmt_pct(d['limit_pct'])} {_bucket_noun(d['kind'], d['key'])} limit"
    if base == "min_cash":
        return f"{fmt_pct(d['floor_pct'])} cash floor"
    if base == "asset_rule":
        return {
            "crypto": "block on new crypto exposure",
            "options": "block on options trades",
            "margin": "block on margin/leverage",
        }.get(d.get("kind", ""), "asset-class block")
    if base == "restricted":
        return f"never-trade rule on {d.get('symbol')}"
    return base


def overridden_message(cid: str, details: dict[str, Any]) -> str:
    """Standalone message for a block the user bypassed for this one trade."""
    return f"Bypassed for this trade (one-time user override): your {override_label(cid, details)}."


def _pass_headline(checks: list[CheckResult], ctx: dict[str, Any]) -> str:
    sp = next((c for c in checks if c.id == "max_single_position"), None)
    if sp is not None:
        d = sp.details
        if d.get("reducing"):
            tail = (
                f", bringing it back under your {fmt_pct(d['limit_pct'])} limit"
                if d["post_trade_pct"] <= d["limit_pct"]
                else f", though it remains above your {fmt_pct(d['limit_pct'])} limit"
            )
            return (
                f"This {ctx.get('action', 'trade')} reduces {d['symbol']} from "
                f"{fmt_pct(d['pre_trade_pct'])} to {fmt_pct(d['post_trade_pct'])} of your "
                f"portfolio{tail}."
            )
        return (
            f"This trade keeps {d['symbol']} at {fmt_pct(d['post_trade_pct'])} of your "
            f"portfolio, under your {fmt_pct(d['limit_pct'])} single-name limit, and all "
            f"other policy checks passed."
        )
    return "This trade is within your risk policy."


# --------------------------------------------------------------------------- #
# Fixed messages                                                              #
# --------------------------------------------------------------------------- #

NO_POLICY_SUMMARY = (
    "Blocked by AgentRisk: no risk policy was found. Create one with "
    "generate_risk_policy before trading."
)
NO_POLICY_MESSAGE = (
    "No risk policy could be resolved (checked the inline policy, the given path, and "
    "the default location). AgentRisk fails closed: with no rules to check against, a "
    "trade cannot pass."
)


def invalid_input_summary(detail: str) -> str:
    return f"Blocked by AgentRisk: the portfolio or trade could not be validated ({detail})."


def invalid_policy_summary() -> str:
    return (
        "Blocked by AgentRisk: the policy file exists but could not be read or "
        "validated. Fix or recreate the policy before trading."
    )


# --------------------------------------------------------------------------- #
# Policy plain-English summary                                                #
# --------------------------------------------------------------------------- #


def policy_summary(policy: Any) -> list[str]:
    """Render a Policy model as a human-readable list of its rules."""
    lines: list[str] = []
    lim = policy.limits
    if lim.max_single_position_pct is not None:
        lines.append(f"Max any single position: {fmt_pct(lim.max_single_position_pct)} of portfolio.")
    for sector, pct in sorted(lim.max_sector_pct.items()):
        lines.append(f"Max {bucket_label('sector', sector)} sector: {fmt_pct(pct)}.")
    for tag, pct in sorted(lim.max_tag_pct.items()):
        lines.append(f"Max {bucket_label('tag', tag)} theme: {fmt_pct(pct)}.")
    for ac, pct in sorted(lim.max_asset_class_pct.items()):
        lines.append(f"Max {bucket_label('asset_class', ac)} asset class: {fmt_pct(pct)}.")

    ar = policy.asset_rules
    lines.append(f"Crypto trades: {ar.crypto.value}.")
    lines.append(f"Options trades: {ar.options.value}.")
    lines.append(f"Margin / leverage: {ar.margin.value}.")

    orr = policy.order_rules
    if orr.max_order_pct_of_portfolio is not None:
        lines.append(f"Max single order: {fmt_pct(orr.max_order_pct_of_portfolio)} of portfolio.")
    if orr.max_order_value is not None:
        lines.append(f"Max single order value: {fmt_money(orr.max_order_value)}.")
    if orr.min_cash_pct is not None:
        lines.append(f"Minimum cash after buys: {fmt_pct(orr.min_cash_pct)}.")

    if policy.restricted.never_trade:
        lines.append(f"Never trade: {', '.join(policy.restricted.never_trade)}.")
    if policy.restricted.warn_list:
        lines.append(f"Warn on: {', '.join(policy.restricted.warn_list)}.")

    lines.append(f"Warn when any limit reaches {fmt_pct(lim.warn_at_utilization)} utilization.")
    lines.append(f"Snapshot considered stale after {policy.data_rules.max_snapshot_age_hours:.0f}h.")
    return lines
