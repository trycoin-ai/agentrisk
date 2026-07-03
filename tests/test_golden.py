"""Golden snapshots: full (portfolio, trade, policy) -> verdict JSON.

Any change to the check math or the message wording shows up as a reviewable diff
in a golden file. Regenerate intentionally with:

    AGENTRISK_REGEN=1 pytest tests/test_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agentrisk import check_trade_risk
from sample_data import NOW, POLICY, SAMPLE_PORTFOLIO

GOLDEN = Path(__file__).parent / "golden"

CASES = {
    "nvda_block": {"action": "buy", "symbol": "NVDA", "quantity": 20,
                   "order_type": "market", "estimated_price": 120},
    "jnj_pass": {"action": "buy", "symbol": "JNJ", "quantity": 10,
                 "order_type": "market", "estimated_price": 150},
    "nvda_sell_reducing": {"action": "sell", "symbol": "NVDA", "quantity": 60,
                           "order_type": "market", "estimated_price": 120},
    "crypto_block": {"action": "buy", "symbol": "BTC", "quantity": 0.05,
                     "order_type": "market", "estimated_price": 60000, "asset_class": "crypto"},
    "options_warn": {
        "action": "buy", "symbol": "NVDA260918C00200000", "quantity": 2,
        "order_type": "market", "estimated_price": 8.40, "asset_class": "option",
        "option": {"underlying": "NVDA", "type": "call", "strike": 200, "expiry": "2026-09-18"},
    },
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_verdict(name):
    verdict = check_trade_risk(
        SAMPLE_PORTFOLIO, CASES[name], policy=POLICY, now=NOW, audit=False
    ).model_dump(mode="json")

    path = GOLDEN / f"{name}.json"
    if os.environ.get("AGENTRISK_REGEN"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")

    assert path.exists(), f"missing golden {path.name}; regenerate with AGENTRISK_REGEN=1"
    assert verdict == json.loads(path.read_text())
