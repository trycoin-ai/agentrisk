"""Shared fixtures. A fixed NOW keeps staleness checks deterministic."""

from __future__ import annotations

import copy

import pytest

from sample_data import NOW, POLICY, SAMPLE_PORTFOLIO


@pytest.fixture
def portfolio() -> dict:
    return copy.deepcopy(SAMPLE_PORTFOLIO)


@pytest.fixture
def policy() -> dict:
    return copy.deepcopy(POLICY)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def home(tmp_path):
    """An isolated AgentRisk home directory for file-based policy/audit tests."""
    return str(tmp_path / ".agentrisk")
