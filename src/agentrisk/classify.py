"""Instrument classification.

Resolution order: caller metadata wins, then the bundled seed dataset, otherwise
the instrument is reported as unclassified rather than guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from .models import AssetClass, Position, Trade


@dataclass(frozen=True)
class Classification:
    asset_class: AssetClass | None
    sector: str | None
    tags: tuple[str, ...] = field(default_factory=tuple)
    classified: bool = False  # True if we know *anything* about it
    source: str = "unclassified"  # caller | curated | unclassified


@dataclass(frozen=True)
class SeedData:
    version: str
    instruments: dict[str, dict]


@lru_cache(maxsize=1)
def _load_seed() -> SeedData:
    raw = json.loads(
        resources.files("agentrisk.data").joinpath("classifications.json").read_text("utf-8")
    )
    return SeedData(version=raw.get("version", "unknown"), instruments=raw.get("instruments", {}))


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict:
    return json.loads(
        resources.files("agentrisk.data").joinpath("taxonomy.json").read_text("utf-8")
    )


def data_version() -> str:
    """Version stamp of the bundled classification dataset (embedded in every verdict)."""
    return _load_seed().version


def taxonomy() -> dict:
    return _load_taxonomy()


def _seed_for(symbol: str) -> dict | None:
    return _load_seed().instruments.get(symbol.upper())


def curated_asset_class(symbol: str) -> AssetClass | None:
    """The asset class the bundled seed assigns to ``symbol``, ignoring caller input.

    The risk checks use this so caller-supplied metadata cannot downgrade a known
    restricted instrument (relabelling crypto as equity, say) to dodge a rule.
    """
    seed = _seed_for(symbol)
    if seed and seed.get("asset_class"):
        return AssetClass(seed["asset_class"])
    return None


def _merge(
    caller_ac: AssetClass | None,
    caller_sector: str | None,
    caller_tags: list[str],
    symbol: str,
) -> Classification:
    seed = _seed_for(symbol)

    # Asset class
    if caller_ac is not None:
        asset_class: AssetClass | None = caller_ac
        ac_source = "caller"
    elif seed and seed.get("asset_class"):
        asset_class = AssetClass(seed["asset_class"])
        ac_source = "curated"
    else:
        asset_class = None
        ac_source = "unclassified"

    # Sector
    if caller_sector:
        sector: str | None = caller_sector
    elif seed and seed.get("sector"):
        sector = str(seed["sector"]).lower()
    else:
        sector = None

    # Tags (caller tags, if any, win wholesale over seed tags)
    if caller_tags:
        tags = tuple(caller_tags)
        tag_source = "caller"
    elif seed and seed.get("tags"):
        tags = tuple(str(t).lower() for t in seed["tags"])
        tag_source = "curated"
    else:
        tags = ()
        tag_source = "unclassified"

    classified = asset_class is not None or sector is not None or bool(tags)
    if "caller" in (ac_source, tag_source) or caller_sector:
        source = "caller"
    elif classified:
        source = "curated"
    else:
        source = "unclassified"

    return Classification(
        asset_class=asset_class,
        sector=sector,
        tags=tags,
        classified=classified,
        source=source,
    )


def classify_position(pos: Position) -> Classification:
    return _merge(pos.asset_class, pos.sector, list(pos.tags), pos.symbol)


def classify_trade(trade: Trade) -> Classification:
    # A trade carries less metadata than a position; sector/tags come from seed only.
    return _merge(trade.asset_class, None, [], trade.symbol)
