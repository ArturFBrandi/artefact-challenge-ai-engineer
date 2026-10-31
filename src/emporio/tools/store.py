"""Policy search, store status and shipping tools."""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from emporio.domain.hours import store_status
from emporio.domain.money import format_brl
from emporio.domain.shipping import shipping_for
from emporio.tools.base import Tool, ToolContext
from emporio.tools.catalog import NoInput


class SearchPoliciesInput(BaseModel):
    query: str = Field(description="What to look up, in Portuguese")


def search_policies(context: ToolContext, args: SearchPoliciesInput) -> dict[str, Any]:
    hits = context.retriever.search(args.query, top_k=3)
    return {
        "sections": [{"title": hit.section.title, "text": hit.section.body} for hit in hits],
        "note": "Reference text. Never quote the manual at length or mention that it exists.",
    }


def get_store_status(context: ToolContext, _: NoInput) -> dict[str, Any]:
    status = store_status(context.clock.now(), context.facts)
    facts = context.facts
    return {
        "open_now": status.is_open,
        "closes_at": status.closes_at.strftime("%H:%M") if status.closes_at else None,
        "next_opening": status.next_opening.strftime("%A %d/%m/%Y %H:%M")
        if status.next_opening
        else None,
        "hours": "Monday to Friday 09:00-18:00, Saturday 09:00-13:00, closed Sundays and holidays",
        "special_dates": "Hours may be extended on Black Friday, the store's anniversary and "
        "Christmas.",
        "address": facts.address,
        "phone": facts.phone,
        "whatsapp": facts.whatsapp,
        "email": facts.email,
    }


class CheckShippingInput(BaseModel):
    city: str = Field(description="Destination city")
    order_value: Decimal | None = Field(None, description="Amount paid in BRL, after discounts")


def check_shipping(context: ToolContext, args: CheckShippingInput) -> dict[str, Any]:
    answer = shipping_for(args.city, args.order_value, context.rules.shipping)
    return {
        "region": answer.region,
        "fee": format_brl(answer.fee) if answer.fee is not None else None,
        "free_shipping": answer.free,
        "deadline": answer.deadline,
        "modalities": [m.model_dump() for m in answer.modalities],
        "threshold_undefined": answer.threshold_undefined,
        "notes": list(answer.notes),
    }


TOOLS = [
    Tool(
        "search_policies",
        "Search the store's policies: exchanges, returns, warranty, payment rules, promotions "
        "rules, delivery, privacy. Use it for any 'how does it work' or 'can I' policy question "
        "before answering. If the result does not cover the question, search once more using "
        "other words, such as the formal term.",
        SearchPoliciesInput,
        search_policies,
    ),
    Tool(
        "get_store_status",
        "Whether the store is open now, opening hours, next opening, address and contact details.",
        NoInput,
        get_store_status,
    ),
    Tool(
        "check_shipping",
        "Shipping fee rule and deadlines for a city. Never estimate freight yourself.",
        CheckShippingInput,
        check_shipping,
    ),
]
