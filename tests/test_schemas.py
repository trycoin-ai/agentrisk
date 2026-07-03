"""The checked-in JSON Schemas must match the current models.

schemas/*.json is a public artifact (editor tooling, docs). If a model changes
but the exported schema is not regenerated, the two drift apart silently. This
test fails when that happens and points at the fix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from export_schemas import MODELS, OUT  # noqa: E402


@pytest.mark.parametrize("name", sorted(MODELS))
def test_exported_schema_is_current(name: str) -> None:
    path = OUT / f"{name}.schema.json"
    assert path.exists(), f"missing {path}; run scripts/export_schemas.py"
    on_disk = json.loads(path.read_text("utf-8"))
    fresh = MODELS[name].model_json_schema()
    assert on_disk == fresh, (
        f"schemas/{name}.schema.json is stale. Regenerate it with:\n"
        f"    python scripts/export_schemas.py"
    )


def test_every_model_has_a_schema_file() -> None:
    exported = {p.name.removesuffix(".schema.json") for p in OUT.glob("*.schema.json")}
    assert set(MODELS) <= exported, "a model in export_schemas.py has no schema file"
