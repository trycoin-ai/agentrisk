"""Property-based invariants (hypothesis) that must hold for any input."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agentrisk import analyze_portfolio_risk, check_trade_risk, generate_risk_policy
from agentrisk.check import simulate
from agentrisk.exposures import PortfolioView
from agentrisk.models import Policy, Portfolio, Trade
from agentrisk.policy import policy_to_dict
from sample_data import NOW, POLICY, SAMPLE_PORTFOLIO

_SYMBOLS = ["NVDA", "MSFT", "AAPL", "JNJ", "XOM", "BTC", "SPY", "ACME", "AMZN", "GME"]
_SEV = {"PASS": 0, "WARN": 1, "BLOCK": 2}


@st.composite
def portfolios(draw):
    n = draw(st.integers(min_value=0, max_value=6))
    syms = draw(st.lists(st.sampled_from(_SYMBOLS), min_size=n, max_size=n, unique=True))
    positions = [
        {"symbol": s,
         "quantity": draw(st.integers(min_value=1, max_value=500)),
         "price": draw(st.integers(min_value=1, max_value=2000))}
        for s in syms
    ]
    cash = draw(st.integers(min_value=0, max_value=50000))
    return {"as_of": "2026-07-01T15:30:00Z", "cash": cash, "positions": positions}


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(pf=portfolios(), sym=st.sampled_from(_SYMBOLS), qty=st.integers(1, 100))
def test_simulate_preserves_total_value(pf, sym, qty):
    """A trade only transfers value between cash and a position (v1 ignores fees)."""
    view = PortfolioView.from_portfolio(Portfolio(**pf))
    trade = Trade(action="buy", symbol=sym, quantity=qty, order_type="market",
                  estimated_price=100, uses_margin=True)
    post, _ = simulate(view, trade)
    assert post.total == view.total  # exact under Decimal arithmetic


@settings(max_examples=100)
@given(pf=portfolios())
def test_asset_class_breakdown_sums_to_100(pf):
    view = PortfolioView.from_portfolio(Portfolio(**pf))
    if view.total <= 0:
        return
    r = analyze_portfolio_risk(pf, now=NOW)
    total = sum(r.breakdowns["by_asset_class"].values())
    assert 99.0 <= total <= 101.0  # rounding tolerance


@settings(max_examples=50)
@given(q_small=st.integers(1, 40), extra=st.integers(1, 60))
def test_larger_buy_never_improves_verdict(q_small, extra):
    """Buying more of a capped name can only keep or worsen the verdict severity."""
    small = check_trade_risk(
        SAMPLE_PORTFOLIO,
        {"action": "buy", "symbol": "NVDA", "quantity": q_small,
         "order_type": "market", "estimated_price": 120, "uses_margin": True},
        policy=POLICY, now=NOW, audit=False,
    )
    big = check_trade_risk(
        SAMPLE_PORTFOLIO,
        {"action": "buy", "symbol": "NVDA", "quantity": q_small + extra,
         "order_type": "market", "estimated_price": 120, "uses_margin": True},
        policy=POLICY, now=NOW, audit=False,
    )
    assert _SEV[big.verdict] >= _SEV[small.verdict]


@settings(max_examples=50)
@given(qty=st.integers(1, 200))
def test_selling_over_limit_position_never_blocks_on_single_name(qty):
    """Exits are never trapped: selling an over-cap name can't be BLOCKed by that cap."""
    v = check_trade_risk(
        SAMPLE_PORTFOLIO,
        {"action": "sell", "symbol": "NVDA", "quantity": qty,
         "order_type": "market", "estimated_price": 120},
        policy=POLICY, now=NOW, audit=False,
    )
    sp = next((c for c in v.checks if c.id == "max_single_position"), None)
    if sp is not None:
        assert sp.status.value != "block"


@settings(max_examples=50, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cap=st.integers(1, 100))
def test_policy_yaml_round_trips(cap, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("policy"))
    r = generate_risk_policy(
        "create", preset="balanced",
        fields={"limits": {"max_single_position_pct": cap}},
        confirm=True, home=home, now=NOW,
    )
    # The written policy, re-parsed, equals the returned policy object.
    from pathlib import Path

    import yaml

    reloaded = Policy(**yaml.safe_load(Path(home, "policy.yaml").read_text()))
    assert policy_to_dict(reloaded) == r.policy


@settings(max_examples=100)
@given(pf=portfolios())
def test_check_is_deterministic(pf):
    args = dict(policy=POLICY, now=NOW, audit=False)
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 1, "order_type": "market",
             "estimated_price": 150}
    a = check_trade_risk(pf, trade, **args).model_dump()
    b = check_trade_risk(pf, trade, **args).model_dump()
    assert a == b
