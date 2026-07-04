"""Lint for the shipped Agent Skill and Claude Code plugin files.

Structural checks only: the skill stays thin, the manifests stay valid, and the
plugin version stays in step with the package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agentrisk" / "SKILL.md"
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
MCP_CONFIG = ROOT / ".mcp.json"


def _frontmatter_and_body(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


def _package_version() -> str:
    # no tomllib on 3.10, a regex will do
    match = re.search(r'(?m)^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text("utf-8"))
    assert match
    return match.group(1)


def test_skill_frontmatter():
    meta, _ = _frontmatter_and_body(SKILL.read_text("utf-8"))
    assert meta.get("name") == "agentrisk"
    description = meta.get("description", "")
    assert re.search(r"trade|order", description, re.IGNORECASE), "description must say when to trigger"


def test_skill_body_is_thin_and_complete():
    text = SKILL.read_text("utf-8")
    _, body = _frontmatter_and_body(text)
    for needed in ("PASS", "WARN", "BLOCK", "check_trade_risk"):
        assert needed in body, f"skill must mention {needed}"
    assert len(text.splitlines()) < 120, "keep the skill a thin protocol"


def test_shipped_files_are_ascii():
    for path in (SKILL, PLUGIN, MARKETPLACE, MCP_CONFIG):
        assert path.read_bytes().isascii(), f"{path.name}: non-ASCII characters"


def test_plugin_version_matches_package():
    plugin = json.loads(PLUGIN.read_text("utf-8"))
    assert plugin["name"] == "agentrisk"
    assert plugin["version"] == _package_version()


def test_marketplace_lists_the_plugin():
    market = json.loads(MARKETPLACE.read_text("utf-8"))
    assert market["name"] == "agentrisk"
    assert any(p["name"] == "agentrisk" for p in market["plugins"])


def test_mcp_server_runs_via_uvx():
    server = json.loads(MCP_CONFIG.read_text("utf-8"))["mcpServers"]["agentrisk"]
    assert server["command"] == "uvx"
    # The server resolves from the published PyPI package, whose name this project
    # owns, so a package index cannot satisfy it with someone else's artifact.
    from_spec = server["args"][server["args"].index("--from") + 1]
    assert from_spec == "agentrisk[mcp]", from_spec
