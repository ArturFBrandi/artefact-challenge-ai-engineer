"""Catalog, promotion and price tools."""

import difflib
import json
import sqlite3
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from emporio.data import repositories as repo
from emporio.domain.availability import Availability, availability_of
from emporio.domain.money import format_brl, from_cents, to_money
from emporio.domain.pricing import (
    PaymentMethod,
    max_installments,
    promotional_price,
    quote,
)
from emporio.domain.rules import PolicyRules
from emporio.text import analyze, tokens
from emporio.tools.base import Tool, ToolContext, ToolFailure

Category = Literal[
    "Guitarras",
    "Baixos",
    "Baterias e Percussão",
    "Teclados e Pianos",
    "Violões",
    "Instrumentos de Sopro (Madeiras)",
    "Instrumentos de Sopro (Metais)",
    "Cordas Orquestrais",
    "Ukuleles",
]
MAX_ALTERNATIVES = 3


def _availability(row: sqlite3.Row) -> Availability:
    return availability_of(row["status"], row["stock_quantity"])


def _current_price(row: sqlite3.Row) -> Decimal:
    price = from_cents(row["price_cents"])
    percent = row["promotion_percent"]
    return promotional_price(price, percent) if percent else price


def _pix_price(row: sqlite3.Row, rules: PolicyRules) -> Decimal:
    price = from_cents(row["price_cents"])
    percent = row["promotion_percent"]
    return quote(price, percent, PaymentMethod.PIX, 1, rules.payment).final_price


def _summary(row: sqlite3.Row, rules: PolicyRules) -> dict[str, Any]:
    list_price = from_cents(row["price_cents"])
    current = _current_price(row)
    summary: dict[str, Any] = {
        "product_id": row["product_id"],
        "name": row["name"],
        "category": row["category"],
        "availability": _availability(row).value,
        "price": format_brl(current),
        "pix_price": format_brl(_pix_price(row, rules)),
    }
    if row["promotion_percent"]:
        summary["promotion"] = {
            "name": row["promotion_name"],
            "percent": row["promotion_percent"],
            "original_price": format_brl(list_price),
            "promotional_price": format_brl(current),
        }
    return summary


class SearchProductsInput(BaseModel):
    query: str | None = Field(None, description="Words to find in name or description")
    category: Category | None = None
    max_price: Decimal | None = Field(None, description="Highest current price in BRL")
    min_price: Decimal | None = Field(None, description="Lowest current price in BRL")
    strings: Literal["nylon", "steel"] | None = Field(None, description="String type")
    electronics: bool | None = Field(None, description="True for electro-acoustic models")
    available_only: bool = Field(True, description="Keep true unless asked about unavailable items")
    limit: int = Field(4, ge=1, le=6, description="How many products to show")


def _match_terms(rows: list[sqlite3.Row], terms: set[str]) -> tuple[list[sqlite3.Row], bool]:
    """All words first. If that finds nothing, products matching at least half of the words."""
    if not terms:
        return rows, False
    scored = [(len(terms & set(analyze(r["search_text"]))), r) for r in rows]
    complete = [r for matched, r in scored if matched == len(terms)]
    if complete:
        return complete, False
    if len(terms) == 1:
        return [], False
    return [r for matched, r in scored if matched * 2 >= len(terms)], True


def search_products(context: ToolContext, args: SearchProductsInput) -> dict[str, Any]:
    rows = repo.all_products(context.connection)
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    if args.strings:
        rows = [r for r in rows if r["strings_type"] == args.strings]
    if args.electronics is not None:
        rows = [r for r in rows if r["electronics"] == int(args.electronics)]

    rows, partial = _match_terms(rows, set(analyze(args.query or "")))

    def in_budget(row: sqlite3.Row, price: Decimal) -> bool:
        above_min = args.min_price is None or price >= args.min_price
        return above_min and (args.max_price is None or price <= args.max_price)

    budget = [r for r in rows if in_budget(r, _current_price(r))]
    available = [r for r in budget if _availability(r) is Availability.AVAILABLE]
    selected = available if args.available_only else budget
    selected = sorted(selected, key=lambda r: _current_price(r))

    result: dict[str, Any] = {
        "total_matches": len(selected),
        "unavailable_matches_hidden": len(budget) - len(available) if args.available_only else 0,
        "products": [_summary(r, context.rules) for r in selected[: args.limit]],
    }
    if args.max_price is not None and args.available_only:
        result["fits_budget_only_with_pix"] = [
            _summary(r, context.rules)
            for r in rows
            if not in_budget(r, _current_price(r))
            and in_budget(r, _pix_price(r, context.rules))
            and _availability(r) is Availability.AVAILABLE
        ]
    if not selected:
        result["note"] = "Nothing in the catalog matches. Do not suggest products from memory."
    elif partial:
        result["partial_match"] = True
        result["note"] = (
            "Only some of the search words matched. If the customer asked for a specific type of "
            "instrument, these products may be something else: check before offering them."
        )
    return result


class GetProductInput(BaseModel):
    name_or_id: str = Field(description="Product id, or its name as the customer wrote it")


def _find(rows: list[sqlite3.Row], name: str) -> list[sqlite3.Row]:
    wanted = tokens(name)
    if not wanted:
        return []
    exact = [r for r in rows if set(wanted) <= set(r["search_name"].split())]
    if exact:
        return exact
    names = {r["search_name"]: r for r in rows}
    close = difflib.get_close_matches(" ".join(wanted), names, n=4, cutoff=0.5)
    return [names[match] for match in close]


def _alternatives(row: sqlite3.Row, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    candidates = [
        r
        for r in rows
        if r["category_id"] == row["category_id"]
        and r["product_id"] != row["product_id"]
        and _availability(r) is Availability.AVAILABLE
    ]
    target = row["price_cents"]
    return sorted(candidates, key=lambda r: abs(r["price_cents"] - target))[:MAX_ALTERNATIVES]


def get_product(context: ToolContext, args: GetProductInput) -> dict[str, Any]:
    rows = repo.all_products(context.connection)
    key = args.name_or_id.strip()
    matches = [r for r in rows if str(r["product_id"]) == key] or _find(rows, key)
    if not matches:
        raise ToolFailure("product_not_found")
    if len(matches) > 1:
        return {
            "ambiguous": True,
            "candidates": [_summary(r, context.rules) for r in matches],
            "note": "Several products match. Ask which one the customer means.",
        }

    row = matches[0]
    result = _summary(row, context.rules)
    availability = _availability(row)
    result["description"] = row["description"]
    result["specs"] = json.loads(row["specs"])
    if availability is Availability.AVAILABLE:
        result["stock_quantity"] = row["stock_quantity"]
        limit = max_installments(_current_price(row), context.rules.payment)
        result["max_installments"] = limit
        result["value_at_max_installments"] = format_brl(to_money(_current_price(row) / limit))
    else:
        result["alternatives"] = [_summary(r, context.rules) for r in _alternatives(row, rows)]
        del result["pix_price"]
    expired = repo.inactive_promotions(context.connection, row["product_id"])
    if expired:
        result["expired_promotions"] = [e["description"] for e in expired]
    return result


class QuotePriceInput(BaseModel):
    product_id: int
    payment_method: PaymentMethod
    installments: int = Field(1, ge=1, le=36, description="Only for credit card")


def quote_price(context: ToolContext, args: QuotePriceInput) -> dict[str, Any]:
    row = repo.product_by_id(context.connection, args.product_id)
    if row is None:
        raise ToolFailure("product_not_found")
    result = quote(
        from_cents(row["price_cents"]),
        row["promotion_percent"],
        args.payment_method,
        args.installments,
        context.rules.payment,
    )
    output: dict[str, Any] = {
        "product": row["name"],
        "availability": _availability(row).value,
        "list_price": format_brl(result.list_price),
        "final_price": format_brl(result.final_price),
        "payment_method": result.method.value,
        "installments_requested": result.installments,
        "installments_allowed": result.installments_allowed,
        "max_installments": result.max_installments,
        "notes": list(result.notes),
    }
    if args.payment_method is PaymentMethod.CREDIT:
        output["value_at_max_installments"] = format_brl(
            to_money(result.final_price / result.max_installments)
        )
    if result.installment_value is not None:
        output["installment_value"] = format_brl(result.installment_value)
    if result.promotion_percent:
        output["promotion_percent"] = result.promotion_percent
        output["promotional_price"] = format_brl(result.final_price)
    if result.pix_discount_percent:
        output["pix_discount_percent"] = int(result.pix_discount_percent)
    return output


class NoInput(BaseModel):
    pass


def list_active_promotions(context: ToolContext, _: NoInput) -> dict[str, Any]:
    rows = [r for r in repo.all_products(context.connection) if r["promotion_percent"]]
    return {
        "promotions": [
            _summary(r, context.rules) for r in rows if _availability(r) is Availability.AVAILABLE
        ]
    }


TOOLS = [
    Tool(
        "search_products",
        "Browse the catalog by words, category, budget, string type or electronics. Use it for "
        "'what do you have' questions and budgets. It is the only source of what the store "
        "sells, so also use it before saying a kind of instrument is or is not sold.",
        SearchProductsInput,
        search_products,
    ),
    Tool(
        "get_product",
        "Details of one product by name or id: price, availability, specs, active promotion and "
        "alternatives when it cannot be bought. Use it whenever a specific product is mentioned.",
        GetProductInput,
        get_product,
    ),
    Tool(
        "quote_price",
        "Exact price for a payment method, including the PIX discount, promotions and "
        "installment limits. Use it for every payment question. Never calculate prices yourself.",
        QuotePriceInput,
        quote_price,
    ),
    Tool(
        "list_active_promotions",
        "All promotions valid now. Use it for general questions about promotions and discounts.",
        NoInput,
        list_active_promotions,
    ),
]
