"""analyze_portfolio_risk: report structure, breakdowns, focus, compliance."""

from __future__ import annotations

from agentrisk import analyze_portfolio_risk


def test_totals_and_positions(portfolio, now):
    r = analyze_portfolio_risk(portfolio, now=now)
    assert r.totals["value"] == 84000.0
    assert r.totals["position_count"] == 9
    assert r.totals["cash_pct"] == 9.5
    # Positions sorted by weight, NVDA first at 28.6%.
    assert r.positions_by_weight[0]["symbol"] == "NVDA"
    assert r.positions_by_weight[0]["pct"] == 28.6


def test_breakdowns(portfolio, now):
    r = analyze_portfolio_risk(portfolio, now=now)
    assert r.breakdowns["by_sector"]["technology"] == 50.0
    assert r.breakdowns["by_asset_class"]["crypto"] == 7.1
    assert r.breakdowns["by_asset_class"]["cash"] == 9.5
    assert r.breakdowns["by_tag"]["ai"] == 47.6  # NVDA + MSFT + AMZN


def test_concentration_band(portfolio, now):
    r = analyze_portfolio_risk(portfolio, now=now)
    assert r.concentration["band"] == "moderate"
    assert 0.10 <= r.concentration["hhi"] <= 0.18


def test_data_quality_reports_unclassified(portfolio, now):
    r = analyze_portfolio_risk(portfolio, now=now)
    # ACME (3,000 / 84,000 = 3.6%) is unclassified and must be surfaced honestly.
    assert "ACME" in r.data_quality["unclassified_symbols"]
    assert r.data_quality["unclassified_pct"] == 3.6


def test_focus_tag_ai(portfolio, policy, now):
    r = analyze_portfolio_risk(portfolio, focus={"tag": "ai"}, policy=policy, now=now)
    assert r.focus["exposure_pct"] == 47.6
    symbols = [c["symbol"] for c in r.focus["contributors"]]
    assert symbols == ["NVDA", "MSFT", "AMZN"]  # sorted by weight
    assert r.focus["status"] == "near_limit"  # 47.6% vs 50% cap (95% utilization)
    assert "caveat" in r.focus  # unclassified holdings present


def test_compliance_audit(portfolio, policy, now):
    r = analyze_portfolio_risk(portfolio, policy=policy, now=now)
    results = {x["rule"]: x for x in r.compliance["results"]}
    assert results["limits.max_single_position_pct"]["status"] == "breached"
    assert results["limits.max_single_position_pct"]["subject"] == "NVDA"
    assert results["limits.max_tag_pct.ai"]["status"] == "near_limit"
    # crypto is held (7.1%) but policy blocks new crypto -> reported as a conflict.
    assert results["asset_rules.crypto"]["status"] == "breached"


def test_limitations_stated(portfolio, now):
    r = analyze_portfolio_risk(portfolio, now=now)
    assert any("look-through" in x for x in r.limitations)
    assert any("Stress scenarios" in x for x in r.limitations)


def test_analyze_is_read_only(portfolio, now, tmp_path):
    # Analysis must never create the .agentrisk directory or any file.
    home = tmp_path / ".agentrisk"
    analyze_portfolio_risk(portfolio, home=str(home), now=now)
    assert not home.exists()
