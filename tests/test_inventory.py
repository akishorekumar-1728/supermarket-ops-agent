"""
tests/test_inventory.py
=======================
Pytest suite for tools/inventory.py
    (receive_stock, get_stock, get_low_stock).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.products import ValidationError, ProductNotFoundError, add_product
from tools.inventory import receive_stock, get_stock, get_low_stock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded DB per test."""
    db = tmp_path / "inv_test.db"
    c = get_and_init(db)
    seed(c, clear=True)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# receive_stock — happy path
# ---------------------------------------------------------------------------

class TestReceiveStock:
    def test_increments_quantity(self, conn):
        before = get_stock("Aashirvaad Atta", conn)["quantity"]
        receive_stock("Aashirvaad Atta", 20, conn)
        after = get_stock("Aashirvaad Atta", conn)["quantity"]
        assert after == before + 20

    def test_returns_updated_product_dict(self, conn):
        result = receive_stock("Tata Salt", 10, conn)
        assert isinstance(result, dict)
        for field in ("id", "sku", "name", "quantity"):
            assert field in result, f"Missing field: {field}"

    def test_quantity_reflects_new_total(self, conn):
        before = get_stock("TATA-SALT-1KG", conn)["quantity"]
        result = receive_stock("TATA-SALT-1KG", 5, conn)
        assert result["quantity"] == before + 5

    def test_fractional_quantity_for_loose_items(self, conn):
        before = get_stock("Sugar", conn)["quantity"]
        receive_stock("Sugar", 2.5, conn)
        after = get_stock("Sugar", conn)["quantity"]
        assert abs(after - (before + 2.5)) < 1e-9

    def test_updates_cost_price_when_provided(self, conn):
        receive_stock("Amul Butter", 10, conn, cost_price=55.0)
        result = get_stock("Amul Butter", conn)
        row = conn.execute(
            "SELECT cost_price FROM products WHERE id = ?",
            (result["product_id"],),
        ).fetchone()
        assert row["cost_price"] == 55.0

    def test_updates_mrp_when_provided(self, conn):
        receive_stock("Parle-G", 20, conn, mrp=52.0)
        row = conn.execute(
            "SELECT mrp FROM products p JOIN stock s ON s.product_id = p.id "
            "WHERE p.sku = 'PARL-G-BSCT'"
        ).fetchone()
        assert row["mrp"] == 52.0

    def test_stock_is_atomic_in_transaction(self, conn):
        """Two consecutive receives should accumulate."""
        receive_stock("Maggi Noodles", 10, conn)
        receive_stock("Maggi Noodles", 10, conn)
        result = get_stock("Maggi", conn)
        # seed stock was 25, +10+10 = 45
        assert result["quantity"] == 45.0


# ---------------------------------------------------------------------------
# receive_stock — validation / error paths
# ---------------------------------------------------------------------------

class TestReceiveStockErrors:
    def test_zero_quantity_raises(self, conn):
        with pytest.raises(ValidationError, match="quantity"):
            receive_stock("Tata Salt", 0, conn)

    def test_negative_quantity_raises(self, conn):
        with pytest.raises(ValidationError, match="quantity"):
            receive_stock("Tata Salt", -5, conn)

    def test_empty_product_query_raises(self, conn):
        with pytest.raises(ValidationError):
            receive_stock("", 10, conn)

    def test_unknown_product_raises(self, conn):
        with pytest.raises(ProductNotFoundError):
            receive_stock("NoSuchProductXYZ", 10, conn)

    def test_ambiguous_query_raises(self, conn):
        # "loose" matches 3 products (Sugar, Rice, Toor Dal)
        with pytest.raises(ValueError, match="Ambiguous"):
            receive_stock("loose", 10, conn)

    def test_negative_cost_price_raises(self, conn):
        with pytest.raises(ValidationError, match="cost_price"):
            receive_stock("Tata Salt", 5, conn, cost_price=-1.0)

    def test_mrp_below_cost_price_raises(self, conn):
        # current cost for Tata Salt is 18; set mrp below that
        with pytest.raises(ValidationError, match="mrp"):
            receive_stock("Tata Salt", 5, conn, cost_price=20.0, mrp=15.0)


# ---------------------------------------------------------------------------
# get_stock
# ---------------------------------------------------------------------------

class TestGetStock:
    def test_returns_dict_with_required_keys(self, conn):
        result = get_stock("Tata Salt", conn)
        for key in ("product_id", "sku", "name", "unit",
                    "quantity", "reorder_level", "is_low_stock"):
            assert key in result, f"Missing key: {key}"

    def test_correct_quantity_for_seeded_product(self, conn):
        result = get_stock("TATA-SALT-1KG", conn)
        assert result["quantity"] == 20.0

    def test_is_low_stock_true_when_at_reorder_level(self, conn):
        # Tata Salt seeded with quantity=20, reorder_level=20
        result = get_stock("Tata Salt", conn)
        assert result["is_low_stock"] is True

    def test_is_low_stock_false_when_above_reorder_level(self, conn):
        # Parle-G seeded with quantity=40, reorder_level=15
        result = get_stock("Parle-G", conn)
        assert result["is_low_stock"] is False

    def test_empty_query_raises(self, conn):
        with pytest.raises(ValidationError):
            get_stock("", conn)

    def test_unknown_product_raises(self, conn):
        with pytest.raises(ProductNotFoundError):
            get_stock("UNKNOWN-SKU-9999", conn)

    def test_ambiguous_query_raises(self, conn):
        with pytest.raises(ValueError, match="Ambiguous"):
            get_stock("loose", conn)

    def test_quantity_reflects_receive(self, conn):
        receive_stock("Fortune Sunflower Oil", 5, conn)
        result = get_stock("Fortune Sunflower Oil", conn)
        assert result["quantity"] == 18 + 5  # seed stock was 18


# ---------------------------------------------------------------------------
# get_low_stock
# ---------------------------------------------------------------------------

class TestGetLowStock:
    def test_returns_list(self, conn):
        result = get_low_stock(conn)
        assert isinstance(result, list)

    def test_expected_low_stock_skus(self, conn):
        result = get_low_stock(conn)
        low_skus = {r["sku"] for r in result}
        expected = {
            "AASH-ATTA-5KG",   # 8  <= 10
            "TATA-SALT-1KG",   # 20 <= 20
            "MAGI-NOODL-70G",  # 25 <= 30
            "AMUL-BUTR-100G",  # 7  <= 10
            "SURF-EXCE-1KG",   # 5  <=  8
            "LOOS-RICE-KG",    # 15 <= 25
        }
        assert low_skus == expected

    def test_result_has_shortfall_field(self, conn):
        result = get_low_stock(conn)
        for item in result:
            assert "shortfall" in item
            assert item["shortfall"] >= 0

    def test_sorted_by_shortfall_descending(self, conn):
        result = get_low_stock(conn)
        shortfalls = [r["shortfall"] for r in result]
        assert shortfalls == sorted(shortfalls, reverse=True)

    def test_receiving_stock_removes_from_low_list(self, conn):
        # Aashirvaad Atta: stock=8, reorder=10 → low.
        # Receive 5 → stock=13 > 10 → should no longer appear.
        receive_stock("Aashirvaad Atta", 5, conn)
        result = get_low_stock(conn)
        skus = {r["sku"] for r in result}
        assert "AASH-ATTA-5KG" not in skus

    def test_empty_list_when_all_stock_adequate(self, conn):
        # Receive enough for every low-stock item
        low_items = get_low_stock(conn)
        for item in low_items:
            receive_stock(item["sku"], item["shortfall"] + 1, conn)
        result = get_low_stock(conn)
        assert result == []

    def test_new_product_below_reorder_appears(self, conn):
        add_product(
            sku="NEW-LOW-001",
            name="Low Stock Widget",
            unit="pcs",
            cost_price=5.0,
            selling_price=8.0,
            mrp=10.0,
            gst_rate=18.0,
            hsn_code="3926",
            reorder_level=50,
            conn=conn,
            initial_stock=3,   # well below 50
        )
        result = get_low_stock(conn)
        skus = {r["sku"] for r in result}
        assert "NEW-LOW-001" in skus
