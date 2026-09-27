"""Startup diagnostics for the MCP server.

The 2.x MCP SDK replaced ``mcp.server.fastmcp`` with ``mcp.server.mcpserver``.
While the extra was declared as an open range, a fresh install resolved the new
SDK and the server exited telling the user to install the extra they already had.
These tests pin the two failure modes apart so the message can never regress to
that again, and pin the supported range to the one the packaging declares.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentrisk import mcp_server

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = pytest.importorskip("tomli", reason="needs tomllib or tomli to read pyproject")

REPO = Path(__file__).resolve().parent.parent


def _block_imports(monkeypatch, blocked: set[str]) -> None:
    """Make importing any module in ``blocked`` raise ImportError.

    A ``None`` entry in ``sys.modules`` makes the import system raise whether or
    not the module was imported earlier in the session, and monkeypatch puts the
    real entry back afterwards.
    """
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)


def test_missing_package_tells_the_user_to_install_the_extra(monkeypatch):
    _block_imports(monkeypatch, {"mcp"})

    with pytest.raises(SystemExit) as excinfo:
        mcp_server.build_server()

    assert "[mcp] extra" in str(excinfo.value)


def test_unsupported_sdk_layout_does_not_claim_the_extra_is_missing(monkeypatch):
    # The package imports, but neither server module the adapter knows about is
    # there. This is what an SDK newer than the ceiling looks like from here.
    _block_imports(monkeypatch, {"mcp.server.mcpserver", "mcp.server.fastmcp"})

    with pytest.raises(SystemExit) as excinfo:
        mcp_server.build_server()

    message = str(excinfo.value)
    assert "mcp.server.mcpserver" in message
    assert "mcp.server.fastmcp" in message
    assert mcp_server.SUPPORTED_MCP in message
    # The old message sent users in a circle; make sure we never say it here.
    assert "[mcp] extra" not in message


def test_incompatible_message_reports_the_installed_version():
    # Reported from package metadata, so the user can see what they actually have.
    assert f"version {mcp_server._installed_mcp_version()}" in (
        mcp_server._incompatible_mcp_message()
    )


def test_supported_range_matches_the_packaging_extra():
    # The message quotes a range; the extra enforces one. They must be the same
    # string, or the advice tells users to install something pip will refuse.
    with (REPO / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    extra = project["optional-dependencies"]["mcp"]
    assert extra == [mcp_server.SUPPORTED_MCP]
    assert mcp_server.SUPPORTED_MCP in project["optional-dependencies"]["dev"]
