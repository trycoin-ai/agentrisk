"""One-time override behavior: soft/hard/none tiers and the audit trail."""

from __future__ import annotations

import json

from agentrisk import check_trade_risk, generate_risk_policy
from agentrisk.store import audit_path, resolve_policy_path

NVDA_BUY = {"action": "buy", "symbol": "NVDA", "quantity": 20,
            "order_type": "market", "estimated_price": 120}


def _check(portfolio, trade, policy, now, **kw):
    return check_trade_risk(portfolio, trade, policy=policy, now=now, audit=False, **kw)


def _by_id(v, cid):
    return next((c for c in v.checks if c.id == cid), None)


def test_block_annotates_overridability(portfolio, policy, now):
    v = _check(portfolio, NVDA_BUY, policy, now)
    assert v.verdict == "BLOCK"
    sp = _by_id(v, "max_single_position")
    assert sp.details["overridable"] is True
    assert sp.details["override_tier"] == "soft"
    assert sp.details["override_token"] == "max_single_position"


def test_soft_override_clears_block(portfolio, policy, now):
    # An NVDA buy trips the single-name, sector and tag caps; bypass all three.
    tokens = ["max_single_position", "max_sector:technology", "max_tag:ai"]
    v = _check(portfolio, NVDA_BUY, policy, now, override=tokens)
    assert v.verdict == "OVERRIDDEN"
    assert v.proceed is True
    assert set(v.overrides) == set(tokens)
    assert _by_id(v, "max_single_position").status.value == "overridden"
    assert "one-time bypass" in v.summary
    assert "single-name limit" in v.summary


def test_partial_override_still_blocks(portfolio, policy, now):
    # Bypassing only one of three blocking caps leaves the trade blocked overall.
    v = _check(portfolio, NVDA_BUY, policy, now, override=["max_single_position"])
    assert v.verdict == "BLOCK"
    assert v.proceed is False
    assert "max_single_position" in v.overrides
    assert _by_id(v, "max_single_position").status.value == "overridden"


def test_hard_block_flagged_and_bypassable(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "BTC", "quantity": 0.01,
             "order_type": "market", "estimated_price": 60000, "asset_class": "crypto"}
    v = _check(portfolio, trade, policy, now)
    ar = _by_id(v, "asset_rule:crypto")
    assert ar.status.value == "block"
    assert ar.details["override_tier"] == "hard"
    assert ar.details["override_guidance"] == "prefer_policy_edit"

    v2 = _check(portfolio, trade, policy, now, override=["asset_rule:crypto"])
    assert v2.verdict == "OVERRIDDEN"
    assert v2.proceed is True
    assert "hard block" in v2.summary


def test_never_trade_is_hard(portfolio, policy, now):
    trade = {"action": "buy", "symbol": "GME", "quantity": 1,
             "order_type": "market", "estimated_price": 100}
    v = _check(portfolio, trade, policy, now)
    assert _by_id(v, "restricted").details["override_tier"] == "hard"
    v2 = _check(portfolio, trade, policy, now, override=["restricted"])
    assert v2.verdict == "OVERRIDDEN" and v2.proceed is True


def test_feasibility_block_cannot_be_bypassed(portfolio, policy, now):
    # Buying more than the available cash can never fill, so it must stay blocked.
    trade = {"action": "buy", "symbol": "AAPL", "quantity": 100,
             "order_type": "market", "estimated_price": 200}
    v = _check(portfolio, trade, policy, now, override=["insufficient_cash"])
    assert v.verdict == "BLOCK"
    assert v.proceed is False
    assert "insufficient_cash" in v.override_rejected
    assert _by_id(v, "insufficient_cash").status.value == "block"


def test_override_of_nonblocking_token_is_noop(portfolio, policy, now):
    # JNJ passes cleanly; passing an override changes nothing.
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 10,
             "order_type": "market", "estimated_price": 150}
    v = _check(portfolio, trade, policy, now, override=["max_single_position"])
    assert v.verdict == "PASS"
    assert v.overrides == []


def test_override_writes_distinct_audit_event(portfolio, now, home):
    generate_risk_policy(
        "create", preset="balanced",
        fields={"limits": {"max_single_position_pct": 25,
                           "max_sector_pct": {"technology": 50},
                           "max_tag_pct": {"ai": 50}},
                "asset_rules": {"crypto": "block"}},
        confirm=True, home=home, now=now,
    )
    v = check_trade_risk(
        portfolio, NVDA_BUY, home=home, now=now,
        override=["max_single_position", "max_sector:technology", "max_tag:ai"],
        override_reason="user approved in session",
    )
    assert v.verdict == "OVERRIDDEN"

    records = [json.loads(line) for line in open(audit_path(resolve_policy_path(None, home)))]
    overrides = [r for r in records if r["event"] == "trade_override"]
    assert overrides, "expected a trade_override audit record"
    assert overrides[-1]["override_reason"] == "user approved in session"
    assert "max_single_position" in overrides[-1]["overrides"]
