"""Reference integration: propose -> check -> GATE -> (mock) execute.

This is the pattern every AgentRisk integration should follow. The critical line
is the gate: execution is called only when ``verdict.proceed`` is true, and WARN
acknowledgements are surfaced before proceeding. AgentRisk returns advice; the
integrator is what makes it a guardrail.

Run it:  python examples/agent_loop.py
It uses a temporary policy directory, so it won't touch your real .agentrisk/.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agentrisk import check_trade_risk, generate_risk_policy

HERE = Path(__file__).parent
PORTFOLIO = json.loads((HERE / "sample_portfolio.json").read_text())


def execute(trade: dict) -> str:
    """Stand-in for a real broker call. In production this places the order."""
    return f"[MOCK EXECUTED] {trade['action']} {trade['quantity']} {trade['symbol']}"


def confirm_with_user(_warnings: list[str]) -> bool:
    """Stand-in for a real confirmation prompt. Here we simply accept warnings."""
    return True


def run_trade(portfolio: dict, trade: dict, policy_path: str) -> None:
    verdict = check_trade_risk(portfolio, trade, policy_path=policy_path)

    print(f"\n>>> Proposed: {trade['action']} {trade['quantity']} {trade['symbol']}")
    print(f"    Verdict: {verdict.verdict}  (proceed={verdict.proceed})")
    print(f"    {verdict.summary}")

    # --- THE GATE ---------------------------------------------------------- #
    if not verdict.proceed:
        print("    -> Execution refused.")
        return
    if verdict.acknowledgements_required:
        print("    Warnings to acknowledge:")
        for w in verdict.acknowledgements_required:
            print(f"      - {w}")
        if not confirm_with_user(verdict.acknowledgements_required):
            print("    -> User declined; execution skipped.")
            return
    print("    ->", execute(trade))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = str(Path(tmp) / ".agentrisk")

        # 1. Create a policy (in a real app the agent translates the user's words).
        generate_risk_policy(
            "create", preset="balanced",
            fields={
                "limits": {"max_single_position_pct": 25, "max_sector_pct": {"technology": 50},
                           "max_tag_pct": {"ai": 50}, "max_asset_class_pct": {"crypto": 10}},
                "asset_rules": {"crypto": "block", "options": "warn", "margin": "block"},
                "order_rules": {"max_order_pct_of_portfolio": 10, "min_cash_pct": 5},
                "restricted": {"never_trade": ["GME"]},
            },
            confirm=True, home=home,
        )
        policy_path = str(Path(home) / "policy.yaml")
        print(f"Policy written to {policy_path}")

        # 2. Run a batch of proposed trades through the gate.
        trades = [
            {"action": "buy", "symbol": "JNJ", "quantity": 10, "order_type": "market",
             "estimated_price": 150},                                            # PASS
            {"action": "buy", "symbol": "NVDA", "quantity": 20, "order_type": "market",
             "estimated_price": 120},                                            # BLOCK (concentration)
            {"action": "buy", "symbol": "BTC", "quantity": 0.05, "order_type": "market",
             "estimated_price": 60000, "asset_class": "crypto"},                 # BLOCK (crypto)
            {"action": "buy", "symbol": "NVDA260918C00200000", "quantity": 2,
             "order_type": "market", "estimated_price": 8.40, "asset_class": "option",
             "option": {"underlying": "NVDA", "type": "call", "strike": 200,
                        "expiry": "2026-09-18"}},                                # WARN (options)
            {"action": "sell", "symbol": "NVDA", "quantity": 60, "order_type": "market",
             "estimated_price": 120},                                            # PASS (reduces breach)
        ]
        for trade in trades:
            run_trade(PORTFOLIO, trade, policy_path)


if __name__ == "__main__":
    main()
