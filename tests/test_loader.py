import sqlite3

import pytest

from emporio.config import ROOT
from emporio.data.db import connect
from emporio.data.loader import SCHEMA, load_csvs


@pytest.fixture
def db(tmp_db) -> sqlite3.Connection:
    connection = connect(tmp_db)
    connection.executescript(SCHEMA.read_text())
    return connection


def test_loads_every_row(db):
    report = load_csvs(db, ROOT / "data")
    assert report.counts == {
        "categories": 9,
        "products": 65,
        "customers": 50,
        "orders": 20,
        "order_items": 22,
        "promotions": 25,
    }


def test_known_oddities_are_reported_not_corrected(db):
    report = load_csvs(db, ROOT / "data")
    text = "\n".join(report.warnings)
    for fragment in ("order 3:", "order 20:", "product 136", "product 130", "share one e-mail"):
        assert fragment in text
    assert sum("has no products" in warning for warning in report.warnings) == 3
    total = db.execute("SELECT total_cents FROM orders WHERE order_id = 3").fetchone()[0]
    assert total == 345000


def test_money_has_no_float_drift(db):
    load_csvs(db, ROOT / "data")
    price = db.execute("SELECT price_cents FROM products WHERE product_id = 83").fetchone()[0]
    assert price == 42990


def test_specs_become_filter_columns(db):
    load_csvs(db, ROOT / "data")
    row = db.execute(
        "SELECT strings_type, electronics FROM products WHERE product_id = 107"
    ).fetchone()
    assert tuple(row) == ("steel", 1)
