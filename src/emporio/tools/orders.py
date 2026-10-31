"""Customer verification, orders, returns and handoff.

No input model here has a customer id. Identity comes from the session, which only
verify_customer can set, and failures are identical for every cause.
"""

import sqlite3
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from emporio.data import repositories as repo
from emporio.domain.hours import store_status
from emporio.domain.money import format_brl, from_cents
from emporio.domain.returns import (
    PurchaseChannel,
    ReturnReason,
    ReturnRequest,
    evaluate_return,
)
from emporio.memory.redact import redact
from emporio.text import normalize_email, normalize_phone
from emporio.tools.base import Tool, ToolContext, ToolFailure
from emporio.tools.catalog import NoInput

MAX_VERIFICATION_ATTEMPTS = 3
GENERIC_FAILURE = "verification_failed"
NOT_VERIFIED = "customer_not_verified"
ORDER_NOT_FOUND = "order_not_found_for_this_customer"

STATUS_MEANING = {
    "pending": "awaiting confirmation",
    "confirmed": "confirmed, being prepared",
    "shipped": "on its way",
    "delivered": "delivered",
    "cancelled": "cancelled",
}


class VerifyCustomerInput(BaseModel):
    order_id: int | None = Field(None, description="Order number given by the customer")
    phone: str | None = Field(None, description="Phone exactly as the customer gave it")
    email: str | None = Field(None, description="E-mail exactly as the customer gave it")


def _matches(customer: sqlite3.Row, phone: str | None, email: str | None) -> bool:
    phone_ok = phone is not None and normalize_phone(phone) == customer["phone_digits"]
    email_ok = email is not None and normalize_email(email) == customer["email"]
    return phone_ok or email_ok


def verify_customer(context: ToolContext, args: VerifyCustomerInput) -> dict[str, Any]:
    session = context.session
    if session.failed_verifications >= MAX_VERIFICATION_ATTEMPTS:
        raise ToolFailure("verification_locked_create_a_handoff")

    customer: sqlite3.Row | None = None
    if args.order_id is not None and (args.phone or args.email):
        owner = repo.customer_owning_order(context.connection, args.order_id)
        customer = owner if owner is not None and _matches(owner, args.phone, args.email) else None
    elif args.phone and args.email:
        customer = repo.customer_by_contacts(
            context.connection, normalize_phone(args.phone), normalize_email(args.email)
        )
    else:
        return {
            "verified": False,
            "needed": "Order number plus phone or e-mail, or both phone and e-mail.",
        }

    if customer is None:
        session.failed_verifications += 1
        raise ToolFailure(GENERIC_FAILURE)

    session.verified_customer_id = customer["customer_id"]
    session.verified_at = context.clock.now()
    session.failed_verifications = 0
    return {"verified": True, "first_name": customer["name"].split()[0]}


def _require_verified(context: ToolContext) -> int:
    customer_id = context.session.verified_customer_id
    if customer_id is None:
        raise ToolFailure(NOT_VERIFIED)
    return customer_id


def _order_view(context: ToolContext, order: sqlite3.Row) -> dict[str, Any]:
    today = context.clock.now().date()
    view: dict[str, Any] = {
        "order_id": order["order_id"],
        "status": order["status"],
        "status_meaning": STATUS_MEANING[order["status"]],
        "order_date": order["order_date"],
        "total": format_brl(from_cents(order["total_cents"])),
        "payment_method": order["payment_method"],
        "items": repo.order_items(context.connection, order["order_id"]),
        "tracking_code": order["tracking_code"],
        "estimated_delivery": order["estimated_delivery"],
    }
    if order["status"] == "cancelled" and order["notes"]:
        view["cancellation_reason"] = order["notes"]
    if order["status"] == "shipped" and order["estimated_delivery"]:
        late = (today - date.fromisoformat(order["estimated_delivery"])).days
        if late > 0:
            view["days_overdue"] = late
            view["note"] = "Delayed. No reason is recorded: do not suggest one. Offer a handoff."
    return view


class OrderInput(BaseModel):
    order_id: int


def get_order(context: ToolContext, args: OrderInput) -> dict[str, Any]:
    customer_id = _require_verified(context)
    order = repo.order_for_customer(context.connection, args.order_id, customer_id)
    if order is None:
        raise ToolFailure(ORDER_NOT_FOUND)
    return _order_view(context, order)


def list_my_orders(context: ToolContext, _: NoInput) -> dict[str, Any]:
    customer_id = _require_verified(context)
    orders = repo.orders_for_customer(context.connection, customer_id)
    return {"orders": [_order_view(context, order) for order in orders]}


class ReturnInput(BaseModel):
    order_id: int
    reason: ReturnReason = Field(
        description="regret: changed their mind. defect: manufacturing problem. "
        "preference: wants another color, model or size."
    )
    purchase_channel: PurchaseChannel | None = Field(
        None, description="Only if the customer said it. Never assume."
    )
    condition_ok: bool | None = Field(
        None,
        description="True only if the customer confirmed it is unused, complete and in the "
        "original packaging.",
    )


def check_return_eligibility(context: ToolContext, args: ReturnInput) -> dict[str, Any]:
    customer_id = _require_verified(context)
    order = repo.order_for_customer(context.connection, args.order_id, customer_id)
    if order is None:
        raise ToolFailure(ORDER_NOT_FOUND)
    estimated = order["estimated_delivery"]
    decision = evaluate_return(
        ReturnRequest(
            status=order["status"],
            order_date=date.fromisoformat(order["order_date"]),
            estimated_delivery=date.fromisoformat(estimated) if estimated else None,
            reason=args.reason,
            purchase_channel=args.purchase_channel,
            condition_ok=args.condition_ok,
        ),
        context.clock.now().date(),
        context.rules.returns,
    )
    return {
        "verdict": decision.verdict.value,
        "rule": decision.rule,
        "explanation": decision.explanation,
        "days_since_purchase": decision.days_since_purchase,
        "days_since_estimated_delivery": decision.days_since_estimated_delivery,
        "ask_customer": list(decision.ask_customer),
        "caveats": list(decision.caveats),
    }


class HandoffKind(StrEnum):
    COMPLAINT = "complaint"
    HUMAN_REQUEST = "human_request"
    POLICY_DOUBT = "policy_doubt"
    ORDER_ISSUE = "order_issue"
    VERIFICATION_FAILED = "verification_failed"
    DATA_REQUEST = "data_request"
    TOOL_FAILURE = "tool_failure"


class HandoffInput(BaseModel):
    kind: HandoffKind
    summary: str = Field(min_length=5, max_length=1000, description="Facts for the team")


def register_handoff(context: ToolContext, kind: str, summary: str) -> dict[str, Any]:
    """One open handoff per kind per conversation, so retries never duplicate."""
    session_id = context.session.session_id
    now = context.clock.now()
    existing = context.connection.execute(
        "SELECT protocol FROM handoffs WHERE session_id = ? AND kind = ?", (session_id, kind)
    ).fetchone()
    if existing:
        protocol = existing["protocol"]
    else:
        # One statement, so concurrent handoffs cannot take the same number.
        protocol = context.connection.execute(
            """
            INSERT INTO handoffs
            SELECT ? || printf('%04d', COUNT(*) + 1), ?, ?, ?, ? FROM handoffs
            RETURNING protocol
            """,
            (f"EM-{now:%Y%m%d}-", session_id, kind, redact(summary), now.isoformat()),
        ).fetchone()["protocol"]
        # Commit now: the turn may keep waiting on the model, and an open write
        # transaction would block every other conversation.
        context.connection.commit()

    status = store_status(now, context.facts)
    return {
        "protocol": protocol,
        "response_deadline": context.rules.handoff.complaint_response,
        "team_returns_at": status.next_opening.strftime("%A %Y-%m-%d %H:%M")
        if status.next_opening
        else None,
    }


def create_handoff(context: ToolContext, args: HandoffInput) -> dict[str, Any]:
    return register_handoff(context, args.kind.value, args.summary)


TOOLS = [
    Tool(
        "verify_customer",
        "Confirm who the customer is, before any order lookup. Needs the order number plus the "
        "phone or e-mail on it, or both phone and e-mail. Use only what the customer typed.",
        VerifyCustomerInput,
        verify_customer,
    ),
    Tool(
        "get_order",
        "Status, items, total, tracking and delivery estimate of one order of the verified "
        "customer.",
        OrderInput,
        get_order,
    ),
    Tool(
        "list_my_orders",
        "All orders of the verified customer.",
        NoInput,
        list_my_orders,
    ),
    Tool(
        "check_return_eligibility",
        "Decide whether an order of the verified customer can be returned or exchanged. The "
        "verdict is final: eligible, ineligible, needs_info (ask what it says) or needs_human "
        "(create a handoff). Always use it rather than judging dates yourself.",
        ReturnInput,
        check_return_eligibility,
    ),
    Tool(
        "create_handoff",
        "Forward a case to the human team and get a protocol number. Use it for complaints, "
        "requests for a person, doubtful or conflicting policy, delayed orders the customer "
        "wants followed up, personal-data deletion, or tool failures.",
        HandoffInput,
        create_handoff,
    ),
]
