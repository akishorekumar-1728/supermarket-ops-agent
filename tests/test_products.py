"""
tests/test_products.py
======================
Pytest suite for tools/products.py (add_product, get_product).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.products import (
    VALID_GST_RATES,
    ValidationError,
    add_product,
    get_product,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded DB per test (function scope)."""
    db = tmp_path / "test.db"
    c = get_and_init(db)
    seed(c, clear=True)
    yield c
    c.close()


@pytest.fixture()
def fresh_conn(tmp_path):
    """Empty DB — no seed data, for add_product isolation."""
    db = tmp_path / "fresh.db"
    c = get_and_init(db)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Minimal valid kwargs helper
# ---------------------------------------------------------------------------

VALID_KWARGS = dict(
    sku="TEST-PROD-001",
    name="Test Biscuit 100g",
    unit="pkt",
    cost_price=10.0,
    selling_price=12.0,
    mrp=15.0,
    gst_rate=5.0,
    hsn_code="1905",
    reorder_level=5,
)


# ---------------------------------------------------------------------------
# add_product — happy path
# ---------------------------------------------------------------------------

class TestAddProductValid:
    def test_returns_dict_with_all_fields(self, fresh_conn):
        result = add_product(**VALID_KWARGS, conn=fresh_conn)
        assert isinstance(result, dict)
        for field in ("id", "sku", "name", "unit", "cost_price",
                      "selling_price", "mrp", "gst_rate", "hsn_code",
                      "reorder_level", "quantity"):
            assert field in result, f"Missing field: {field}"

    def test_sku_stored_correctly(self, fresh_conn):
        result = add_product(**VALID_KWARGS, conn=fresh_conn)
        assert result["sku"] == "TEST-PROD-001"

    def test_initial_stock_zero_by_default(self, fresh_conn):
        result = add_product(**VALID_KWARGS, conn=fresh_conn)
        assert result["quantity"] == 0.0

    def test_initial_stock_nonzero(self, fresh_conn):
        result = add_product(**VALID_KWARGS, conn=fresh_conn, initial_stock=50)
        assert result["quantity"] == 50.0

    def test_product_persisted_to_db(self, fresh_conn):
        add_product(**VALID_KWARGS, conn=fresh_conn)
        row = fresh_conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE sku = ?",
            ("TEST-PROD-001",),
        ).fetchone()
        assert row["n"] == 1

    def test_stock_row_created(self, fresh_conn):
        result = add_product(**VALID_KWARGS, conn=fresh_conn)
        row = fresh_conn.execute(
            "SELECT quantity FROM stock WHERE product_id = ?",
            (result["id"],),
        ).fetchone()
        assert row is not None
        assert row["quantity"] == 0.0

    def test_zero_gst_allowed(self, fresh_conn):
        kw = {**VALID_KWARGS, "sku": "LOOS-TEST-KG", "gst_rate": 0.0}
        result = add_product(**kw, conn=fresh_conn)
        assert result["gst_rate"] == 0.0

    def test_all_valid_gst_rates_accepted(self, fresh_conn):
        for i, rate in enumerate(sorted(VALID_GST_RATES)):
            kw = {**VALID_KWARGS,
                  "sku": f"SKU-GST-{i}",
                  "gst_rate": rate,
                  "cost_price": 10.0,
                  "selling_price": 10.0,
                  "mrp": 100.0}
            result = add_product(**kw, conn=fresh_conn)
            assert result["gst_rate"] == rate


# ---------------------------------------------------------------------------
# add_product — validation errors
# ---------------------------------------------------------------------------

class TestAddProductValidation:
    def test_missing_sku_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="sku"):
            add_product(**{**VALID_KWARGS, "sku": ""}, conn=fresh_conn)

    def test_none_name_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="name"):
            add_product(**{**VALID_KWARGS, "name": None}, conn=fresh_conn)

    def test_missing_unit_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="unit"):
            add_product(**{**VALID_KWARGS, "unit": "  "}, conn=fresh_conn)

    def test_negative_cost_price_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="cost_price"):
            add_product(**{**VALID_KWARGS, "cost_price": -1}, conn=fresh_conn)

    def test_selling_price_below_cost_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="selling_price"):
            add_product(
                **{**VALID_KWARGS, "cost_price": 20.0, "selling_price": 15.0, "mrp": 25.0},
                conn=fresh_conn,
            )

    def test_mrp_below_selling_price_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="mrp"):
            add_product(
                **{**VALID_KWARGS, "selling_price": 20.0, "mrp": 18.0},
                conn=fresh_conn,
            )

    def test_invalid_gst_rate_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="gst_rate"):
            add_product(**{**VALID_KWARGS, "gst_rate": 11.0}, conn=fresh_conn)

    def test_non_numeric_price_raises(self, fresh_conn):
        with pytest.raises(ValidationError):
            add_product(**{**VALID_KWARGS, "cost_price": "abc"}, conn=fresh_conn)

    def test_negative_reorder_level_raises(self, fresh_conn):
        with pytest.raises(ValidationError, match="reorder_level"):
            add_product(**{**VALID_KWARGS, "reorder_level": -3}, conn=fresh_conn)

    def test_duplicate_sku_raises_integrity_error(self, fresh_conn):
        add_product(**VALID_KWARGS, conn=fresh_conn)
        with pytest.raises(sqlite3.IntegrityError):
            add_product(**VALID_KWARGS, conn=fresh_conn)

    def test_empty_query_raises_on_get_product(self, fresh_conn):
        with pytest.raises(ValidationError):
            get_product("", fresh_conn)

    def test_none_query_raises_on_get_product(self, fresh_conn):
        with pytest.raises(ValidationError):
            get_product(None, fresh_conn)


# ---------------------------------------------------------------------------
# get_product — queries against seeded data
# ---------------------------------------------------------------------------

class TestGetProduct:
    def test_exact_sku_match(self, conn):
        results = get_product("AASH-ATTA-5KG", conn)
        assert len(results) == 1
        assert results[0]["sku"] == "AASH-ATTA-5KG"

    def test_case_insensitive_sku(self, conn):
        results = get_product("aash-atta-5kg", conn)
        assert len(results) == 1

    def test_full_name_match(self, conn):
        results = get_product("Aashirvaad Atta 5kg", conn)
        assert len(results) == 1
        assert results[0]["sku"] == "AASH-ATTA-5KG"

    def test_partial_name_match_single(self, conn):
        results = get_product("Maggi", conn)
        assert len(results) == 1
        assert results[0]["sku"] == "MAGI-NOODL-70G"

    def test_partial_name_match_multiple(self, conn):
        # "loose" matches Sugar, Rice, Toor Dal
        results = get_product("loose", conn)
        assert len(results) == 3

    def test_no_match_returns_empty_list(self, conn):
        results = get_product("NONEXISTENT-PRODUCT-XYZ", conn)
        assert results == []

    def test_result_has_quantity_field(self, conn):
        results = get_product("Tata Salt", conn)
        assert len(results) == 1
        assert "quantity" in results[0]

    def test_result_quantity_is_numeric(self, conn):
        results = get_product("Sugar", conn)
        assert isinstance(results[0]["quantity"], (int, float))

    def test_add_then_get(self, conn):
        add_product(
            sku="NEW-PROD-001",
            name="Brand New Soap 100g",
            unit="pcs",
            cost_price=15.0,
            selling_price=20.0,
            mrp=25.0,
            gst_rate=18.0,
            hsn_code="3401",
            reorder_level=10,
            conn=conn,
            initial_stock=30,
        )
        results = get_product("Brand New Soap", conn)
        assert len(results) == 1
        assert results[0]["quantity"] == 30.0
