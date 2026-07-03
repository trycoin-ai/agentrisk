"""Classification precedence: caller > seed > unclassified."""

from __future__ import annotations

from agentrisk.classify import classify_position, data_version
from agentrisk.models import AssetClass, Position


def test_seed_classification():
    c = classify_position(Position(symbol="NVDA", quantity=1, price=1))
    assert c.asset_class is AssetClass.equity
    assert c.sector == "technology"
    assert "ai" in c.tags
    assert c.classified is True
    assert c.source == "curated"


def test_caller_metadata_wins():
    c = classify_position(
        Position(symbol="NVDA", quantity=1, price=1, sector="communication-services",
                 tags=["custom"])
    )
    assert c.sector == "communication-services"
    assert c.tags == ("custom",)
    assert c.source == "caller"


def test_unknown_symbol_is_unclassified():
    c = classify_position(Position(symbol="ZZZZ", quantity=1, price=1))
    assert c.asset_class is None
    assert c.sector is None
    assert c.tags == ()
    assert c.classified is False
    assert c.source == "unclassified"


def test_data_version_present():
    assert data_version()  # non-empty version stamp
