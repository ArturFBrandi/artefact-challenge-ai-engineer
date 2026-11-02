"""Parameterized queries. Order and customer access always filters by the verified customer."""

import sqlite3
from typing import Any

Row = sqlite3.Row

_PRODUCT_COLUMNS = """
    p.*, c.name AS category,
    (SELECT discount_percent FROM promotions m
     WHERE m.product_id = p.product_id AND m.is_active = 1
     ORDER BY discount_percent DESC LIMIT 1) AS promotion_percent,
    (SELECT description FROM promotions m
     WHERE m.product_id = p.product_id AND m.is_active = 1
     ORDER BY discount_percent DESC LIMIT 1) AS promotion_name
"""
_PRODUCTS = f"SELECT {_PRODUCT_COLUMNS} FROM products p JOIN categories c USING (category_id)"


def all_products(connection: sqlite3.Connection) -> list[Row]:
    return connection.execute(_PRODUCTS).fetchall()


def product_by_id(connection: sqlite3.Connection, product_id: int) -> Row | None:
    row: Row | None = connection.execute(
        f"{_PRODUCTS} WHERE p.product_id = ?", (product_id,)
    ).fetchone()
    return row


def inactive_promotions(connection: sqlite3.Connection, product_id: int) -> list[Row]:
    return connection.execute(
        "SELECT description, discount_percent FROM promotions "
        "WHERE product_id = ? AND is_active = 0",
        (product_id,),
    ).fetchall()


def customer_by_id(connection: sqlite3.Connection, customer_id: int) -> Row | None:
    row: Row | None = connection.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    return row


def customer_owning_order(connection: sqlite3.Connection, order_id: int) -> Row | None:
    row: Row | None = connection.execute(
        "SELECT c.* FROM customers c JOIN orders o USING (customer_id) WHERE o.order_id = ?",
        (order_id,),
    ).fetchone()
    return row


def customer_by_contacts(connection: sqlite3.Connection, phone: str, email: str) -> Row | None:
    row: Row | None = connection.execute(
        "SELECT * FROM customers WHERE phone_digits = ? AND email = ?", (phone, email)
    ).fetchone()
    return row


def order_for_customer(
    connection: sqlite3.Connection, order_id: int, customer_id: int
) -> Row | None:
    row: Row | None = connection.execute(
        "SELECT * FROM orders WHERE order_id = ? AND customer_id = ?", (order_id, customer_id)
    ).fetchone()
    return row


def orders_for_customer(connection: sqlite3.Connection, customer_id: int) -> list[Row]:
    return connection.execute(
        "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC", (customer_id,)
    ).fetchall()


def order_items(connection: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT p.name, c.name AS category, i.quantity FROM order_items i "
        "JOIN products p USING (product_id) JOIN categories c USING (category_id) "
        "WHERE i.order_id = ?",
        (order_id,),
    ).fetchall()
    return [dict(row) for row in rows]
