"""MCP contract: the three tools exist with stable names and schemas.

An accidental change to a tool name or its input schema breaks every agent
integration, so we pin them here.
"""

from __future__ import annotations

import asyncio

import pytest

mcp = pytest.importorskip("mcp")


def _tools():
    from agentrisk.mcp_server import build_server

    server = build_server()
    return {t.name: t for t in asyncio.run(server.list_tools())}


def test_three_tools_registered():
    tools = _tools()
    assert set(tools) == {
        "analyze_portfolio_risk",
        "check_trade_risk",
        "generate_risk_policy",
    }


def test_check_trade_risk_schema():
    tool = _tools()["check_trade_risk"]
    props = tool.inputSchema["properties"]
    assert "portfolio" in props and "trade" in props
    assert set(tool.inputSchema.get("required", [])) >= {"portfolio", "trade"}


def test_tools_have_agent_facing_descriptions():
    tools = _tools()
    # The descriptions must teach the NL->structured translation.
    assert "focus" in tools["analyze_portfolio_risk"].description
    assert "proceed" in tools["check_trade_risk"].description
    assert "confirm" in tools["generate_risk_policy"].description
