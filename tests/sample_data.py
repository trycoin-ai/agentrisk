"""Shared sample data for tests (importable by both conftest and property tests)."""

from __future__ import annotations

from datetime import datetime, timezone

NOW = datetime(2026, 7, 1, 15, 30, 0, tzinfo=timezone.utc)

# Total value = 84,000 (76,000 positions + 8,000 cash). NVDA = 24,000 = 28.571%.
SAMPLE_PORTFOLIO = {
    "as_of": "2026-07-01T15:30:00Z",
    "base_currency": "USD",
    "cash": 8000,
    "positions": [
        {"symbol": "NVDA", "quantity": 200, "price": 120},   # 24,000  tech, ai, semis
        {"symbol": "MSFT", "quantity": 25, "price": 400},    # 10,000  tech, ai
        {"symbol": "SPY", "quantity": 16, "price": 500},     #  8,000  etf
        {"symbol": "AAPL", "quantity": 40, "price": 200},    #  8,000  tech
        {"symbol": "AMZN", "quantity": 40, "price": 150},    #  6,000  cons-disc, ai
        {"symbol": "BTC", "quantity": 0.1, "price": 60000},  #  6,000  crypto
        {"symbol": "JNJ", "quantity": 40, "price": 150},     #  6,000  healthcare
        {"symbol": "XOM", "quantity": 50, "price": 100},     #  5,000  energy
        {"symbol": "ACME", "quantity": 100, "price": 30},    #  3,000  UNCLASSIFIED
    ],
}

POLICY = {
    "schema_version": 1,
    "revision": 3,
    "preset": "balanced",
    "created_at": "2026-07-01",
    "updated_at": "2026-07-01",
    "notes": "test policy",
    "limits": {
        "max_single_position_pct": 25,
        "max_sector_pct": {"technology": 50},
        "max_tag_pct": {"ai": 50},
        "max_asset_class_pct": {"crypto": 10},
        "warn_at_utilization": 80,
    },
    "asset_rules": {"crypto": "block", "options": "warn", "margin": "block"},
    "order_rules": {"max_order_pct_of_portfolio": 10, "max_order_value": 25000, "min_cash_pct": 5},
    "restricted": {"never_trade": ["GME"], "warn_list": []},
    "data_rules": {"max_snapshot_age_hours": 24},
}
