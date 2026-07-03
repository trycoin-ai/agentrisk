"""End-to-end smoke test for the MCP server.

Launches the stdio server the way an MCP client would, lists the tools, creates a
policy in a temp directory, and checks trades that should BLOCK, PASS, and be
OVERRIDDEN. Run from a checkout with the mcp extra installed: pip install -e ".[mcp]".
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    sys.exit("This script needs the MCP client SDK. From a checkout, install it "
             'with: pip install -e ".[mcp]"')

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

SAMPLE_PORTFOLIO = {
    # Stamped a couple of hours ago so the snapshot never ages past the policy's
    # staleness window and turns an expected PASS into a WARN.
    "as_of": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    "cash": 8000,
    "positions": [
        {"symbol": "NVDA", "quantity": 200, "price": 120},
        {"symbol": "MSFT", "quantity": 25, "price": 400},
    ],
}


def _payload(result) -> dict:
    """Pull the JSON dict out of a CallToolResult (structured or text content)."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    for block in result.content:
        if getattr(block, "text", None):
            return json.loads(block.text)
    return {}


async def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="agentrisk-smoke-"))
    policy_path = str(workdir / "policy.yaml")

    # Launch via the current interpreter so it works in any venv with agentrisk
    # installed. In production, clients launch the "agentrisk-mcp" command instead.
    params = StdioServerParameters(command=sys.executable, args=["-m", "agentrisk.mcp_server"])

    failures = 0
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Tools present
            tools = {t.name for t in (await session.list_tools()).tools}
            expected = {"analyze_portfolio_risk", "check_trade_risk", "generate_risk_policy"}
            ok = expected <= tools
            print(f"[{PASS if ok else FAIL}] server exposes the three tools: {sorted(tools)}")
            failures += not ok

            # 2. Create a policy
            res = _payload(await session.call_tool("generate_risk_policy", {
                "mode": "create", "preset": "balanced",
                "fields": {"limits": {"max_single_position_pct": 25},
                           "asset_rules": {"crypto": "block", "options": "warn", "margin": "block"}},
                "confirm": True, "policy_path": policy_path,
            }))
            ok = res.get("written") is True
            print(f"[{PASS if ok else FAIL}] generate_risk_policy wrote a policy: {res.get('message')}")
            failures += not ok

            # 3a. A trade that should BLOCK (pushes NVDA over 25%)
            res = _payload(await session.call_tool("check_trade_risk", {
                "portfolio": SAMPLE_PORTFOLIO,
                "trade": {"action": "buy", "symbol": "NVDA", "quantity": 40,
                          "order_type": "market", "estimated_price": 120},
                "policy_path": policy_path,
            }))
            ok = res.get("verdict") == "BLOCK" and res.get("proceed") is False
            print(f"[{PASS if ok else FAIL}] check_trade_risk BLOCKs the over-limit buy")
            print(f"        -> {res.get('summary')}")
            failures += not ok

            # 3b. A trade that should PASS (a small, in-policy sell)
            res = _payload(await session.call_tool("check_trade_risk", {
                "portfolio": SAMPLE_PORTFOLIO,
                "trade": {"action": "sell", "symbol": "NVDA", "quantity": 20,
                          "order_type": "market", "estimated_price": 120},
                "policy_path": policy_path,
            }))
            ok = res.get("verdict") == "PASS" and res.get("proceed") is True
            print(f"[{PASS if ok else FAIL}] check_trade_risk PASSes the in-policy sell")
            print(f"        -> {res.get('summary')}")
            failures += not ok

            # 3c. A buy that trips only the single-name cap, then a one-time bypass.
            res = _payload(await session.call_tool("check_trade_risk", {
                "portfolio": SAMPLE_PORTFOLIO,
                "trade": {"action": "buy", "symbol": "NVDA", "quantity": 30,
                          "order_type": "market", "estimated_price": 120},
                "policy_path": policy_path,
                "override": ["max_single_position"],
                "override_reason": "smoke test: user-approved one-time bypass",
            }))
            ok = (
                res.get("verdict") == "OVERRIDDEN"
                and res.get("proceed") is True
                and "max_single_position" in res.get("overrides", [])
            )
            print(f"[{PASS if ok else FAIL}] check_trade_risk allows a one-time OVERRIDDEN bypass")
            print(f"        -> {res.get('summary')}")
            failures += not ok

    print()
    if failures:
        print(f"{FAIL}: {failures} check(s) failed.")
        return 1
    print(f"{PASS}: MCP server works end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
