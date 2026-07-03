"""Tests for the `agentrisk` command-line interface."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agentrisk.cli import main


@pytest.fixture
def pf_file(tmp_path):
    # Nothing pre-breaches the 25% cap, so PASS/BLOCK are unambiguous.
    # The CLI evaluates staleness against wall-clock now, so stamp the snapshot a
    # few hours ago to keep it fresh whenever the suite runs (a fixed date would
    # eventually age past the 24h default and turn PASS into WARN).
    p = tmp_path / "pf.json"
    p.write_text(json.dumps({
        "as_of": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "cash": 15000,
        "positions": [
            {"symbol": "NVDA", "quantity": 50, "price": 120},   # 6,000 (20%)
            {"symbol": "MSFT", "quantity": 10, "price": 300},   # 3,000 (10%)
            {"symbol": "AAPL", "quantity": 15, "price": 200},   # 3,000 (10%)
            {"symbol": "JNJ", "quantity": 20, "price": 150},    # 3,000 (10%)
        ],  # total 30,000; nothing near the 25% cap
    }))
    return str(p)


@pytest.fixture
def policy_file(tmp_path):
    return str(tmp_path / ".agentrisk" / "policy.yaml")


def _init(policy_file, *extra):
    return main(["policy", "init", "--max-position", "25", "--policy", policy_file, *extra])


def test_policy_init_and_show(policy_file, capsys):
    assert _init(policy_file, "--block", "crypto", "--warn", "options") == 0
    out = capsys.readouterr().out
    assert "Policy written" in out
    assert "single position: 25%" in out
    assert "Crypto trades: block." in out

    assert main(["policy", "show", "--policy", policy_file]) == 0
    assert "revision 1" in capsys.readouterr().out


def test_policy_init_refuses_overwrite(policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    assert _init(policy_file) == 2  # already exists
    assert "already exists" in capsys.readouterr().err
    assert _init(policy_file, "--force") == 0  # force overwrites


def test_check_block_exits_nonzero(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["check", "buy", "20", "NVDA", "--at", "120", "--portfolio", pf_file, "--policy", policy_file])
    out = capsys.readouterr().out
    assert rc == 1
    assert "BLOCK" in out and "NVDA" in out


def test_check_pass_exits_zero(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["check", "buy", "2", "JNJ", "--at", "150", "--portfolio", pf_file, "--policy", policy_file])
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_check_override(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["check", "buy", "20", "NVDA", "--at", "120", "--portfolio", pf_file,
               "--policy", policy_file, "--override", "max_single_position"])
    assert rc == 0
    assert "OVERRIDDEN" in capsys.readouterr().out


def test_check_requires_a_price(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["check", "buy", "20", "NVDA", "--portfolio", pf_file, "--policy", policy_file])
    assert rc == 2
    assert "--at" in capsys.readouterr().err


def test_check_no_policy_fails_closed(pf_file, tmp_path, capsys):
    rc = main(["check", "buy", "1", "JNJ", "--at", "150", "--portfolio", pf_file,
               "--policy", str(tmp_path / "missing.yaml")])
    assert rc == 1
    assert "BLOCK" in capsys.readouterr().out


def test_analyze(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["analyze", pf_file, "--focus", "tag:ai", "--policy", policy_file])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Top positions" in out and "NVDA" in out and "Focus" in out


def test_check_json_output(pf_file, policy_file, capsys):
    _init(policy_file)
    capsys.readouterr()
    rc = main(["check", "buy", "20", "NVDA", "--at", "120", "--portfolio", pf_file,
               "--policy", policy_file, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["verdict"] == "BLOCK" and payload["proceed"] is False
