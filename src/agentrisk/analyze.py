"""analyze_portfolio_risk: read-only portfolio risk report.

Concentration, exposure breakdowns, an optional policy-compliance audit, and an
optional focus spotlight. Writes nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .classify import data_version
from .exposures import (
    BUCKET_ASSET_CLASS,
    BUCKET_SECTOR,
    BUCKET_TAG,
    HHI_BANDS_DOC,
    PortfolioView,
    hhi_band,
    rounded_buckets,
    rounded_positions,
)
from .models import Portfolio, RiskReport
from .policy import PolicyLoadError, resolve_policy
from .util import EPSILON, q1, q2, q4, ratio_pct
from .version import __version__

PortfolioInput = Portfolio | dict

V1_LIMITATIONS = [
    "ETF look-through not performed (v1): an ETF is treated as a single position, "
    "not decomposed into its holdings.",
    "Stress scenarios ('tech -20%') are not available in v1.",
    "Duplicated-risk / overlap analysis is not available in v1.",
]


def _coerce_portfolio(p: PortfolioInput) -> Portfolio:
    return p if isinstance(p, Portfolio) else Portfolio(**p)


def _status(current: Decimal, limit: float, warn_at: float) -> tuple[str, Decimal]:
    limit_d = Decimal(str(limit))
    utilization = ratio_pct(current, limit_d) if limit_d > 0 else Decimal(0)
    if current > limit_d + EPSILON:
        return "breached", utilization
    if utilization >= Decimal(str(warn_at)) - EPSILON:
        return "near_limit", utilization
    return "ok", utilization


def _evaluate_compliance(view: PortfolioView, policy: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    lim = policy.limits
    warn_at = lim.warn_at_utilization

    if lim.max_single_position_pct is not None and view.holdings:
        # The binding case is the single largest position.
        top_symbol, top_pct = max(
            ((h.symbol, view.weight_pct(h.symbol)) for h in view.holdings),
            key=lambda t: (t[1], t[0]),
        )
        status, util = _status(top_pct, lim.max_single_position_pct, warn_at)
        results.append({
            "rule": "limits.max_single_position_pct",
            "limit": lim.max_single_position_pct,
            "current": q1(top_pct),
            "utilization_pct": q1(util),
            "status": status,
            "subject": top_symbol,
        })

    for kind, limits_map, prefix in (
        (BUCKET_SECTOR, lim.max_sector_pct, "limits.max_sector_pct"),
        (BUCKET_TAG, lim.max_tag_pct, "limits.max_tag_pct"),
        (BUCKET_ASSET_CLASS, lim.max_asset_class_pct, "limits.max_asset_class_pct"),
    ):
        for key, limit in sorted(limits_map.items()):
            current = view.bucket_pct(kind, key)
            status, util = _status(current, limit, warn_at)
            results.append({
                "rule": f"{prefix}.{key}",
                "limit": limit,
                "current": q1(current),
                "utilization_pct": q1(util),
                "status": status,
                "subject": key,
            })

    # Asset-rule conflicts: a held position that a 'block' rule would forbid buying.
    for kind, rule in (
        ("crypto", policy.asset_rules.crypto),
        ("option", policy.asset_rules.options),
    ):
        if rule.value == "block":
            held = view.bucket_pct(BUCKET_ASSET_CLASS, kind)
            if held > EPSILON:
                results.append({
                    "rule": f"asset_rules.{kind}",
                    "limit": None,
                    "current": q1(held),
                    "utilization_pct": None,
                    "status": "breached",
                    "subject": kind,
                    "note": f"policy blocks new {kind} exposure; you already hold "
                            f"{q1(held)}% (existing holdings are reported, not forced to sell)",
                })
    return results


def _build_focus(view: PortfolioView, focus: dict, policy: Any | None) -> dict[str, Any]:
    dim = next(iter(focus), None)
    if dim is None:
        return {"query": {}, "error": "empty focus (expected tag|sector|asset_class|symbol)"}
    value = focus[dim]
    out: dict[str, Any] = {"query": {dim: value}}

    if dim == "symbol":
        sym = str(value).upper()
        out["exposure_pct"] = q1(view.weight_pct(sym))
        out["found"] = view.find(sym) is not None
        return out

    mapping = {"tag": BUCKET_TAG, "sector": BUCKET_SECTOR, "asset_class": BUCKET_ASSET_CLASS}
    kind = mapping.get(dim)
    if kind is None:
        out["error"] = f"unknown focus dimension {dim!r} (use tag|sector|asset_class|symbol)"
        return out

    key = str(value).lower()
    out["exposure_pct"] = q1(view.bucket_pct(kind, key))
    contributors: list[dict[str, Any]] = []
    for h in view.holdings:
        in_bucket = (
            (kind == BUCKET_TAG and key in h.tags)
            or (kind == BUCKET_SECTOR and h.sector == key)
            or (kind == BUCKET_ASSET_CLASS and h.asset_class is not None and h.asset_class.value == key)
        )
        if in_bucket:
            contributors.append({"symbol": h.symbol, "pct": q1(view.weight_pct(h.symbol))})
    contributors.sort(key=lambda c: (-c["pct"], c["symbol"]))
    out["contributors"] = contributors

    # If the policy defines a limit for this bucket, include its utilization.
    if policy is not None:
        limits_map = {
            BUCKET_TAG: policy.limits.max_tag_pct,
            BUCKET_SECTOR: policy.limits.max_sector_pct,
            BUCKET_ASSET_CLASS: policy.limits.max_asset_class_pct,
        }[kind]
        if key in limits_map:
            status, util = _status(view.bucket_pct(kind, key), limits_map[key],
                                    policy.limits.warn_at_utilization)
            out["limit_pct"] = limits_map[key]
            out["utilization_pct"] = q1(util)
            out["status"] = status

    unclassified = view.unclassified_pct()
    if unclassified > EPSILON:
        out["caveat"] = (
            f"{q1(unclassified)}% of the portfolio is unclassified, so true exposure "
            f"could be higher than shown."
        )
    return out


def analyze_portfolio_risk(
    portfolio: PortfolioInput,
    *,
    analyses: list[str] | None = None,
    focus: dict | None = None,
    policy: Any | dict | None = None,
    policy_path: str | None = None,
    home: str | None = None,
    now: datetime | None = None,
) -> RiskReport:
    now = now or datetime.now(timezone.utc)
    pf = _coerce_portfolio(portfolio)
    view = PortfolioView.from_portfolio(pf)

    wanted = set(analyses) if analyses else {"concentration", "compliance"}
    # A report is read-only and never gates a trade, so an unreadable policy is not
    # fatal here: skip compliance rather than crash (and never echo file contents).
    try:
        pol, pol_meta = resolve_policy(policy, policy_path, home)
        policy_unreadable = False
    except PolicyLoadError:
        pol, pol_meta = None, {"source": "error", "path": None, "revision": None}
        policy_unreadable = True

    report = RiskReport()
    report.engine = {
        "agentrisk_version": __version__,
        "classification_data_version": data_version(),
    }
    report.limitations = list(V1_LIMITATIONS)

    # --- totals (always) --------------------------------------------------- #
    report.totals = {
        "value": q2(view.total),
        "cash": q2(view.cash),
        "cash_pct": q1(view.cash_pct()),
        "position_count": len(view.holdings),
        "as_of": pf.as_of.isoformat(),
    }

    # --- concentration ----------------------------------------------------- #
    if "concentration" in wanted:
        report.positions_by_weight = rounded_positions(view)
        by_asset_class = rounded_buckets(view, BUCKET_ASSET_CLASS)
        if view.cash > EPSILON:
            # Cash isn't a holding, but showing it here makes the breakdown sum to ~100%.
            by_asset_class["cash"] = q1(view.cash_pct())
            by_asset_class = dict(sorted(by_asset_class.items(), key=lambda kv: (-kv[1], kv[0])))
        report.breakdowns = {
            "by_sector": rounded_buckets(view, BUCKET_SECTOR),
            "by_asset_class": by_asset_class,
            "by_tag": rounded_buckets(view, BUCKET_TAG),
            "note": "tag percentages may overlap (a position can carry several tags).",
        }
        hhi = view.hhi()
        report.concentration = {
            "hhi": q4(hhi),
            "band": hhi_band(hhi),
            "bands_doc": HHI_BANDS_DOC,
        }
        report.top_risks = _top_risks(view)

    # --- compliance -------------------------------------------------------- #
    if "compliance" in wanted:
        if pol is not None:
            report.compliance = {
                "policy": {"path": pol_meta["path"], "revision": pol_meta["revision"],
                           "source": pol_meta["source"]},
                "results": _evaluate_compliance(view, pol),
            }
        else:
            note = (
                "A policy file was found but could not be read, so no compliance "
                "audit was performed."
                if policy_unreadable
                else "No policy found, so no compliance audit was performed."
            )
            report.compliance = {"policy": None, "results": [], "note": note}

    # --- focus spotlight --------------------------------------------------- #
    if focus:
        report.focus = _build_focus(view, focus, pol)

    # --- data quality ------------------------------------------------------ #
    age_hours = (now - pf.as_of).total_seconds() / 3600
    warnings: list[str] = []
    if pol is not None and age_hours > pol.data_rules.max_snapshot_age_hours:
        warnings.append(f"snapshot is {age_hours:.0f} hours old")
    report.data_quality = {
        "unclassified_pct": q1(view.unclassified_pct()),
        "unclassified_symbols": view.unclassified_symbols(),
        "snapshot_age_hours": q1(Decimal(str(age_hours))),
        "warnings": warnings,
    }
    return report


def _top_risks(view: PortfolioView) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    positions = rounded_positions(view)
    if positions:
        top = positions[0]
        risks.append({"kind": "single_position", "subject": top["symbol"], "pct": top["pct"],
                      "note": "Largest single position."})
    sectors = rounded_buckets(view, BUCKET_SECTOR)
    sectors = {k: v for k, v in sectors.items() if k != "unclassified"}
    if sectors:
        k = next(iter(sectors))
        risks.append({"kind": "sector", "subject": k, "pct": sectors[k],
                      "note": "Largest sector exposure."})
    tags = rounded_buckets(view, BUCKET_TAG)
    if tags:
        k = next(iter(tags))
        risks.append({"kind": "tag", "subject": k, "pct": tags[k],
                      "note": "Largest theme exposure."})
    return risks
