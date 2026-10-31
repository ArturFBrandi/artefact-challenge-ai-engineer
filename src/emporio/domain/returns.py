"""Return and exchange eligibility.

The manual leaves gaps: no delivery date and no purchase channel in the data, and §4.2 conflicts
with §8.1 between days 31 and 90. Those cases ask the customer or go to a human instead of
guessing. See docs/DATA_AUDIT.md.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from emporio.domain.rules import ReturnRules


class Verdict(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEEDS_INFO = "needs_info"
    NEEDS_HUMAN = "needs_human"


class ReturnReason(StrEnum):
    REGRET = "regret"
    DEFECT = "defect"
    PREFERENCE = "preference"


class PurchaseChannel(StrEnum):
    ONLINE = "online"
    IN_STORE = "in_store"


@dataclass(frozen=True)
class ReturnRequest:
    status: str
    order_date: date
    estimated_delivery: date | None
    reason: ReturnReason
    purchase_channel: PurchaseChannel | None = None
    condition_ok: bool | None = None


@dataclass(frozen=True)
class ReturnDecision:
    verdict: Verdict
    rule: str
    explanation: str
    days_since_purchase: int
    days_since_estimated_delivery: int | None
    ask_customer: tuple[str, ...] = ()
    caveats: tuple[str, ...] = field(default=())


PROXY_CAVEAT = (
    "The store has no recorded delivery date; this uses the estimated delivery date as an "
    "approximation, and the customer should be told so."
)
EXCLUSIONS_CAVEAT = (
    "Not eligible for exchange: customized instruments, final-sale clearance items and wind "
    "mouthpieces (§4.4). The data does not record these, so confirm with the customer."
)


def evaluate_return(request: ReturnRequest, today: date, rules: ReturnRules) -> ReturnDecision:
    since_purchase = (today - request.order_date).days
    since_receipt = (
        (today - request.estimated_delivery).days if request.estimated_delivery else None
    )

    def decide(
        verdict: Verdict,
        rule: str,
        explanation: str,
        ask: tuple[str, ...] = (),
        caveats: tuple[str, ...] = (),
    ) -> ReturnDecision:
        return ReturnDecision(
            verdict, rule, explanation, since_purchase, since_receipt, ask, caveats
        )

    if request.status == "cancelled":
        return decide(Verdict.INELIGIBLE, "order_cancelled", "This order was cancelled.")
    if request.status != "delivered" or since_receipt is None:
        return decide(
            Verdict.NEEDS_HUMAN,
            "not_received",
            "The order has not been delivered, so receipt-based windows have not started. No "
            "procedure is defined for cancelling before delivery.",
        )

    if request.reason is ReturnReason.DEFECT:
        return _defect(request, since_purchase, since_receipt, rules, decide)
    return _within_days_of_receipt(request, since_receipt, rules, decide)


def _defect(request, since_purchase, since_receipt, rules, decide):  # type: ignore[no-untyped-def]
    caveats = ("Damage from misuse, falls, humidity or unauthorized changes is not covered.",)
    if since_purchase <= rules.defect_exchange_days:
        return decide(
            Verdict.ELIGIBLE,
            "defect_exchange_4_2",
            f"Within {rules.defect_exchange_days} days of purchase: the store exchanges it.",
            caveats=(*caveats, EXCLUSIONS_CAVEAT),
        )
    if since_receipt <= rules.legal_warranty_days + rules.estimate_margin_days:
        return decide(
            Verdict.NEEDS_HUMAN,
            "warranty_conflict_4_2_8_1",
            f"Past the {rules.defect_exchange_days}-day exchange window, where §4.2 points to the "
            f"manufacturer, but inside or near the {rules.legal_warranty_days}-day legal warranty "
            "counted from receipt (§8.1). Explain both rules and let the team decide. Give no "
            "legal opinion.",
            caveats=(*caveats, PROXY_CAVEAT),
        )
    return decide(
        Verdict.INELIGIBLE,
        "manufacturer_warranty_4_2",
        "Past the store's windows: the manufacturer's warranty applies (6 months to 2 years, "
        "depending on the brand), and the store can mediate on request.",
        caveats=(PROXY_CAVEAT,),
    )


def _within_days_of_receipt(request, since_receipt, rules, decide):  # type: ignore[no-untyped-def]
    regret = request.reason is ReturnReason.REGRET
    limit = rules.regret_days if regret else rules.preference_exchange_days
    rule = "right_of_regret_4_1" if regret else "preference_exchange_4_3"

    if regret and request.purchase_channel is None:
        return decide(
            Verdict.NEEDS_INFO,
            rule,
            "The right of regret only covers online purchases, and the channel is not recorded.",
            ask=("purchase_channel",),
        )
    if regret and request.purchase_channel is PurchaseChannel.IN_STORE:
        return decide(
            Verdict.INELIGIBLE,
            rule,
            "The right of regret covers online purchases. A preference exchange within "
            f"{rules.preference_exchange_days} days may still apply.",
        )

    if since_receipt > limit + rules.estimate_margin_days:
        return decide(
            Verdict.INELIGIBLE,
            rule,
            f"The {limit}-day window has passed.",
            caveats=(PROXY_CAVEAT,),
        )
    if since_receipt > limit:
        return decide(
            Verdict.NEEDS_HUMAN,
            rule,
            f"Close to the {limit}-day limit, and the result depends on the real delivery date.",
            caveats=(PROXY_CAVEAT,),
        )
    if request.condition_ok is None:
        return decide(
            Verdict.NEEDS_INFO,
            rule,
            f"Inside the {limit}-day window. Packaging and condition still need confirming.",
            ask=("condition_ok",),
            caveats=(PROXY_CAVEAT,),
        )
    if not request.condition_ok:
        return decide(
            Verdict.INELIGIBLE,
            rule,
            "The product must be unused, complete and in its original packaging.",
            caveats=(PROXY_CAVEAT,),
        )

    if regret:
        detail = (
            f"Refund to the original payment method within {rules.refund_business_days} business "
            "days; the store pays return freight."
        )
        caveats = (PROXY_CAVEAT,)
    else:
        detail = "Subject to availability; value differences are charged or refunded."
        caveats = (PROXY_CAVEAT, EXCLUSIONS_CAVEAT)
    return decide(Verdict.ELIGIBLE, rule, f"Inside the {limit}-day window. {detail}", caveats=caveats)
