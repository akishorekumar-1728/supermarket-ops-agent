"""
tests/test_billing.py
=====================
Pytest suite for tools/billing.py:
- create_bill
- add_bill_item
- remove_bill_item
- update_bill_item
- verify stock quantities remain strictly untouched during draft operations
- verify operations on finalized bills are rejected
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.billing import (
    BillNotFoundError,
    BillStateError,
    add_bill_item,
    create_bill,
    get_bill,
    remove_bill_item,
    update_bill_item,
)
from tools.products import ProductNotFoundError, ValidationError


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "billing_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


def get_all_stock_snapshot(conn) -> dict[int, float]:
    """Helper to take snapshot of all product_id -> quantity in stock table."""
    rows = conn.execute("SELECT product_id, quantity FROM stock").fetchall()
    return {row["product_id"]: row["quantity"] for row in rows}


class TestCreateBill:
    def test_creates_draft_bill(self, conn):
        bill_id = create_bill(conn, payment_mode="cash")
        assert isinstance(bill_id, int)
        bill = get_bill(bill_id, conn)
        assert bill["status"] == "draft"
        assert bill["payment_mode"] == "cash"
        assert bill["subtotal"] == 0.0
        assert bill["grand_total"] == 0.0
        assert bill["items"] == []

    def test_creates_bill_with_defaults(self, conn):
        bill_id = create_bill(conn)
        bill = get_bill(bill_id, conn)
        assert bill["status"] == "draft"
        assert bill["payment_mode"] is None
        assert bill["invoice_number"].startswith("INV-")


class TestAddBillItem:
    def test_add_single_item(self, conn):
        bill_id = create_bill(conn)
        # Tata Salt 1kg: selling_price=22.0, gst_rate=5%
        # 2 units -> taxable = 44.0. 5% GST -> CGST 1.10, SGST 1.10, Total 46.20
        res = add_bill_item(bill_id, "Tata Salt 1kg", 2, conn)
        assert res["sku"] == "TATA-SALT-1KG"
        assert res["quantity"] == 2.0
        assert res["unit_price"] == 22.0
        assert res["taxable_amount"] == 44.0
        assert res["gst_rate"] == 5.0
        assert res["cgst_amount"] == 1.10
        assert res["sgst_amount"] == 1.10
        assert res["total"] == 46.20

        # Bill running totals check
        bill = get_bill(bill_id, conn)
        assert bill["subtotal"] == 44.0
        assert bill["cgst_total"] == 1.10
        assert bill["sgst_total"] == 1.10
        assert bill["gst_total"] == 2.20
        assert bill["grand_total"] == 46.20
        assert len(bill["items"]) == 1

    def test_add_multiple_items_running_totals(self, conn):
        bill_id = create_bill(conn)

        # 1) Tata Salt: 1 unit @ 22.0, 5% GST -> taxable 22.0, CGST 0.55, SGST 0.55, total 23.10
        add_bill_item(bill_id, "Tata Salt", 1, conn)

        # 2) Amul Butter 100g: 2 units @ 60.0, 12% GST -> taxable 120.0, CGST 7.20, SGST 7.20, total 134.40
        add_bill_item(bill_id, "Amul Butter", 2, conn)

        # 3) Loose Sugar: 1.5 kg @ 44.0, 0% GST -> taxable 66.0, CGST 0, SGST 0, total 66.00
        add_bill_item(bill_id, "Sugar (loose)", 1.5, conn)

        bill = get_bill(bill_id, conn)
        assert len(bill["items"]) == 3
        # Subtotal: 22.0 + 120.0 + 66.0 = 208.0
        assert bill["subtotal"] == 208.0
        # CGST: 0.55 + 7.20 + 0 = 7.75
        assert bill["cgst_total"] == 7.75
        # SGST: 0.55 + 7.20 + 0 = 7.75
        assert bill["sgst_total"] == 7.75
        # Total GST: 15.50
        assert bill["gst_total"] == 15.50
        # Grand Total: 208.0 + 15.50 = 223.50
        assert bill["grand_total"] == 223.50

    def test_add_invalid_quantity_raises(self, conn):
        bill_id = create_bill(conn)
        with pytest.raises(ValidationError, match="Quantity must be > 0"):
            add_bill_item(bill_id, "Tata Salt", 0, conn)

        with pytest.raises(ValidationError, match="Quantity must be > 0"):
            add_bill_item(bill_id, "Tata Salt", -2, conn)

    def test_add_nonexistent_product_raises(self, conn):
        bill_id = create_bill(conn)
        with pytest.raises(ProductNotFoundError):
            add_bill_item(bill_id, "Nonexistent Item XYZ", 1, conn)

    def test_add_ambiguous_query_raises(self, conn):
        bill_id = create_bill(conn)
        with pytest.raises(ValueError, match="Ambiguous"):
            add_bill_item(bill_id, "loose", 1, conn)


class TestRemoveBillItem:
    def test_remove_item_updates_totals(self, conn):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 1, conn)
        add_bill_item(bill_id, "Amul Butter", 1, conn)

        bill_before = get_bill(bill_id, conn)
        assert len(bill_before["items"]) == 2

        # Remove Tata Salt
        res = remove_bill_item(bill_id, "Tata Salt", conn)
        assert res["sku"] == "TATA-SALT-1KG"

        bill_after = get_bill(bill_id, conn)
        assert len(bill_after["items"]) == 1
        # Only Amul butter remains: 60.0 taxable + 7.20 GST = 67.20
        assert bill_after["subtotal"] == 60.0
        assert bill_after["cgst_total"] == 3.60
        assert bill_after["sgst_total"] == 3.60
        assert bill_after["gst_total"] == 7.20
        assert bill_after["grand_total"] == 67.20

    def test_remove_nonexistent_item_in_bill_raises(self, conn):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 1, conn)
        with pytest.raises(LookupError, match="is not in bill"):
            remove_bill_item(bill_id, "Amul Butter", conn)


class TestUpdateBillItem:
    def test_update_quantity_recalculates_totals(self, conn):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 1, conn)

        # Update to 3 units (22 * 3 = 66 taxable, 5% GST -> 1.65 CGST, 1.65 SGST, 69.30 total)
        res = update_bill_item(bill_id, "Tata Salt", 3, conn)
        assert res["quantity"] == 3.0
        assert res["taxable_amount"] == 66.0
        assert res["cgst_amount"] == 1.65
        assert res["sgst_amount"] == 1.65
        assert res["total"] == 69.30

        bill = get_bill(bill_id, conn)
        assert bill["subtotal"] == 66.0
        assert bill["grand_total"] == 69.30

    def test_update_invalid_quantity_raises(self, conn):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 1, conn)
        with pytest.raises(ValidationError, match="Quantity must be > 0"):
            update_bill_item(bill_id, "Tata Salt", -1, conn)

    def test_update_item_not_in_bill_raises(self, conn):
        bill_id = create_bill(conn)
        with pytest.raises(LookupError, match="is not in bill"):
            update_bill_item(bill_id, "Tata Salt", 2, conn)


class TestStockProtection:
    def test_stock_remains_unchanged_across_all_draft_operations(self, conn):
        """
        Stock table must NOT move when:
        - creating a bill
        - adding items
        - updating quantities
        - removing items
        """
        stock_before = get_all_stock_snapshot(conn)

        # 1. Create draft
        bill_id = create_bill(conn)
        assert get_all_stock_snapshot(conn) == stock_before

        # 2. Add multiple items
        add_bill_item(bill_id, "Tata Salt", 5, conn)
        add_bill_item(bill_id, "Aashirvaad Atta", 2, conn)
        add_bill_item(bill_id, "Amul Butter", 3, conn)
        assert get_all_stock_snapshot(conn) == stock_before

        # 3. Update quantity
        update_bill_item(bill_id, "Tata Salt", 10, conn)
        assert get_all_stock_snapshot(conn) == stock_before

        # 4. Remove item
        remove_bill_item(bill_id, "Amul Butter", conn)
        assert get_all_stock_snapshot(conn) == stock_before

        # Final check
        stock_after = get_all_stock_snapshot(conn)
        assert stock_after == stock_before


class TestFinalizedBillGuards:
    def test_cannot_modify_finalized_bill(self, conn):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 1, conn)

        # Manually finalize bill
        conn.execute(
            "UPDATE bills SET status = 'finalized', finalized_at = '2026-09-15T12:00:00Z' WHERE id = ?",
            (bill_id,),
        )
        conn.commit()

        # Add item should reject
        with pytest.raises(BillStateError, match="Cannot modify bill"):
            add_bill_item(bill_id, "Amul Butter", 1, conn)

        # Update item should reject
        with pytest.raises(BillStateError, match="Cannot modify bill"):
            update_bill_item(bill_id, "Tata Salt", 5, conn)

        # Remove item should reject
        with pytest.raises(BillStateError, match="Cannot modify bill"):
            remove_bill_item(bill_id, "Tata Salt", conn)

    def test_nonexistent_bill_raises(self, conn):
        with pytest.raises(BillNotFoundError):
            add_bill_item(99999, "Tata Salt", 1, conn)
