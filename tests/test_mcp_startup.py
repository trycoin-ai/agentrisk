"""Startup diagnostics for the MCP server.

The 2.x MCP SDK dropped ``mcp.server.fastmcp``. Because the extra was declared as
an open range, a fresh install resolved the new SDK and the server exited telling
the user to install the extra they already had. These tests pin the two failure
modes apart so the message can never regress to that again.
"""

from __future__ import annotations

import builtins

import pytest

from agentrisk import mcp_server


def _block_imports(monkeypatch, blocked: set[str]) -> None:
    """Make importing any name in `blocked` raise, leaving other imports alone."""
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in blocked:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_missing_package_tells_the_user_to_install_the_extra(monkeypatch):
    _block_imports(monkeypatch, {"mcp"})

    with pytest.raises(SystemExit) as excinfo:
        mcp_server.build_server()

    assert "[mcp] extra" in str(excinfo.value)


def test_unsupported_sdk_layout_does_not_claim_the_extra_is_missing(monkeypatch):
    # The package imports, but the submodule the server is built on is gone. This
    # is what a 2.x SDK looks like from here.
    _block_imports(monkeypatch, {"mcp.server.fastmcp"})

    with pytest.raises(SystemExit) as excinfo:
        mcp_server.build_server()

    message = str(excinfo.value)
    assert "mcp.server.fastmcp" in message
    assert "mcp>=1.2.0,<2" in message
    # The old message sent users in a circle; make sure we never say it here.
    assert "[mcp] extra" not in message


def test_incompatible_message_reports_the_installed_version():
    # Reported from package metadata, so the user can see what they actually have.
    assert f"version {mcp_server._installed_mcp_version()}" in (
        mcp_server._incompatible_mcp_message()
    )
