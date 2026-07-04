"""check_trade_risk: pre-execution trade validation.

Simulates the proposed trade on the snapshot and evaluates every applicable
policy rule into a single PASS / WARN / BLOCK verdict. Fails closed on invalid
input or a missing policy, never blocks a risk-reducing trade, and only blocks
trades that worsen a breach.

The rule catalog lives in ``checks.py`` and the one-time override tiering in
``overrides.py``; this module runs them in a fixed order and aggregates the result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import messages
from .audit import record as audit_record
from .checks import (
    asset_rule_checks,
    bucket_checks,
    min_cash_check,
    order_size_check,
    precondition_checks,
    restricted_check,
    single_position_check,
    staleness_check,
    unverifiable_check,
)
from .classify import classify_trade, curated_asset_class, data_version
from .exposures import Holding, PortfolioView
from .models import (
    CheckResult,
    CheckStatus,
    Portfolio,
    Trade,
    TradeAction,
    Verdict,
)
from .overrides import annotate_block, apply_overrides
from .policy import PolicyLoadError, resolve_policy
from .util import EPSILON, q1, q2
from .version import __version__

PortfolioInput = Portfolio | dict
TradeInput = Trade | dict

_B = CheckStatus.block
_W = CheckStatus.warn
_O = CheckStatus.overridden


def _coerce_portfolio(p: PortfolioInput) -> Portfolio:
    return p if isinstance(p, Portfolio) else Portfolio(**p)


def _coerce_trade(t: TradeInput) -> Trade:
    return t if isinstance(t, Trade) else Trade(**t)


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
    checks.extend(precondition_checks(pre, tr, notes))
    r = restricted_check(tr, pol)
    if r is not None:
        checks.append(r)
    checks.extend(asset_rule_checks(tr, pol))
    sp = single_position_check(pre, post, tr, pol)
    if sp is not None:
        checks.append(sp)
    checks.extend(bucket_checks(pre, post, tr, pol))
    uv = unverifiable_check(tr, pol)
    if uv is not None:
        checks.append(uv)
    osz = order_size_check(pre_total, tr, pol)
    if osz is not None:
        checks.append(osz)
    mc = min_cash_check(post, tr, pol)
    if mc is not None:
        checks.append(mc)
    dq = staleness_check(age_hours, pol)
    if dq is not None:
        checks.append(dq)

    # 5. Annotate blocks with overridability, then apply any user-approved bypass.
    for c in checks:
        annotate_block(c)
    overridden, rejected = apply_overrides(checks, override_tokens)

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
            "snapshot_age_hours": q1(Decimal(str(age_hours))),
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
