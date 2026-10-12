"""Tiny invoicing module for the sprintwarden pytest example."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(amount: str) -> int:
    """Sprint S01: parse an amount like "10.005" and round half-up to cents."""
    return int((Decimal(amount) / CENT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_vat(cents: int, rate: str) -> int:
    """Sprint S02: add VAT to an amount in cents, rounding half-up."""
    return int(
        (Decimal(cents) * (1 + Decimal(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
