"""Schema validation: malformed input is rejected with clear, specific errors."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentrisk.models import Portfolio, Position, Trade


def test_symbol_uppercased_and_value_exact():
    p = Position(symbol="nvda", quantity="40", price="172.50")
    assert p.symbol == "NVDA"
    # str-based Decimal coercion keeps money exact (no float artifacts).
    assert p.market_value == Decimal("6900.00")


def test_negative_quantity_rejected_as_short():
    with pytest.raises(ValidationError, match="short positions"):
        Position(symbol="NVDA", quantity=-1, price=100)


def test_option_requires_detail():
    with pytest.raises(ValidationError, match="no option detail"):
        Position(symbol="NVDA", quantity=1, price=1, asset_class="option")


def test_option_multiplier_applied_to_value():
    pos = Position(
        symbol="NVDA260918C00200000",
        quantity=2,
        price="8.40",
        asset_class="option",
        option={"underlying": "NVDA", "type": "call", "strike": 200, "expiry": "2026-09-18"},
    )
    assert pos.market_value == Decimal("1680.00")  # 2 * 8.40 * 100


def test_non_usd_currency_rejected():
    with pytest.raises(ValidationError, match="USD only"):
        Portfolio(as_of="2026-07-01T00:00:00Z", base_currency="EUR")


def test_duplicate_symbols_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        Portfolio(
            as_of="2026-07-01T00:00:00Z",
            positions=[
                {"symbol": "NVDA", "quantity": 1, "price": 1},
                {"symbol": "NVDA", "quantity": 2, "price": 1},
            ],
        )


def test_total_value_mismatch_flagged():
    with pytest.raises(ValidationError, match="invalid_snapshot"):
        Portfolio(
            as_of="2026-07-01T00:00:00Z",
            cash=0,
            positions=[{"symbol": "NVDA", "quantity": 10, "price": 100}],  # computes to 1000
            total_value=5000,
        )


def test_unknown_policy_field_is_error_not_ignored():
    from agentrisk.models import Policy

    with pytest.raises(ValidationError):
        Policy(limits={"max_single_positon_pct": 25})  # typo must not silently vanish


def test_limit_order_requires_limit_price():
    with pytest.raises(ValidationError, match="limit_price"):
        Trade(action="buy", symbol="NVDA", quantity=1, order_type="limit")


def test_market_order_requires_estimated_price():
    with pytest.raises(ValidationError, match="estimated_price"):
        Trade(action="buy", symbol="NVDA", quantity=1, order_type="market")


def test_trade_order_value():
    t = Trade(action="buy", symbol="NVDA", quantity=20, order_type="market", estimated_price="120")
    assert t.order_value == Decimal("2400")
