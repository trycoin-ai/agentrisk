"""check_trade_risk: pre-execution trade validation.

Simulates the proposed trade on the snapshot and evaluates every applicable
policy rule into a single PASS / WARN / BLOCK verdict. Fails closed on invalid
input or a missing policy, never blocks a risk-reducing trade, and only blocks
trades that worsen a breach.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import messages
from .audit import record as audit_record
from .classify import classify_trade, curated_asset_class, data_version
from .exposures import (
    BUCKET_ASSET_CLASS,
    BUCKET_SECTOR,
    BUCKET_TAG,
    Holding,
    PortfolioView,
)
from .models import (
    AssetClass,
    CheckResult,
    CheckStatus,
    Portfolio,
    RuleAction,
    Trade,
    TradeAction,
    Verdict,
)
from .policy import PolicyLoadError, resolve_policy
from .util import EPSILON, q1, q2, ratio_pct
from .version import __version__

PortfolioInput = Portfolio | dict
TradeInput = Trade | dict

_B = CheckStatus.block
_W = CheckStatus.warn
_P = CheckStatus.ok
_O = CheckStatus.overridden

_CID_FOR_KIND = {
    BUCKET_SECTOR: "max_sector",
    BUCKET_TAG: "max_tag",
    BUCKET_ASSET_CLASS: "max_asset_class",
}

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


def _annotate_block(check: CheckResult) -> None:
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


def _apply_overrides(
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


def _coerce_portfolio(p: PortfolioInput) -> Portfolio:
    return p if isinstance(p, Portfolio) else Portfolio(**p)


def _coerce_trade(t: TradeInput) -> Trade:
    return t if isinstance(t, Trade) else Trade(**t)


def _dec(x: float) -> Decimal:
    return Decimal(str(x))


# --------------------------------------------------------------------------- #
# Simulation                                                                  #
# --------------------------------------------------------------------------- #


def simulate(view: PortfolioView, trade: Trade) -> tuple[PortfolioView, dict[str, Any]]:
    """Apply the trade to a copy of the view. Total value is invariant (v1 ignores fees).

    Existing holdings stay valued at their snapshot price; the trade delta is
    applied at the trade's evaluation price. A sell is capped at the held value
    (you cannot sell more than you hold); the shortfall is flagged.
    """
    post = view.copy()
    value = trade.order_value
    notes: dict[str, Any] = {}
    held = post.find(trade.symbol)
    tclass = classify_trade(trade)

    if trade.action is TradeAction.buy:
        post.cash -= value
        if held is not None:
            held.value += value
        else:
            post.holdings.append(
                Holding(
                    symbol=trade.symbol,
                    value=value,
                    asset_class=trade.asset_class or tclass.asset_class,
                    sector=tclass.sector,
                    tags=tclass.tags,
                    classified=tclass.classified or trade.asset_class is not None,
                    is_option=trade.option is not None,
                )
            )
    else:  # sell
        held_value = held.value if held is not None else Decimal(0)
        if value > held_value + EPSILON:
            notes["insufficient_holdings"] = held_value
            fill = held_value
        else:
            fill = value
        post.cash += fill
        if held is not None:
            held.value -= fill
            if held.value <= EPSILON:
                post.holdings = [h for h in post.holdings if h is not held]
    return post, notes


# --------------------------------------------------------------------------- #
# Individual checks                                                           #
# --------------------------------------------------------------------------- #


def _precondition_checks(pre: PortfolioView, trade: Trade, notes: dict) -> list[CheckResult]:
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


def _restricted_check(trade: Trade, policy: Any) -> CheckResult | None:
    r = policy.restricted
    if trade.symbol in r.never_trade:
        return _make("restricted", _B, {"symbol": trade.symbol, "list": "never_trade"})
    if trade.symbol in r.warn_list:
        return _make("restricted", _W, {"symbol": trade.symbol, "list": "warn_list"})
    return None


def _asset_rule_checks(trade: Trade, policy: Any) -> list[CheckResult]:
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


def _single_position_check(
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


def _bucket_checks(
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


def _unverifiable_check(trade: Trade, policy: Any) -> CheckResult | None:
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


def _order_size_check(pre_total: Decimal, trade: Trade, policy: Any) -> CheckResult | None:
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


def _min_cash_check(
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


def _staleness_check(age_hours: float, policy: Any) -> CheckResult | None:
    max_age = policy.data_rules.max_snapshot_age_hours
    if age_hours > max_age:
        return _make("data_quality", _W, {
            "snapshot_age_hours": age_hours, "max_age_hours": max_age,
        })
    return None


def _numify(v: float) -> int | float:
    f = float(v)
    return int(f) if f == int(f) else f


# --------------------------------------------------------------------------- #
# Aggregation                                                                 #
# --------------------------------------------------------------------------- #


def _aggregate(checks: list[CheckResult]) -> str:
    if any(c.status is _B for c in checks):
        return "BLOCK"
    if any(c.status is _O for c in checks):
        return "OVERRIDDEN"
    if any(c.status is _W for c in checks):
        return "WARN"
    return "PASS"


def _engine() -> dict[str, Any]:
    return {"agentrisk_version": __version__, "classification_data_version": data_version()}


def _blocked(cid: str, message: str, summary: str, now: datetime,
             evaluated: dict | None = None) -> Verdict:
    return Verdict(
        verdict="BLOCK",
        proceed=False,
        summary=summary,
        checks=[CheckResult(id=cid, status=_B, message=message,
                            details={"override_tier": "none", "overridable": False})],
        acknowledgements_required=[],
        evaluated=evaluated or {},
        data_quality={},
        engine=_engine(),
    )


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #


def check_trade_risk(
    portfolio: PortfolioInput,
    trade: TradeInput,
    *,
    policy: Any | dict | None = None,
    policy_path: str | None = None,
    home: str | None = None,
    now: datetime | None = None,
    audit: bool = True,
    override: list[str] | None = None,
    override_reason: str | None = None,
) -> Verdict:
    now = now or datetime.now(timezone.utc)
    override_tokens = set(override or [])

    # 1. Validate inputs; fail closed to BLOCK rather than raising.
    try:
        pf = _coerce_portfolio(portfolio)
    except Exception as exc:  # noqa: BLE001 - any parse failure must fail closed
        return _blocked("invalid_snapshot", f"Portfolio failed validation: {exc}",
                        messages.invalid_input_summary(str(exc).splitlines()[0]), now)
    try:
        tr = _coerce_trade(trade)
    except Exception as exc:  # noqa: BLE001
        return _blocked("invalid_trade", f"Trade failed validation: {exc}",
                        messages.invalid_input_summary(str(exc).splitlines()[0]), now)

    # A caller may enrich classification, but must not contradict curated data for a
    # known instrument. Relabelling (e.g. crypto as equity) to dodge an asset rule
    # fails closed. Options carry their own detail, so they are exempt.
    seed_ac = curated_asset_class(tr.symbol)
    if tr.option is None and tr.asset_class is not None and seed_ac is not None \
            and tr.asset_class is not seed_ac:
        detail = (f"{tr.symbol} is classified as {seed_ac.value}, "
                  f"not {tr.asset_class.value}")
        return _blocked("invalid_trade", f"Trade classification conflict: {detail}.",
                        messages.invalid_input_summary(detail), now)

    # 2. Resolve policy; no policy means no guardrail, so fail closed. A policy file
    #    that exists but cannot be parsed also fails closed, with a generic message
    #    so the file's contents never leak through an error.
    try:
        pol, pol_meta = resolve_policy(policy, policy_path, home)
    except PolicyLoadError as exc:
        return _blocked("invalid_policy", str(exc), messages.invalid_policy_summary(), now)
    if pol is None:
        return _blocked("no_policy", messages.NO_POLICY_MESSAGE, messages.NO_POLICY_SUMMARY,
                        now, evaluated={"policy": pol_meta})

    # 3. Build views and simulate.
    pre = PortfolioView.from_portfolio(pf)
    pre_total = pre.total
    post, notes = simulate(pre, tr)
    age_hours = (now - pf.as_of).total_seconds() / 3600

    # 4. Run checks in a deterministic order.
    checks: list[CheckResult] = []
    checks.extend(_precondition_checks(pre, tr, notes))
    r = _restricted_check(tr, pol)
    if r is not None:
        checks.append(r)
    checks.extend(_asset_rule_checks(tr, pol))
    sp = _single_position_check(pre, post, tr, pol)
    if sp is not None:
        checks.append(sp)
    checks.extend(_bucket_checks(pre, post, tr, pol))
    uv = _unverifiable_check(tr, pol)
    if uv is not None:
        checks.append(uv)
    osz = _order_size_check(pre_total, tr, pol)
    if osz is not None:
        checks.append(osz)
    mc = _min_cash_check(post, tr, pol)
    if mc is not None:
        checks.append(mc)
    dq = _staleness_check(age_hours, pol)
    if dq is not None:
        checks.append(dq)

    # 5. Annotate blocks with overridability, then apply any user-approved bypass.
    for c in checks:
        _annotate_block(c)
    overridden, rejected = _apply_overrides(checks, override_tokens)

    # 6. Aggregate + compose.
    verdict_level = _aggregate(checks)
    ctx = {"symbol": tr.symbol, "action": tr.action.value}
    summary = messages.compose_summary(verdict_level, checks, ctx)
    ack = [c.message for c in checks if c.status is _W]

    result = Verdict(
        verdict=verdict_level,
        proceed=verdict_level != "BLOCK",
        summary=summary,
        checks=checks,
        acknowledgements_required=ack,
        overrides=overridden,
        override_rejected=rejected,
        evaluated={
            "action": tr.action.value,
            "symbol": tr.symbol,
            "quantity": float(tr.quantity),
            "price_used": q2(tr.eval_price or Decimal(0)),
            "order_value": q2(tr.order_value),
            "portfolio_as_of": pf.as_of.isoformat(),
            "policy": {
                "path": pol_meta["path"],
                "source": pol_meta["source"],
                "revision": pol_meta["revision"],
                "sha256": pol_meta["sha256"],
            },
        },
        data_quality={
            "unclassified_pct": q1(pre.unclassified_pct()),
            "snapshot_age_hours": q1(_dec(age_hours)),
            "warnings": [c.message for c in checks if c.id == "data_quality"],
        },
        engine=_engine(),
    )

    # 7. Audit (only for file-backed policies; best-effort). An override is logged
    #    as its own loud event so a bypassed guardrail always leaves a trail.
    if audit and pol_meta.get("path"):
        from pathlib import Path

        event = "trade_override" if overridden else "trade_check"
        payload = {
            "verdict": result.verdict,
            "proceed": result.proceed,
            "symbol": tr.symbol,
            "action": tr.action.value,
            "order_value": q2(tr.order_value),
            "summary": result.summary,
            "policy_revision": pol_meta["revision"],
        }
        if overridden:
            payload["overrides"] = overridden
            payload["override_reason"] = override_reason
        audit_record(Path(pol_meta["path"]), event, payload, now=now)

    return result
