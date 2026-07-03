"""Seed-data lint: bundled classifications must be internally consistent."""

from __future__ import annotations

import json
from importlib import resources

from agentrisk.models import AssetClass

VALID_ASSET_CLASSES = {ac.value for ac in AssetClass}


def _load(name: str) -> dict:
    return json.loads(resources.files("agentrisk.data").joinpath(name).read_text("utf-8"))


def test_taxonomy_wellformed():
    tax = _load("taxonomy.json")
    assert tax["sectors"], "taxonomy must define sectors"
    assert tax["tags"], "taxonomy must define tags"
    assert len(set(tax["sectors"])) == len(tax["sectors"]), "duplicate sectors"


def test_classifications_reference_valid_taxonomy():
    tax = _load("taxonomy.json")
    seed = _load("classifications.json")
    sectors = set(tax["sectors"])
    tags = set(tax["tags"])

    assert seed.get("version"), "dataset must carry a version"
    assert seed.get("source"), "dataset must carry provenance"

    for symbol, entry in seed["instruments"].items():
        assert symbol == symbol.upper(), f"{symbol} must be upper-cased"
        assert entry["asset_class"] in VALID_ASSET_CLASSES, f"{symbol}: bad asset_class"
        sector = entry.get("sector")
        assert sector is None or sector in sectors, f"{symbol}: sector {sector!r} not in taxonomy"
        for tag in entry.get("tags", []):
            assert tag in tags, f"{symbol}: tag {tag!r} not in taxonomy"
        assert entry.get("source"), f"{symbol}: missing provenance 'source'"


def test_key_example_symbols_present():
    seed = _load("classifications.json")["instruments"]
    for sym in ("NVDA", "BTC", "SPY", "GME"):
        assert sym in seed, f"{sym} should be in the seed dataset (used in docs/examples)"


def test_dataset_is_broad():
    # The bundled dataset covers the US-listed universe so a real ticker is rarely
    # fully unknown. If this drops, re-run scripts/expand_seed.py.
    seed = _load("classifications.json")["instruments"]
    assert len(seed) > 5000, "expected broad coverage; run scripts/expand_seed.py"


def test_curated_overlay_wins_over_broad_base():
    # Hand-curated sector/tags must survive a dataset expansion.
    nvda = _load("classifications.json")["instruments"]["NVDA"]
    assert nvda["sector"] == "technology"
    assert "ai" in nvda["tags"]
    assert nvda["source"] == "curated"
