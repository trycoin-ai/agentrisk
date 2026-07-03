"""Append-only JSONL audit log for verdicts and policy changes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import append_line, audit_path


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def record(
    policy_path: Path,
    event_type: str,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    """Append one audit record. Never raises; returns True if the write succeeded.

    A read-only risk decision stays best-effort (it must not fail on a full disk),
    but a policy mutation checks the return value so an unauditable change can fail
    closed instead of leaving no trail.
    """
    line = json.dumps(
        {"ts": _now(now).isoformat(), "event": event_type, **payload},
        default=str,
        sort_keys=True,
    )
    try:
        append_line(audit_path(policy_path), line)
        return True
    except OSError:
        return False
