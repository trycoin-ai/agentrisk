"""The risk-check catalog: one function per rule.

Each function evaluates a proposed trade against one policy rule on the pre- and
post-trade portfolio views and returns a ``CheckResult`` (or None when the rule does
not apply). The functions are pure: they read the views and the policy and never
write anything. ``check.py`` runs them in a fixed order and aggregates the verdict.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import messages
from .classify import classify_trade
from .exposures import (
    BUCKET_ASSET_CLASS,
    BUCKET_SECTOR,
    BUCKET_TAG,
    PortfolioView,
)
from .models import (
    AssetClass,
    CheckResult,
    CheckStatus,
    RuleAction,
    Trade,
    TradeAction,
)
from .util import EPSILON, q1, q2, ratio_pct

_B = CheckStatus.block
_W = CheckStatus.warn
_P = CheckStatus.ok

_CID_FOR_KIND = {
    BUCKET_SECTOR: "max_sector",
    BUCKET_TAG: "max_tag",
    BUCKET_ASSET_CLASS: "max_asset_class",
}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make(cid: str, status: CheckStatus, details: dict[str, Any]) -> CheckResult:
    return CheckResult(
        id=cid,
        status=status,
        message=messages.check_message(cid, status, details),
        details=details,
    )


def _rule_status(action: RuleAction) -> CheckStatus:
    return {RuleAction.allow: _P, RuleAction.warn: _W, RuleAction.block: _B}[action]


def _dec(x: float) -> Decimal:
    return Decimal(str(x))


def _numify(v: float) -> int | float:
    f = float(v)
    return int(f) if f == int(f) else f


# --------------------------------------------------------------------------- #
# Individual checks                                                           #
# --------------------------------------------------------------------------- #


def precondition_checks(pre: PortfolioView, trade: Trade, notes: dict) -> list[CheckResult]:
    out: list[CheckResult] = []
    if (
        trade.action is TradeAction.buy
        and not trade.uses_margin
        and trade.order_value > pre.cash + EPSILON
    ):
        out.append(_make("insufficient_cash", _B, {
            "order_value": q2(trade.order_value),
            "cash_available": q2(pre.cash),
        }))
    if "insufficient_holdings" in notes:
        out.append(_make("insufficient_holdings", _B, {
            "symbol": trade.symbol,
            "held_value": q2(notes["insufficient_holdings"]),
        }))
    return out


def restricted_check(trade: Trade, policy: Any) -> CheckResult | None:
    r = policy.restricted
    if trade.symbol in r.never_trade:
        return _make("restricted", _B, {"symbol": trade.symbol, "list": "never_trade"})
    if trade.symbol in r.warn_list:
        return _make("restricted", _W, {"symbol": trade.symbol, "list": "warn_list"})
    return None


def asset_rule_checks(trade: Trade, policy: Any) -> list[CheckResult]:
    tclass = classify_trade(trade)
    is_crypto = trade.asset_class is AssetClass.crypto or tclass.asset_class is AssetClass.crypto
    is_option = (
        trade.option is not None
        or trade.asset_class is AssetClass.option
        or tclass.asset_class is AssetClass.option
    )
    increasing = trade.action is TradeAction.buy
    out: list[CheckResult] = []

    if is_crypto:
        action = policy.asset_rules.crypto
        if not increasing:
            out.append(_make("asset_rule:crypto", _P, {"kind": "crypto", "reducing": True,
                                                       "action": action.value}))
        else:
            out.append(_make("asset_rule:crypto", _rule_status(action),
                             {"kind": "crypto", "action": action.value}))
    if is_option:
        action = policy.asset_rules.options
        if not increasing:
            out.append(_make("asset_rule:options", _P, {"kind": "options", "reducing": True,
                                                        "action": action.value}))
        else:
            out.append(_make("asset_rule:options", _rule_status(action),
                             {"kind": "options", "action": action.value}))
    if trade.uses_margin:
        action = policy.asset_rules.margin
        if not increasing:
            # Exits are never trapped: closing a leveraged position is always allowed,
            # matching the crypto and options rules above.
            out.append(_make("asset_rule:margin", _P, {"kind": "margin", "reducing": True,
                                                       "action": action.value}))
        else:
            out.append(_make("asset_rule:margin", _rule_status(action),
                             {"kind": "margin", "action": action.value}))

    if not out:
        out.append(_make("asset_rule", _P, {"kind": "equity", "action": "allow"}))
    return out


def single_position_check(
    pre: PortfolioView, post: PortfolioView, trade: Trade, policy: Any
) -> CheckResult | None:
    limit = policy.limits.max_single_position_pct
    if limit is None:
        return None
    limit_d = _dec(limit)
    pre_pct = pre.weight_pct(trade.symbol)
    post_pct = post.weight_pct(trade.symbol)
    increasing = post_pct > pre_pct + EPSILON
    reducing = post_pct < pre_pct - EPSILON
    util = ratio_pct(post_pct, limit_d)
    warn_thresh = limit_d * _dec(policy.limits.warn_at_utilization) / Decimal(100)

    d: dict[str, Any] = {
        "symbol": trade.symbol,
        "limit_pct": _numify(limit),
        "pre_trade_pct": q1(pre_pct),
        "post_trade_pct": q1(post_pct),
        "utilization_pct": q1(util),
    }
    if post_pct > limit_d + EPSILON:
        if increasing:
            return _make("max_single_position", _B, d)
        d["reducing"] = reducing
        return _make("max_single_position", _P, d)
    if increasing and post_pct >= warn_thresh - EPSILON:
        return _make("max_single_position", _W, d)
    if reducing:
        d["reducing"] = True
    return _make("max_single_position", _P, d)


def bucket_checks(
    pre: PortfolioView, post: PortfolioView, trade: Trade, policy: Any
) -> list[CheckResult]:
    lim = policy.limits
    warn_util = _dec(lim.warn_at_utilization) / Decimal(100)
    tclass = classify_trade(trade)
    trade_ac = trade.asset_class or tclass.asset_class

    affected = {
        BUCKET_SECTOR: {tclass.sector} if tclass.sector else set(),
        BUCKET_TAG: set(tclass.tags),
        BUCKET_ASSET_CLASS: {trade_ac.value} if trade_ac else set(),
    }
    out: list[CheckResult] = []
    for kind, limits_map in (
        (BUCKET_SECTOR, lim.max_sector_pct),
        (BUCKET_TAG, lim.max_tag_pct),
        (BUCKET_ASSET_CLASS, lim.max_asset_class_pct),
    ):
        for key, limit in sorted(limits_map.items()):
            limit_d = _dec(limit)
            pre_pct = pre.bucket_pct(kind, key)
            post_pct = post.bucket_pct(kind, key)
            is_affected = key in affected[kind]
            increasing = post_pct > pre_pct + EPSILON
            reducing = post_pct < pre_pct - EPSILON
            over = post_pct > limit_d + EPSILON
            util = ratio_pct(post_pct, limit_d)
            d = {
                "kind": kind, "key": key, "limit_pct": _numify(limit),
                "pre_trade_pct": q1(pre_pct), "post_trade_pct": q1(post_pct),
                "utilization_pct": q1(util),
            }
            cid = _CID_FOR_KIND[kind]
            if over:
                if is_affected and increasing:
                    out.append(_make(cid, _B, d))
                elif is_affected and reducing:
                    d["reducing"] = True
                    out.append(_make(cid, _P, d))
                else:
                    out.append(_make("unrelated_breach", _W, d))
            elif is_affected and increasing and post_pct >= limit_d * warn_util - EPSILON:
                out.append(_make(cid, _W, d))
            elif is_affected:
                out.append(_make(cid, _P, d))
            # unaffected & under limit: no check (avoid noise)
    return out


def unverifiable_check(trade: Trade, policy: Any) -> CheckResult | None:
    """Warn when a policy limit cannot be verified against this instrument.

    Broad asset-class coverage means most tickers are known to be an equity, but a
    long-tail equity may have no curated sector. If the policy caps a sector, that
    cap cannot be enforced against a sector-unknown equity, and silently ignoring it
    would weaken the guardrail, so we surface it.
    """
    tclass = classify_trade(trade)
    trade_ac = trade.asset_class or tclass.asset_class
    has_sector_cap = bool(policy.limits.max_sector_pct)
    has_bucket_caps = has_sector_cap or bool(
        policy.limits.max_tag_pct or policy.limits.max_asset_class_pct
    )

    if trade_ac is None:
        # Fully unknown instrument: nothing about it can be checked.
        if has_bucket_caps:
            return _make("unverifiable_exposure", _W,
                         {"symbol": trade.symbol, "dimensions": ["classification"]})
    elif trade_ac is AssetClass.equity and tclass.sector is None and has_sector_cap:
        # Known equity, unknown sector: a sector cap cannot be verified against it.
        return _make("unverifiable_exposure", _W,
                     {"symbol": trade.symbol, "dimensions": ["sector"]})
    return None


def order_size_check(pre_total: Decimal, trade: Trade, policy: Any) -> CheckResult | None:
    orr = policy.order_rules
    if orr.max_order_pct_of_portfolio is None and orr.max_order_value is None:
        return None
    order_value = trade.order_value
    order_pct = ratio_pct(order_value, pre_total)
    d: dict[str, Any] = {"order_value": q2(order_value), "order_pct": q1(order_pct)}

    if orr.max_order_value is not None and order_value > _dec(orr.max_order_value) + EPSILON:
        d["over"] = "value"
        d["limit_value"] = _numify(orr.max_order_value)
        if orr.max_order_pct_of_portfolio is not None:
            d["limit_pct"] = _numify(orr.max_order_pct_of_portfolio)
        return _make("max_order_size", _B, d)
    if (
        orr.max_order_pct_of_portfolio is not None
        and order_pct > _dec(orr.max_order_pct_of_portfolio) + EPSILON
    ):
        d["over"] = "pct"
        d["limit_pct"] = _numify(orr.max_order_pct_of_portfolio)
        return _make("max_order_size", _B, d)

    if orr.max_order_pct_of_portfolio is not None:
        d["limit_pct"] = _numify(orr.max_order_pct_of_portfolio)
    return _make("max_order_size", _P, d)


def min_cash_check(
    post: PortfolioView, trade: Trade, policy: Any
) -> CheckResult | None:
    floor = policy.order_rules.min_cash_pct
    if floor is None or trade.action is not TradeAction.buy:
        return None
    post_cash_pct = post.cash_pct()
    d = {"post_cash_pct": q1(post_cash_pct), "floor_pct": _numify(floor)}
    if post_cash_pct < _dec(floor) - EPSILON:
        return _make("min_cash", _B, d)
    return _make("min_cash", _P, d)


def staleness_check(age_hours: float, policy: Any) -> CheckResult | None:
    max_age = policy.data_rules.max_snapshot_age_hours
    if age_hours > max_age:
        return _make("data_quality", _W, {
            "snapshot_age_hours": age_hours, "max_age_hours": max_age,
        })
    return None
