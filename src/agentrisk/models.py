"""Pydantic models for AgentRisk's inputs and outputs.

Money is Decimal end to end and percentages are on a 0-100 scale. Input models
reject unknown fields so a misspelled rule fails loudly instead of silently not
being enforced.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Shared helpers                                                              #
# --------------------------------------------------------------------------- #


def _to_decimal(value: Any) -> Decimal:
    """Coerce numbers to ``Decimal`` via ``str`` so floats like 172.50 stay exact."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise ValueError("expected a number, got a boolean")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ValueError(f"could not parse number: {value!r}") from exc
    raise ValueError(f"expected a number, got {type(value).__name__}")


# --------------------------------------------------------------------------- #
# Enums                                                                       #
# --------------------------------------------------------------------------- #


class AssetClass(str, Enum):
    equity = "equity"
    etf = "etf"
    crypto = "crypto"
    option = "option"
    cash = "cash"


class OptionType(str, Enum):
    call = "call"
    put = "put"


class TradeAction(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"


class RuleAction(str, Enum):
    allow = "allow"
    warn = "warn"
    block = "block"


class CheckStatus(str, Enum):
    ok = "pass"
    warn = "warn"
    block = "block"
    overridden = "overridden"  # a block the user explicitly bypassed for this one trade
    skipped = "skipped"


# --------------------------------------------------------------------------- #
# Instrument / portfolio inputs                                               #
# --------------------------------------------------------------------------- #


class OptionDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    underlying: str
    type: OptionType
    strike: Decimal
    expiry: str  # ISO date (YYYY-MM-DD); not modelled deeply in v1
    multiplier: int = 100

    @field_validator("underlying")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("strike", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _to_decimal(v)

    @field_validator("multiplier")
    @classmethod
    def _positive_multiplier(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("option multiplier must be positive")
        return v


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: Decimal
    price: Decimal
    asset_class: AssetClass | None = None
    sector: str | None = None
    tags: list[str] = Field(default_factory=list)
    option: OptionDetail | None = None

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must not be empty")
        return v

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _to_decimal(v)

    @field_validator("quantity")
    @classmethod
    def _non_negative_qty(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(
                "negative quantities (short positions) are not supported in v1"
            )
        return v

    @field_validator("price")
    @classmethod
    def _non_negative_price(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("price must not be negative")
        return v

    @field_validator("sector")
    @classmethod
    def _lower_sector(cls, v: str | None) -> str | None:
        return v.strip().lower() if v else v

    @field_validator("tags")
    @classmethod
    def _lower_tags(cls, v: list[str]) -> list[str]:
        # de-duplicate while preserving order, lower-cased
        seen: set[str] = set()
        out: list[str] = []
        for tag in v:
            t = tag.strip().lower()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @model_validator(mode="after")
    def _option_consistency(self) -> Position:
        if self.option is not None and self.asset_class is None:
            object.__setattr__(self, "asset_class", AssetClass.option)
        if self.asset_class is AssetClass.option and self.option is None:
            raise ValueError(
                f"position {self.symbol!r} is asset_class 'option' but has no option detail"
            )
        return self

    @property
    def multiplier(self) -> Decimal:
        return Decimal(self.option.multiplier) if self.option else Decimal(1)

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.price * self.multiplier


class Portfolio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    base_currency: str = "USD"
    cash: Decimal = Decimal(0)
    positions: list[Position] = Field(default_factory=list)
    total_value: Decimal | None = None  # optional caller cross-check

    @field_validator("base_currency")
    @classmethod
    def _usd_only(cls, v: str) -> str:
        v = v.strip().upper()
        if v != "USD":
            raise ValueError(f"base_currency {v!r} not supported in v1 (USD only)")
        return v

    @field_validator("as_of")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        # Treat naive timestamps as UTC rather than rejecting them.
        return v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)

    @field_validator("cash", "total_value", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Any:
        return None if v is None else _to_decimal(v)

    @field_validator("cash")
    @classmethod
    def _non_negative_cash(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("cash must not be negative")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Portfolio:
        symbols = [p.symbol for p in self.positions]
        dupes = {s for s in symbols if symbols.count(s) > 1}
        if dupes:
            raise ValueError(
                f"duplicate position symbols: {sorted(dupes)} (aggregate them first)"
            )
        if self.total_value is not None:
            computed = self.total
            if computed > 0:
                drift = abs(computed - self.total_value) / computed
                if drift > Decimal("0.01"):
                    raise ValueError(
                        "invalid_snapshot: provided total_value "
                        f"{self.total_value} differs from computed {computed} by "
                        f"{drift * 100:.1f}% (>1%)"
                    )
        return self

    @property
    def positions_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.cash + self.positions_value


# --------------------------------------------------------------------------- #
# Trade proposal                                                              #
# --------------------------------------------------------------------------- #


class Trade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: TradeAction
    symbol: str
    quantity: Decimal
    order_type: OrderType = OrderType.market
    limit_price: Decimal | None = None
    estimated_price: Decimal | None = None
    asset_class: AssetClass | None = None
    uses_margin: bool = False
    option: OptionDetail | None = None
    rationale: str | None = None

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must not be empty")
        return v

    @field_validator("quantity", "limit_price", "estimated_price", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Any:
        return None if v is None else _to_decimal(v)

    @field_validator("quantity")
    @classmethod
    def _positive_qty(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("trade quantity must be positive")
        return v

    @model_validator(mode="after")
    def _price_present(self) -> Trade:
        if self.option is not None and self.asset_class is None:
            object.__setattr__(self, "asset_class", AssetClass.option)
        # Mirror Position: an option trade must carry its contract detail, otherwise
        # multiplier falls back to 1 and order value is understated by ~100x.
        if self.asset_class is AssetClass.option and self.option is None:
            raise ValueError(
                f"trade for {self.symbol!r} is asset_class 'option' but has no option detail"
            )
        if self.order_type is OrderType.limit and self.limit_price is None:
            raise ValueError("limit orders require a limit_price")
        if self.order_type is OrderType.market and self.estimated_price is None:
            raise ValueError("market orders require an estimated_price")
        if self.eval_price is None or self.eval_price <= 0:
            raise ValueError("evaluation price must be positive")
        return self

    @property
    def eval_price(self) -> Decimal | None:
        return self.limit_price if self.order_type is OrderType.limit else self.estimated_price

    @property
    def multiplier(self) -> Decimal:
        return Decimal(self.option.multiplier) if self.option else Decimal(1)

    @property
    def order_value(self) -> Decimal:
        price = self.eval_price or Decimal(0)
        return self.quantity * price * self.multiplier


# --------------------------------------------------------------------------- #
# Risk policy                                                                 #
# --------------------------------------------------------------------------- #


def _pct_field(default: float | None = None) -> Any:
    return Field(default=default, ge=0, le=100)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_single_position_pct: float | None = _pct_field()
    max_sector_pct: dict[str, float] = Field(default_factory=dict)
    max_tag_pct: dict[str, float] = Field(default_factory=dict)
    max_asset_class_pct: dict[str, float] = Field(default_factory=dict)
    warn_at_utilization: float = Field(default=80.0, ge=0, le=100)

    @field_validator("max_sector_pct", "max_tag_pct", "max_asset_class_pct")
    @classmethod
    def _valid_bucket_pcts(cls, v: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, pct in v.items():
            if not 0 <= pct <= 100:
                raise ValueError(f"limit for {key!r} must be between 0 and 100")
            out[key.strip().lower()] = float(pct)
        return out


class AssetRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crypto: RuleAction = RuleAction.allow
    options: RuleAction = RuleAction.allow
    margin: RuleAction = RuleAction.allow


class OrderRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_order_pct_of_portfolio: float | None = _pct_field()
    max_order_value: float | None = Field(default=None, ge=0)
    min_cash_pct: float | None = _pct_field()


class Restricted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    never_trade: list[str] = Field(default_factory=list)
    warn_list: list[str] = Field(default_factory=list)

    @field_validator("never_trade", "warn_list")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]


class DataRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_snapshot_age_hours: float = Field(default=24.0, ge=0)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    revision: int = 1
    preset: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    notes: str | None = None

    limits: Limits = Field(default_factory=Limits)
    asset_rules: AssetRules = Field(default_factory=AssetRules)
    order_rules: OrderRules = Field(default_factory=OrderRules)
    restricted: Restricted = Field(default_factory=Restricted)
    data_rules: DataRules = Field(default_factory=DataRules)


# --------------------------------------------------------------------------- #
# Outputs (plain-typed: no Decimal, so JSON serialization is trivial & stable) #
# --------------------------------------------------------------------------- #


class CheckResult(BaseModel):
    id: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Verdict(BaseModel):
    verdict: str  # PASS | WARN | BLOCK | OVERRIDDEN
    proceed: bool
    summary: str
    checks: list[CheckResult] = Field(default_factory=list)
    acknowledgements_required: list[str] = Field(default_factory=list)
    overrides: list[str] = Field(default_factory=list)  # block tokens bypassed this trade
    override_rejected: list[str] = Field(default_factory=list)  # tokens that cannot be bypassed
    evaluated: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    engine: dict[str, Any] = Field(default_factory=dict)


class RiskReport(BaseModel):
    totals: dict[str, Any] = Field(default_factory=dict)
    positions_by_weight: list[dict[str, Any]] = Field(default_factory=list)
    breakdowns: dict[str, Any] = Field(default_factory=dict)
    concentration: dict[str, Any] = Field(default_factory=dict)
    top_risks: list[dict[str, Any]] = Field(default_factory=list)
    compliance: dict[str, Any] | None = None
    focus: dict[str, Any] | None = None
    data_quality: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    engine: dict[str, Any] = Field(default_factory=dict)


class PolicyDiffEntry(BaseModel):
    field: str
    old: Any = None
    new: Any = None
    classification: str  # tightening | loosening | neutral


class PolicyResult(BaseModel):
    mode: str  # create | update | show
    written: bool
    path: str | None = None
    requires_confirmation: bool = False
    message: str = ""
    policy: dict[str, Any] = Field(default_factory=dict)
    yaml: str = ""
    summary: list[str] = Field(default_factory=list)
    diff: list[PolicyDiffEntry] | None = None
