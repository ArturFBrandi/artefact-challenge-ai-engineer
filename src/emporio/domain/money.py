"""Money is always Decimal, rounded half up to cents."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, ROUND_HALF_UP)


def from_cents(cents: int) -> Decimal:
    return to_money(Decimal(cents) / 100)


def format_brl(value: Decimal) -> str:
    """Brazilian format in every language: R$ 2.199,00."""
    text = f"{to_money(value):,.2f}"
    return "R$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")
