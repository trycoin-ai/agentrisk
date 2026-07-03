"""Paths and atomic file writes for the .agentrisk state directory.

The home directory resolves as: explicit path > $AGENTRISK_HOME > ./.agentrisk.
Writes are atomic (temp file + rename).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ENV_HOME = "AGENTRISK_HOME"
DEFAULT_DIRNAME = ".agentrisk"
POLICY_FILENAME = "policy.yaml"
HISTORY_DIRNAME = "policy_history"
AUDIT_FILENAME = "audit.jsonl"


def home_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the AgentRisk home directory (does not create it)."""
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    return Path.cwd() / DEFAULT_DIRNAME


def default_policy_path(explicit_home: str | os.PathLike[str] | None = None) -> Path:
    return home_dir(explicit_home) / POLICY_FILENAME


def resolve_policy_path(
    policy_path: str | os.PathLike[str] | None = None,
    home: str | os.PathLike[str] | None = None,
) -> Path:
    """A caller-given ``policy_path`` wins; otherwise use the default location."""
    if policy_path is not None:
        return Path(policy_path).expanduser()
    return default_policy_path(home)


def history_dir(policy_path: Path) -> Path:
    return policy_path.parent / HISTORY_DIRNAME


def audit_path(policy_path: Path) -> Path:
    return policy_path.parent / AUDIT_FILENAME


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in same dir, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_line(path: Path, line: str) -> None:
    """Append a single line (JSONL record) to ``path``, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")
