"""Load the provided CSV files into SQLite. Source files are never modified."""

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from emporio.text import fold, normalize_email, normalize_phone, tokens

SCHEMA = Path(__file__).with_name("schema.sql")
CSV_PATTERN = "desafio_tecnico_ai_eng - {}.csv"


@dataclass
class LoadReport:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = ["Loaded: " + ", ".join(f"{name}={n}" for name, n in self.counts.items())]
        lines += [f"  warning: {warning}" for warning in self.warnings]
        return "\n".join(lines)


def _read(data_dir: Path, table: str) -> list[dict[str, str]]:
    with (data_dir / CSV_PATTERN.format(table)).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _cents(value: str) -> int:
    return int(Decimal(value) * 100)


def load_csvs(connection: sqlite3.Connection, data_dir: Path) -> LoadReport:
    report = LoadReport()
    categories = _read(data_dir, "categories")
    products = _read(data_dir, "products")
    customers = _read(data_dir, "customers")
    orders = _read(data_dir, "orders")
    items = _read(data_dir, "order_items")
    promotions = _read(data_dir, "promotions")

    category_names = {row["category_id"]: row["name"] for row in categories}
    connection.executemany(
        "INSERT INTO categories VALUES (?, ?, ?, ?)",
        [
            (r["category_id"], r["name"], r["description"], " ".join(tokens(r["name"])))
            for r in categories
        ],
    )

    for row in products:
        specs = json.loads(row["specs"])
        electronics = {"yes": 1, "no": 0}.get(specs.get("electronics", ""))
        strings = specs.get("strings")
        connection.execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["product_id"],
                row["name"],
                row["category_id"],
                _cents(row["price_brl"]),
                row["description"],
                int(row["stock_quantity"]),
                row["status"],
                row["specs"],
                strings if strings in ("nylon", "steel") else None,
                electronics,
                " ".join(tokens(row["name"])),
                " ".join(
                    tokens(
                        f"{row['name']} {row['description']} {category_names[row['category_id']]}"
                    )
                ),
            ),
        )

    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
        [
            (
                r["customer_id"],
                r["name"],
                normalize_phone(r["phone"]),
                normalize_email(r["email"]),
                r["city"],
            )
            for r in customers
        ],
    )
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["order_id"],
                r["customer_id"],
                r["order_date"],
                r["status"],
                _cents(r["total_brl"]),
                r["payment_method"],
                r["tracking_code"] or None,
                r["estimated_delivery"] or None,
                r["notes"] or None,
            )
            for r in orders
        ],
    )
    connection.executemany(
        "INSERT INTO order_items VALUES (?, ?, ?)",
        [(r["order_id"], r["product_id"], r["quantity"]) for r in items],
    )
    connection.executemany(
        "INSERT INTO promotions VALUES (?, ?, ?, ?, ?)",
        [
            (
                r["promotion_id"],
                r["product_id"],
                r["discount_percent"],
                r["description"],
                r["is_active"],
            )
            for r in promotions
        ],
    )

    report.counts = {
        "categories": len(categories),
        "products": len(products),
        "customers": len(customers),
        "orders": len(orders),
        "order_items": len(items),
        "promotions": len(promotions),
    }
    report.warnings = quality_warnings(connection)
    return report


def quality_warnings(connection: sqlite3.Connection) -> list[str]:
    """Known oddities are reported, not corrected."""
    warnings: list[str] = []

    for row in connection.execute(
        """
        SELECT o.order_id, o.total_cents, SUM(p.price_cents * i.quantity) AS computed
        FROM orders o
        JOIN order_items i USING (order_id)
        JOIN products p USING (product_id)
        GROUP BY o.order_id
        HAVING o.total_cents <> computed
        """
    ):
        warnings.append(
            f"order {row['order_id']}: stored total {row['total_cents'] / 100:.2f} differs from "
            f"items {row['computed'] / 100:.2f}; stored total kept"
        )

    for row in connection.execute(
        "SELECT product_id, name, status, stock_quantity FROM products "
        "WHERE (status = 'discontinued' AND stock_quantity > 0) OR status = 'coming_soon'"
    ):
        warnings.append(
            f"product {row['product_id']} ({row['name']}): {row['status']} with stock "
            f"{row['stock_quantity']}; not sold"
        )

    for row in connection.execute(
        "SELECT email, COUNT(*) AS n FROM customers GROUP BY email HAVING n > 1"
    ):
        warnings.append(f"{row['n']} customers share one e-mail; it cannot identify a customer")

    for row in connection.execute(
        "SELECT c.name FROM categories c LEFT JOIN products p USING (category_id) "
        "WHERE p.product_id IS NULL"
    ):
        warnings.append(f"category '{fold(row['name'])}' has no products")

    return warnings
