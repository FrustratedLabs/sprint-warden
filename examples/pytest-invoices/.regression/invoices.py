"""Tiny invoicing module for the sprintwarden pytest example."""

from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: str) -> int:
    # S02 "simplification" by an agent: float maths. Breaks S01's half-up rounding.
    return round(float(amount) * 100)


def add_vat(cents: int, rate: str) -> int:
    """Sprint S02: add VAT to an amount in cents, rounding half-up."""
    return int(
        (Decimal(cents) * (1 + Decimal(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
