"""Small deterministic numeric helpers.

All risk math is done in ``Decimal``; these helpers convert to rounded floats
only at the output boundary so JSON is clean and golden tests never wobble on
float representation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# A tiny tolerance for "did this get worse?" comparisons, so floating boundary
# cases (e.g. 25.0000001 vs 25.0) don't flip a verdict on rounding noise.
EPSILON = Decimal("0.0001")


def ratio_pct(part: Decimal, whole: Decimal) -> Decimal:
    """``part`` as a percentage (0-100) of ``whole``; 0 when ``whole`` is 0."""
    if whole == 0:
        return Decimal(0)
    return part / whole * Decimal(100)


def q1(d: Decimal | float) -> float:
    """Round to 1 decimal place as a float (used for percentages)."""
    return float(Decimal(str(d)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def q2(d: Decimal | float) -> float:
    """Round to 2 decimal places as a float (used for money)."""
    return float(Decimal(str(d)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def q4(d: Decimal | float) -> float:
    """Round to 4 decimal places (used for the HHI concentration index)."""
    return float(Decimal(str(d)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
