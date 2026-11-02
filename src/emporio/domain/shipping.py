"""Shipping rules. There is no freight table, so other cities never get a price."""

from dataclasses import dataclass
from decimal import Decimal

from emporio.domain.money import to_money
from emporio.domain.rules import ShippingModality, ShippingRules
from emporio.text import fold


@dataclass(frozen=True)
class ShippingAnswer:
    region: str
    fee: Decimal | None
    free: bool | None
    deadline: str | None
    modalities: tuple[ShippingModality, ...]
    threshold_undefined: bool
    notes: tuple[str, ...]


def shipping_for(city: str, order_value: Decimal | None, rules: ShippingRules) -> ShippingAnswer:
    if fold(city).strip() != "campo grande":
        return ShippingAnswer(
            region="other_city",
            fee=None,
            free=None,
            deadline=None,
            modalities=rules.other_cities,
            threshold_undefined=False,
            notes=(
                "Freight is calculated from ZIP code, weight and dimensions; no price is available "
                "here. Large instruments may need an individual quote.",
                "Other municipalities of the metro region are not listed, so only Campo Grande "
                "is treated as metro.",
            ),
        )

    threshold = rules.metro_free_above_brl
    notes: tuple[str, ...]
    if order_value is None:
        fee, free, undefined = None, None, False
        notes = (f"Free above {threshold} BRL, flat fee {rules.metro_flat_fee_brl} BRL below it.",)
    elif order_value == threshold:
        fee, free, undefined = None, None, True
        notes = ("The policy covers amounts above and below this value, but not this exact one.",)
    elif order_value > threshold:
        fee, free, undefined = to_money(0), True, False
        notes = ()
    else:
        fee, free, undefined = to_money(rules.metro_flat_fee_brl), False, False
        notes = ()

    return ShippingAnswer(
        region="metro_campo_grande",
        fee=fee,
        free=free,
        deadline=rules.metro_days,
        modalities=(),
        threshold_undefined=undefined,
        notes=notes,
    )
