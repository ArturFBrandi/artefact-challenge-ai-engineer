"""Prices, discounts and installments. The LLM never does this arithmetic."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from emporio.domain.money import format_brl, to_money
from emporio.domain.rules import PaymentRules

MAX_INSTALLMENTS = 12


class PaymentMethod(StrEnum):
    PIX = "pix"
    DEBIT = "debit"
    CREDIT = "credit"
    BOLETO = "boleto"


@dataclass(frozen=True)
class Quote:
    list_price: Decimal
    promotion_percent: int | None
    promotion_price: Decimal | None
    pix_discount_percent: Decimal | None
    final_price: Decimal
    method: PaymentMethod
    max_installments: int
    installments: int
    installment_value: Decimal | None
    installments_allowed: bool
    notes: tuple[str, ...]


def promotional_price(list_price: Decimal, percent: int) -> Decimal:
    return to_money(list_price * (100 - percent) / 100)


def minimum_installment(installments: int, rules: PaymentRules) -> Decimal:
    for tier in rules.installment_tiers:
        if installments <= tier.up_to:
            return tier.min_installment_brl
    raise ValueError(f"{installments} installments is above the maximum")


def installments_valid(total: Decimal, installments: int, rules: PaymentRules) -> bool:
    if installments == 1:
        return True
    if not 1 < installments <= MAX_INSTALLMENTS:
        return False
    return total >= minimum_installment(installments, rules) * installments


def max_installments(total: Decimal, rules: PaymentRules) -> int:
    allowed = [n for n in range(1, MAX_INSTALLMENTS + 1) if installments_valid(total, n, rules)]
    return max(allowed)


def quote(
    list_price: Decimal,
    promotion_percent: int | None,
    method: PaymentMethod,
    installments: int,
    rules: PaymentRules,
) -> Quote:
    promotion_price = (
        promotional_price(list_price, promotion_percent) if promotion_percent else None
    )
    base_price = promotion_price if promotion_price is not None else list_price
    notes: list[str] = []
    pix_percent: Decimal | None = None
    final_price = base_price

    if method is PaymentMethod.PIX:
        if promotion_price is None:
            pix_percent = rules.pix_discount_percent
            final_price = to_money(list_price * (100 - pix_percent) / 100)
        else:
            notes.append("The PIX discount does not apply on top of a promotional price.")

    if method is PaymentMethod.CREDIT:
        allowed = installments_valid(base_price, installments, rules)
        limit = max_installments(base_price, rules)
        if not allowed:
            notes.append(f"{installments}x is not allowed for this amount; the limit is {limit}x.")
        value = to_money(base_price / installments) if allowed else None
    else:
        allowed = installments == 1
        limit = 1
        value = None
        if not allowed:
            notes.append(f"{method.value} is paid in a single payment.")

    return Quote(
        list_price=to_money(list_price),
        promotion_percent=promotion_percent,
        promotion_price=promotion_price,
        pix_discount_percent=pix_percent,
        final_price=final_price,
        method=method,
        max_installments=limit,
        installments=installments,
        installment_value=value,
        installments_allowed=allowed,
        notes=tuple(notes),
    )


def describe_final_price(result: Quote) -> str:
    return format_brl(result.final_price)
