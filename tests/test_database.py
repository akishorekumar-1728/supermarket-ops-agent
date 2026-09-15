"""
tests/test_database.py  -  Persistence layer verification
"""
from __future__ import annotations

import sqlite3, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import PRODUCTS, seed


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("db") / "test_supermarket.db"


@pytest.fixture(scope="module")
def conn(db_path):
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


class TestPragmas:
    def test_wal_mode_enabled(self, conn):
        row = conn.execute("PRAGMA journal_mode;").fetchone()
        assert row[0] == "wal", f"Expected WAL, got: {row[0]}"

    def test_foreign_keys_enabled(self, conn):
        row = conn.execute("PRAGMA foreign_keys;").fetchone()
        assert row[0] == 1, "FK should be ON"


class TestSchemaExists:
    @pytest.mark.parametrize("table", [
        "products", "stock", "bills", "bill_items",
        "khata_customers", "khata_transactions", "preferences",
    ])
    def test_table_exists(self, conn, table):
        sql = "SELECT name FROM sqlite_master WHERE type=" + repr("table") + " AND name=?"
        rows = _q(conn, sql, (table,))
        assert len(rows) == 1, f"Table {table!r} not found"


class TestProductCount:
    def test_all_products_seeded(self, conn):
        n = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        assert n == len(PRODUCTS), f"Expected {len(PRODUCTS)}, got {n}"


class TestProductFields:
    def test_products_have_required_fields(self, conn):
        sql = (
            "SELECT id, sku, name, unit, cost_price, selling_price, mrp, "
            "gst_rate, hsn_code, reorder_level, created_at, updated_at "
            "FROM products"
        )
        rows = _q(conn, sql)
        assert len(rows) == len(PRODUCTS)
        for row in rows:
            assert row["id"] is not None
            assert isinstance(row["sku"], str) and row["sku"]
            assert isinstance(row["name"], str) and row["name"]
            assert isinstance(row["unit"], str) and row["unit"]
            assert row["cost_price"] >= 0
            assert row["selling_price"] >= 0
            assert row["mrp"] >= 0
            assert 0 <= row["gst_rate"] <= 100
            assert row["hsn_code"] is not None
            assert row["reorder_level"] >= 0
            assert row["created_at"] is not None
            assert row["updated_at"] is not None

    @pytest.mark.parametrize("sku,xgst", [
        ("LOOS-SUGR-KG",   0.0),
        ("LOOS-RICE-KG",   0.0),
        ("LOOS-TOOR-KG",   0.0),
        ("AASH-ATTA-5KG",  5.0),
        ("TATA-SALT-1KG",  5.0),
        ("MAGI-NOODL-70G", 5.0),
        ("PARL-G-BSCT",    5.0),
        ("FORT-OIL-1L",    5.0),
        ("AMUL-BUTR-100G", 12.0),
        ("SURF-EXCE-1KG",  18.0),
    ])
    def test_gst_rate_per_product(self, conn, sku, xgst):
        row = conn.execute("SELECT gst_rate FROM products WHERE sku=?", (sku,)).fetchone()
        assert row is not None, f"SKU {sku!r} not found"
        assert row["gst_rate"] == xgst, f"{sku}: got {row[chr(39)+'gst_rate'+chr(39)]}, want {xgst}"

    @pytest.mark.parametrize("sku", [p.sku for p in PRODUCTS])
    def test_sku_is_unique(self, conn, sku):
        rows = _q(conn, "SELECT id FROM products WHERE sku=?", (sku,))
        assert len(rows) == 1, f"Duplicate SKU: {sku}"


class TestStockRows:
    def test_stock_count_matches_products(self, conn):
        sn = conn.execute("SELECT COUNT(*) AS n FROM stock").fetchone()["n"]
        pn = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        assert sn == pn, f"stock={sn}, products={pn}"

    def test_stock_quantities_non_negative(self, conn):
        for row in _q(conn, "SELECT product_id, quantity FROM stock"):
            assert row["quantity"] >= 0, f"Negative qty for pid={row['product_id']}"

    def test_stock_fk_valid(self, conn):
        orphans = _q(conn,
            "SELECT s.product_id FROM stock s "
            "LEFT JOIN products p ON p.id=s.product_id WHERE p.id IS NULL"
        )
        assert len(orphans) == 0, "Orphan stock rows"

    def test_initial_stock_values(self, conn):
        from database.seed import PRODUCTS as seeds
        for p in seeds:
            row = conn.execute(
                "SELECT s.quantity FROM stock s "
                "JOIN products pr ON pr.id=s.product_id WHERE pr.sku=?",
                (p.sku,)
            ).fetchone()
            assert row is not None, f"No stock for {p.sku}"
            qty = row["quantity"]
            assert qty == p.initial_stock, f"{p.sku}: want {p.initial_stock}, got {qty}"


class TestLowStock:
    def test_low_stock_detected(self, conn):
        expected = {
            "AASH-ATTA-5KG", "TATA-SALT-1KG", "MAGI-NOODL-70G",
            "AMUL-BUTR-100G", "SURF-EXCE-1KG", "LOOS-RICE-KG",
        }
        rows = _q(conn,
            "SELECT p.sku FROM stock s "
            "JOIN products p ON p.id=s.product_id "
            "WHERE s.quantity <= p.reorder_level"
        )
        got = {r["sku"] for r in rows}
        assert got == expected, f"want={sorted(expected)} got={sorted(got)}"


class TestForeignKeyEnforcement:
    def test_bad_stock_product_id_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO stock(product_id, quantity) VALUES(99999, 10)")
            conn.commit()
        conn.rollback()

    def test_bad_bill_item_bill_id_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bill_items"
                "(bill_id, product_id, quantity, unit_price, cost_price, taxable_amount, total)"
                " VALUES(99999, 1, 1, 10, 8, 10, 10)"
            )
            conn.commit()
        conn.rollback()


class TestPreferences:
    def test_kv_insert_and_read(self, conn):
        conn.execute(
            "INSERT OR REPLACE INTO preferences(key, value) VALUES(?,?)",
            ("shop_name", "Raju Kirana Stores"),
        )
        conn.commit()
        row = conn.execute("SELECT value FROM preferences WHERE key=?", ("shop_name",)).fetchone()
        assert row["value"] == "Raju Kirana Stores"
