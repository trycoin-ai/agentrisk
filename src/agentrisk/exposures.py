"""Portfolio exposure math shared by analyze and check.

A PortfolioView is a classified, value-resolved snapshot. Trade simulation
produces another PortfolioView, so the same exposure code evaluates pre- and
post-trade states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .classify import Classification, classify_position
from .models import AssetClass, Portfolio, Position
from .util import q1, q2, q4, ratio_pct

# Bucket "kinds" the limit engine understands.
BUCKET_SECTOR = "sector"
BUCKET_TAG = "tag"
BUCKET_ASSET_CLASS = "asset_class"


@dataclass
class Holding:
    symbol: str
    value: Decimal
    asset_class: AssetClass | None
    sector: str | None
    tags: tuple[str, ...]
    classified: bool
    is_option: bool = False

    @classmethod
    def from_position(cls, pos: Position) -> Holding:
        c: Classification = classify_position(pos)
        return cls(
            symbol=pos.symbol,
            value=pos.market_value,
            asset_class=c.asset_class,
            sector=c.sector,
            tags=c.tags,
            classified=c.classified,
            is_option=pos.option is not None or c.asset_class is AssetClass.option,
        )


@dataclass
class PortfolioView:
    as_of: object  # datetime; kept loose to avoid a circular import surface
    cash: Decimal
    holdings: list[Holding] = field(default_factory=list)

    # -- construction ------------------------------------------------------- #

    @classmethod
    def from_portfolio(cls, pf: Portfolio) -> PortfolioView:
        return cls(
            as_of=pf.as_of,
            cash=pf.cash,
            holdings=[Holding.from_position(p) for p in pf.positions],
        )

    def copy(self) -> PortfolioView:
        return PortfolioView(
            as_of=self.as_of,
            cash=self.cash,
            holdings=[
                Holding(
                    symbol=h.symbol,
                    value=h.value,
                    asset_class=h.asset_class,
                    sector=h.sector,
                    tags=h.tags,
                    classified=h.classified,
                    is_option=h.is_option,
                )
                for h in self.holdings
            ],
        )

    # -- totals ------------------------------------------------------------- #

    @property
    def positions_value(self) -> Decimal:
        return sum((h.value for h in self.holdings), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.cash + self.positions_value

    def _denominator(self) -> Decimal:
        # Total value is the natural denominator. Guard the degenerate all-zero
        # case so weights are finite rather than dividing by zero.
        t = self.total
        return t if t > 0 else self.positions_value

    # -- lookups ------------------------------------------------------------ #

    def find(self, symbol: str) -> Holding | None:
        symbol = symbol.upper()
        for h in self.holdings:
            if h.symbol == symbol:
                return h
        return None

    def symbol_value(self, symbol: str) -> Decimal:
        h = self.find(symbol)
        return h.value if h else Decimal(0)

    def weight_pct(self, symbol: str) -> Decimal:
        return ratio_pct(self.symbol_value(symbol), self._denominator())

    # -- exposures ---------------------------------------------------------- #

    def cash_pct(self) -> Decimal:
        return ratio_pct(self.cash, self._denominator())

    def bucket_value(self, kind: str, key: str) -> Decimal:
        """Total value of holdings in a given sector / tag / asset-class bucket."""
        key = key.lower()
        total = Decimal(0)
        for h in self.holdings:
            if kind == BUCKET_SECTOR and h.sector == key:
                total += h.value
            elif kind == BUCKET_TAG and key in h.tags:
                total += h.value
            elif kind == BUCKET_ASSET_CLASS and h.asset_class is not None and h.asset_class.value == key:
                total += h.value
        return total

    def bucket_pct(self, kind: str, key: str) -> Decimal:
        return ratio_pct(self.bucket_value(kind, key), self._denominator())

    def buckets(self, kind: str) -> dict[str, Decimal]:
        """All non-empty buckets of a kind to percentage, plus an 'unclassified' bucket."""
        raw: dict[str, Decimal] = {}
        unclassified = Decimal(0)
        for h in self.holdings:
            if kind == BUCKET_SECTOR:
                keys = [h.sector] if h.sector else []
            elif kind == BUCKET_TAG:
                keys = list(h.tags)
            elif kind == BUCKET_ASSET_CLASS:
                keys = [h.asset_class.value] if h.asset_class else []
            else:  # pragma: no cover - defensive
                keys = []
            if not keys:
                unclassified += h.value
            for k in keys:
                raw[k] = raw.get(k, Decimal(0)) + h.value
        denom = self._denominator()
        out = {k: ratio_pct(v, denom) for k, v in raw.items()}
        if unclassified > 0:
            out["unclassified"] = ratio_pct(unclassified, denom)
        return out

    # -- data quality ------------------------------------------------------- #

    def unclassified_value(self) -> Decimal:
        return sum((h.value for h in self.holdings if not h.classified), Decimal(0))

    def unclassified_pct(self) -> Decimal:
        return ratio_pct(self.unclassified_value(), self._denominator())

    def unclassified_symbols(self) -> list[str]:
        return sorted(h.symbol for h in self.holdings if not h.classified)

    # -- concentration ------------------------------------------------------ #

    def hhi(self) -> Decimal:
        """Herfindahl-Hirschman index over position weight *fractions* (cash excluded).

        Sum of (value / total)^2 for each position, on a 0-1 scale.
        """
        denom = self._denominator()
        if denom == 0:
            return Decimal(0)
        return sum(((h.value / denom) ** 2 for h in self.holdings), Decimal(0))


# --- concentration band mapping (thresholds documented in the output) --------- #

HHI_MODERATE = Decimal("0.10")
HHI_HIGH = Decimal("0.18")
HHI_BANDS_DOC = "diversified <0.10, moderate 0.10-0.18, highly_concentrated >0.18"


def hhi_band(hhi: Decimal) -> str:
    if hhi > HHI_HIGH:
        return "highly_concentrated"
    if hhi >= HHI_MODERATE:
        return "moderate"
    return "diversified"


def rounded_positions(view: PortfolioView) -> list[dict]:
    """Positions sorted by weight desc (ties broken by symbol) for stable output."""
    denom = view._denominator()
    rows: list[dict[str, Any]] = []
    for h in view.holdings:
        rows.append(
            {
                "symbol": h.symbol,
                "value": q2(h.value),
                "pct": q1(ratio_pct(h.value, denom)),
                "asset_class": h.asset_class.value if h.asset_class else None,
                "sector": h.sector,
                "tags": list(h.tags),
                "classified": h.classified,
            }
        )
    rows.sort(key=lambda r: (-r["pct"], r["symbol"]))
    return rows


def rounded_buckets(view: PortfolioView, kind: str) -> dict[str, float]:
    """Buckets sorted by percentage desc for stable, readable output."""
    items = view.buckets(kind)
    ordered = sorted(items.items(), key=lambda kv: (-kv[1], kv[0]))
    return {k: q1(v) for k, v in ordered}


__all__ = [
    "Holding",
    "PortfolioView",
    "BUCKET_SECTOR",
    "BUCKET_TAG",
    "BUCKET_ASSET_CLASS",
    "HHI_BANDS_DOC",
    "hhi_band",
    "rounded_positions",
    "rounded_buckets",
    "q1",
    "q2",
    "q4",
]
