"""check_trade_risk behavior: PASS / WARN / BLOCK, breach semantics, fail-closed."""

from __future__ import annotations

from agentrisk import check_trade_risk


def _check(portfolio, trade, policy, now):
    return check_trade_risk(portfolio, trade, policy=policy, now=now, audit=False)


def _by_id(verdict, cid):
    return next((c for c in verdict.checks if c.id == cid), None)


# --- BLOCK: the canonical concentration example -------------------------------- #


def test_block_single_name_concentration(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "NVDA", "quantity": 20,
             "order_type": "market", "estimated_price": 120}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    assert v.proceed is False
    sp = _by_id(v, "max_single_position")
    assert sp.status.value == "block"
    assert sp.details["pre_trade_pct"] == 28.6
    assert sp.details["post_trade_pct"] == 31.4
    # Headline is the single-name limit, and the message names the number and the rule.
    assert v.summary.startswith("Blocked by AgentRisk:")
    assert "31.4%" in v.summary and "25%" in v.summary and "NVDA" in v.summary


# --- PASS ---------------------------------------------------------------------- #


def test_pass_normal_buy(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 10,
             "order_type": "market", "estimated_price": 150}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "PASS"
    assert v.proceed is True
    assert v.summary.startswith("Risk check passed.")
    assert "JNJ" in v.summary and "25%" in v.summary


# --- WARN ---------------------------------------------------------------------- #


def test_warn_on_options(portfolio, policy, now):
    trade = {
        "action": "buy", "symbol": "NVDA260918C00200000", "quantity": 2,
        "order_type": "market", "estimated_price": 8.40, "asset_class": "option",
        "option": {"underlying": "NVDA", "type": "call", "strike": 200, "expiry": "2026-09-18"},
    }
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "WARN"
    assert v.proceed is True
    assert len(v.acknowledgements_required) == 1
    assert "warned before options" in v.summary


# --- BLOCK by asset rule (crypto) --------------------------------------------- #


def test_block_crypto_asset_rule(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "BTC", "quantity": 0.05,
             "order_type": "market", "estimated_price": 60000, "asset_class": "crypto"}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    # asset_rule (priority 3) is the headline over the asset-class cap (priority 5).
    assert "blocks new crypto exposure" in v.summary
    assert _by_id(v, "asset_rule:crypto").status.value == "block"


def test_block_margin(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "AAPL", "quantity": 1, "order_type": "market",
             "estimated_price": 200, "uses_margin": True}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    assert "blocks leverage" in v.summary


def test_block_never_trade_list(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "GME", "quantity": 1, "order_type": "market",
             "estimated_price": 30}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    assert "never-trade list" in v.summary


def test_block_oversized_order(portfolio, policy, now):
    # 400 shares of AAPL at 200 = 80,000 = 95% of an 84,000 portfolio (cap 10%).
    trade = {"action": "buy", "symbol": "AAPL", "quantity": 400, "order_type": "market",
             "estimated_price": 200, "uses_margin": True}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    assert _by_id(v, "max_order_size").status.value == "block"


# --- Pre-existing breach semantics (D12) -------------------------------------- #


def test_reducing_trade_on_breach_passes(portfolio, policy, now):
    # NVDA is already 28.6% (over the 25% cap). Selling it should NOT be blocked.
    trade = {"action": "sell", "symbol": "NVDA", "quantity": 20,
             "order_type": "market", "estimated_price": 120}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "PASS"
    assert v.proceed is True
    sp = _by_id(v, "max_single_position")
    assert sp.status.value == "pass"
    assert sp.details.get("reducing") is True


def test_sell_brings_position_back_under_limit(portfolio, policy, now):
    trade = {"action": "sell", "symbol": "NVDA", "quantity": 60,
             "order_type": "market", "estimated_price": 120}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "PASS"
    assert "bringing it back under your 25% limit" in v.summary


def test_sell_blocked_crypto_still_allowed(portfolio, policy, now):
    # Policy blocks new crypto, but exiting existing crypto is never trapped.
    trade = {"action": "sell", "symbol": "BTC", "quantity": 0.05,
             "order_type": "market", "estimated_price": 60000, "asset_class": "crypto"}
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "PASS"


# --- Fail closed --------------------------------------------------------------- #


def test_no_policy_fails_closed(portfolio, now, tmp_path):
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 1, "order_type": "market",
             "estimated_price": 150}
    v = check_trade_risk(portfolio, trade, home=str(tmp_path / "nope"), now=now, audit=False)
    assert v.verdict == "BLOCK"
    assert v.proceed is False
    assert "no risk policy" in v.summary.lower()


def test_invalid_snapshot_fails_closed(policy, now):
    bad = {"as_of": "2026-07-01T15:30:00Z", "positions": [{"symbol": "X", "quantity": -5, "price": 1}]}
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 1, "order_type": "market",
             "estimated_price": 150}
    v = check_trade_risk(bad, trade, policy=policy, now=now, audit=False)
    assert v.verdict == "BLOCK"
    assert _by_id(v, "invalid_snapshot") is not None


def test_insufficient_cash_blocks(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 1000, "order_type": "market",
             "estimated_price": 150}  # 150,000 far exceeds 8,000 cash, no margin
    v = _check(portfolio, trade, policy, now)
    assert v.verdict == "BLOCK"
    assert _by_id(v, "insufficient_cash") is not None


# --- Staleness ----------------------------------------------------------------- #


def test_stale_snapshot_warns(portfolio, policy, now):
    from datetime import timedelta

    later = now + timedelta(hours=30)
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 5, "order_type": "market",
             "estimated_price": 150}
    v = check_trade_risk(portfolio, trade, policy=policy, now=later, audit=False)
    assert v.verdict == "WARN"
    assert any("hours old" in a for a in v.acknowledgements_required)


# --- Determinism --------------------------------------------------------------- #


def test_verdict_is_deterministic(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "NVDA", "quantity": 20, "order_type": "market",
             "estimated_price": 120}
    a = _check(portfolio, policy=policy, trade=trade, now=now).model_dump()
    b = _check(portfolio, policy=policy, trade=trade, now=now).model_dump()
    assert a == b
