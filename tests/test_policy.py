"""Policy lifecycle: create, update (diff + confirm gate), show, history, no-clobber."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentrisk import generate_risk_policy
from agentrisk.models import Policy


def _path(home: str) -> Path:
    return Path(home) / "policy.yaml"


def test_create_proposes_without_writing(home, now):
    r = generate_risk_policy(
        "create", preset="balanced",
        fields={"limits": {"max_single_position_pct": 25},
                "asset_rules": {"options": "warn", "margin": "block"}},
        confirm=False, home=home, now=now,
    )
    assert r.written is False
    assert r.requires_confirmation is True
    assert not _path(home).exists()
    assert r.policy["limits"]["max_single_position_pct"] == 25
    assert any("single position: 25%" in s for s in r.summary)


def test_create_writes_on_confirm(home, now):
    r = generate_risk_policy(
        "create", preset="balanced",
        fields={"limits": {"max_single_position_pct": 25}},
        confirm=True, home=home, now=now,
    )
    assert r.written is True
    assert _path(home).exists()
    assert r.policy["revision"] == 1
    # Round-trips through the strict schema.
    Policy(**{k: v for k, v in r.policy.items()})


def test_create_never_clobbers(home, now):
    generate_risk_policy("create", confirm=True, home=home, now=now)
    with pytest.raises(ValueError, match="already exists"):
        generate_risk_policy("create", confirm=True, home=home, now=now)


def test_update_classifies_tightening_and_loosening(home, now):
    generate_risk_policy("create", preset="balanced",
                         fields={"limits": {"max_single_position_pct": 25}},
                         confirm=True, home=home, now=now)
    r = generate_risk_policy(
        "update",
        changes={"limits": {"max_single_position_pct": 20}, "asset_rules": {"crypto": "block"}},
        confirm=False, home=home, now=now,
    )
    assert r.written is False
    by_field = {e.field: e for e in r.diff}
    # Lowering the cap 25 -> 20 tightens; balanced's crypto 'warn' -> 'block' tightens.
    assert by_field["limits.max_single_position_pct"].classification == "tightening"
    assert by_field["asset_rules.crypto"].classification == "tightening"


def test_update_flags_loosening(home, now):
    generate_risk_policy("create", preset="balanced",
                         fields={"limits": {"max_single_position_pct": 25}},
                         confirm=True, home=home, now=now)
    r = generate_risk_policy(
        "update", changes={"limits": {"max_single_position_pct": 35}},
        confirm=False, home=home, now=now,
    )
    entry = next(e for e in r.diff if e.field == "limits.max_single_position_pct")
    assert entry.classification == "loosening"
    assert "relaxes" in r.message.lower()


def test_update_writes_history_on_confirm(home, now):
    generate_risk_policy("create", preset="balanced", confirm=True, home=home, now=now)
    r = generate_risk_policy("update", changes={"limits": {"max_single_position_pct": 15}},
                             confirm=True, home=home, now=now)
    assert r.written is True
    assert r.policy["revision"] == 2
    assert (Path(home) / "policy_history" / "rev-1.yaml").exists()


def test_update_requires_existing_policy(home, now):
    with pytest.raises(ValueError, match="no policy exists"):
        generate_risk_policy("update", changes={"limits": {"max_single_position_pct": 10}},
                             home=home, now=now)


def test_show_reports_current(home, now):
    generate_risk_policy("create", preset="conservative", confirm=True, home=home, now=now)
    r = generate_risk_policy("show", home=home, now=now)
    assert r.written is False
    assert r.policy["preset"] == "conservative"
    assert r.summary


def test_add_never_trade_is_tightening(home, now):
    generate_risk_policy("create", preset="balanced", confirm=True, home=home, now=now)
    r = generate_risk_policy("update", changes={"restricted": {"never_trade": ["GME"]}},
                             confirm=False, home=home, now=now)
    entry = next(e for e in r.diff if e.field == "restricted.never_trade")
    assert entry.new == "GME"
    assert entry.classification == "tightening"


def test_audit_log_records_policy_events(home, now):
    generate_risk_policy("create", preset="balanced", confirm=True, home=home, now=now)
    generate_risk_policy("update", changes={"limits": {"max_single_position_pct": 15}},
                         confirm=True, home=home, now=now)
    audit = Path(home) / "audit.jsonl"
    assert audit.exists()
    lines = audit.read_text().strip().splitlines()
    assert any("policy_created" in ln for ln in lines)
    assert any("policy_updated" in ln for ln in lines)
