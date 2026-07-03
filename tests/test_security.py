"""Regression tests for the reported security findings.

Each test pins a guardrail that a caller-controlled input tried to slip past, or
a fail-closed behavior that must hold when state cannot be written.
"""

from __future__ import annotations

import pytest

from agentrisk import check_trade_risk, generate_risk_policy
from agentrisk.models import Trade
from sample_data import NOW, POLICY, SAMPLE_PORTFOLIO


def _by_id(verdict, cid):
    return next((c for c in verdict.checks if c.id == cid), None)


# -- Finding 1: caller asset_class cannot downgrade a curated restricted class -- #


def test_spoofed_asset_class_cannot_bypass_crypto_block():
    # BTC is crypto in the bundled data; labelling it equity must not dodge the block.
    trade = {"action": "buy", "symbol": "BTC", "quantity": 0.05, "order_type": "market",
             "estimated_price": 60000, "asset_class": "equity"}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy=POLICY, now=NOW, audit=False)
    assert v.verdict == "BLOCK"
    assert v.proceed is False
    assert _by_id(v, "invalid_trade") is not None


def test_spoofed_asset_class_block_is_not_overridable():
    trade = {"action": "buy", "symbol": "BTC", "quantity": 0.05, "order_type": "market",
             "estimated_price": 60000, "asset_class": "equity"}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy=POLICY, now=NOW, audit=False,
                         override=["invalid_trade"])
    assert v.verdict == "BLOCK"
    assert v.proceed is False


def test_matching_asset_class_is_still_accepted():
    # Declaring the same class the data already records is not a conflict.
    trade = {"action": "buy", "symbol": "BTC", "quantity": 0.05, "order_type": "market",
             "estimated_price": 60000, "asset_class": "crypto"}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy=POLICY, now=NOW, audit=False)
    assert _by_id(v, "invalid_trade") is None
    assert _by_id(v, "asset_rule:crypto").status.value == "block"


# -- Finding 3: an option trade must carry its option detail -------------------- #


def test_option_trade_without_detail_is_rejected_by_model():
    with pytest.raises(ValueError, match="option"):
        Trade(action="buy", symbol="XYZ", quantity=1, order_type="market",
              estimated_price=8.40, asset_class="option")


def test_option_trade_without_detail_fails_closed():
    trade = {"action": "buy", "symbol": "XYZ", "quantity": 1, "order_type": "market",
             "estimated_price": 8.40, "asset_class": "option"}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy=POLICY, now=NOW, audit=False)
    assert v.verdict == "BLOCK"
    assert _by_id(v, "invalid_trade") is not None


# -- Finding 4a: an unreadable policy fails closed without leaking file bytes --- #


def test_unreadable_policy_fails_closed_without_leaking_contents(tmp_path):
    secret = "S3CRET-TOKEN-a1b2c3"
    bad = tmp_path / "policy.yaml"
    bad.write_text(f"data_rules:\n  max_snapshot_age_hours: \"{secret}\"\n")
    trade = {"action": "buy", "symbol": "JNJ", "quantity": 1, "order_type": "market",
             "estimated_price": 150}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy_path=str(bad), now=NOW, audit=False)
    assert v.verdict == "BLOCK"
    assert _by_id(v, "invalid_policy") is not None
    blob = v.summary + "".join(c.message for c in v.checks)
    assert secret not in blob


# -- Finding 4c: a policy change that cannot be audited fails closed ------------ #


def test_policy_create_fails_closed_when_audit_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr("agentrisk.audit.record", lambda *a, **k: False)
    path = tmp_path / ".agentrisk" / "policy.yaml"
    with pytest.raises(RuntimeError, match="audit"):
        generate_risk_policy("create", preset="balanced", confirm=True,
                             policy_path=str(path), now=NOW)
    assert not path.exists()  # rolled back


# -- Finding 5: a reducing (sell) margin trade is never trapped ----------------- #


def test_margin_sell_reducing_is_not_blocked():
    # NVDA is already held; a margin-flagged sell reduces exposure and must pass the
    # margin rule even though the policy blocks margin.
    trade = {"action": "sell", "symbol": "NVDA", "quantity": 50, "order_type": "market",
             "estimated_price": 120, "uses_margin": True}
    v = check_trade_risk(SAMPLE_PORTFOLIO, trade, policy=POLICY, now=NOW, audit=False)
    margin = _by_id(v, "asset_rule:margin")
    assert margin is not None
    assert margin.status.value != "block"
