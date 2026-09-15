"""
tests/test_finalize.py
======================
Comprehensive test suite for tools/billing.py: finalize_bill

Covering:
1. Happy path: multi-item bill finalize, stock decrements correctly, GST totals verified.
2. Oversell guard: requested qty > available stock, rejection with shortfall, stock UNCHANGED.
3. Below-cost guard: item unit_price < cost_price, rejection, stock UNCHANGED.
4. Idempotency: duplicate call with SAME idempotency_key does NOT decrement stock twice,
   returns identical invoice result.
5. Concurrency protection: concurrent finalize attempts with overlapping stock where only
   one can succeed; exactly one succeeds, the other fails cleanly, stock never goes negative.
"""
from __future__ import annotations

import concurrent.futures
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init, get_connection
from database.seed import seed
from tools.billing import (
    BelowCostSaleError,
    BillStateError,
    InsufficientStockError,
    add_bill_item,
    create_bill,
    finalize_bill,
    get_bill,
)
from tools.inventory import get_stock


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "finalize_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


@pytest.fixture()
def db_file(tmp_path):
    """Returns path to fresh seeded database file for multi-connection concurrency tests."""
    db_path = tmp_path / "concurrent_finalize.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    c.close()
    return db_path


class TestFinalizeHappyPath:
    def test_finalize_multi_item_bill(self, conn):
        # Initial stocks:
        # Tata Salt 1kg: stock 20, selling_price 22.0, cost_price 18.0, 5% GST
        # Amul Butter 100g: stock 7, selling_price 60.0, cost_price 52.0, 12% GST
        salt_initial = get_stock("Tata Salt", conn)["quantity"]
        butter_initial = get_stock("Amul Butter", conn)["quantity"]

        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 2, conn)    # 2 * 22.0 = 44.0 taxable, 2.20 GST
        add_bill_item(bill_id, "Amul Butter", 1, conn)  # 1 * 60.0 = 60.0 taxable, 7.20 GST

        idemp_key = "idemp-test-happy-1"
        finalized = finalize_bill(bill_id, idempotency_key=idemp_key, payment_mode="upi", conn=conn)

        # Header asserts
        assert finalized["status"] == "finalized"
        assert finalized["invoice_number"].startswith("INV-")
        assert finalized["payment_mode"] == "upi"
        assert finalized["finalized_at"] is not None
        assert finalized["idempotency_key"] == idemp_key

        # Subtotal & GST asserts
        # Subtotal: 44.0 + 60.0 = 104.0
        assert finalized["subtotal"] == 104.0
        # CGST: 1.10 + 3.60 = 4.70
        assert finalized["cgst_total"] == 4.70
        # SGST: 1.10 + 3.60 = 4.70
        assert finalized["sgst_total"] == 4.70
        # Total GST: 9.40
        assert finalized["gst_total"] == 9.40
        # Grand Total: 104.0 + 9.40 = 113.40
        assert finalized["grand_total"] == 113.40

        # Stock assertion: decremented by exact item amounts
        salt_after = get_stock("Tata Salt", conn)["quantity"]
        butter_after = get_stock("Amul Butter", conn)["quantity"]
        assert salt_after == salt_initial - 2
        assert butter_after == butter_initial - 1


class TestFinalizeOversellGuard:
    def test_oversell_single_item_rejected_and_stock_untouched(self, conn):
        # Amul butter has initial stock 7
        butter_stock_before = get_stock("Amul Butter", conn)["quantity"]
        assert butter_stock_before == 7.0

        bill_id = create_bill(conn)
        # Attempt to sell 8 (shortfall of 1)
        add_bill_item(bill_id, "Amul Butter", 8, conn)

        with pytest.raises(InsufficientStockError) as exc_info:
            finalize_bill(bill_id, idempotency_key="idemp-oversell-1", conn=conn)

        err_msg = str(exc_info.value)
        assert "Amul Butter" in err_msg
        assert "AMUL-BUTR-100G" in err_msg
        assert "Shortfall: 1.0" in err_msg or "shortfall" in err_msg.lower()

        # Check stock remains completely unchanged
        assert get_stock("Amul Butter", conn)["quantity"] == butter_stock_before

        # Bill remains in draft status
        bill = get_bill(bill_id, conn)
        assert bill["status"] == "draft"

    def test_oversell_second_item_reverts_all_prior_items(self, conn):
        # Tata salt has 20, Amul butter has 7
        salt_before = get_stock("Tata Salt", conn)["quantity"]
        butter_before = get_stock("Amul Butter", conn)["quantity"]

        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 5, conn)     # Valid
        add_bill_item(bill_id, "Amul Butter", 10, conn)  # Oversell! (has 7)

        with pytest.raises(InsufficientStockError):
            finalize_bill(bill_id, idempotency_key="idemp-oversell-2", conn=conn)

        # Neither product's stock should have changed
        assert get_stock("Tata Salt", conn)["quantity"] == salt_before
        assert get_stock("Amul Butter", conn)["quantity"] == butter_before


class TestFinalizeBelowCostGuard:
    def test_below_cost_sale_rejected_and_stock_untouched(self, conn):
        salt_before = get_stock("Tata Salt", conn)["quantity"]

        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 2, conn)

        # Artificially alter unit_price in bill_items to be below cost_price
        # Cost price for Tata salt is 18.0. Set selling unit_price to 15.0
        conn.execute(
            "UPDATE bill_items SET unit_price = 15.0, cost_price = 18.0 WHERE bill_id = ?",
            (bill_id,),
        )
        conn.commit()

        with pytest.raises(BelowCostSaleError) as exc_info:
            finalize_bill(bill_id, idempotency_key="idemp-below-cost-1", conn=conn)

        err_msg = str(exc_info.value)
        assert "below its cost price" in err_msg
        assert "Tata Salt" in err_msg

        # Stock must not have changed
        assert get_stock("Tata Salt", conn)["quantity"] == salt_before

        # Bill must still be draft
        bill = get_bill(bill_id, conn)
        assert bill["status"] == "draft"


class TestFinalizeIdempotency:
    def test_idempotent_duplicate_call_returns_same_result_without_double_decrement(self, conn):
        salt_initial = get_stock("Tata Salt", conn)["quantity"]

        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt", 3, conn)

        idemp_key = "idemp-unique-test-key-123"

        # First finalize
        first_result = finalize_bill(bill_id, idempotency_key=idemp_key, conn=conn)
        assert first_result["status"] == "finalized"
        invoice_num = first_result["invoice_number"]

        # Stock after 1st call
        salt_after_first = get_stock("Tata Salt", conn)["quantity"]
        assert salt_after_first == salt_initial - 3

        # Second finalize with SAME key
        second_result = finalize_bill(bill_id, idempotency_key=idemp_key, conn=conn)

        # Stock MUST NOT be decremented again
        salt_after_second = get_stock("Tata Salt", conn)["quantity"]
        assert salt_after_second == salt_after_first

        # Invoices and totals match exactly
        assert second_result["invoice_number"] == invoice_num
        assert second_result["grand_total"] == first_result["grand_total"]
        assert second_result["status"] == "finalized"


class TestFinalizeConcurrency:
    def test_concurrent_finalize_overlapping_stock_only_one_succeeds(self, db_file):
        """
        Setup: Amul Butter has 7 in stock.
        Create two distinct draft bills:
        - Bill A wants 5 units
        - Bill B wants 5 units
        Total requested = 10 > 7.
        Both bills attempt to finalize concurrently across separate threads/connections.
        Guarantees:
        - Exactly ONE bill succeeds.
        - The other bill fails (with InsufficientStockError or busy error).
        - Final stock is 7 - 5 = 2 (NEVER negative).
        """
        # Set up Bill A and Bill B using a setup connection
        init_conn = get_connection(db_file)
        bill_a_id = create_bill(init_conn)
        add_bill_item(bill_a_id, "Amul Butter", 5, init_conn)

        bill_b_id = create_bill(init_conn)
        add_bill_item(bill_b_id, "Amul Butter", 5, init_conn)

        init_conn.close()

        results = []
        errors = []

        def finalize_worker(bill_id: int, key: str):
            worker_conn = get_connection(db_file)
            try:
                res = finalize_bill(bill_id, idempotency_key=key, conn=worker_conn)
                return ("SUCCESS", res)
            except Exception as e:
                return ("ERROR", e)
            finally:
                worker_conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(finalize_worker, bill_a_id, "conc-key-A")
            fut_b = executor.submit(finalize_worker, bill_b_id, "conc-key-B")

            res_a = fut_a.result()
            res_b = fut_b.result()

        outcomes = [res_a[0], res_b[0]]
        # Exactly one must succeed
        assert outcomes.count("SUCCESS") == 1, f"Expected 1 success, got {outcomes}: {res_a}, {res_b}"
        assert outcomes.count("ERROR") == 1

        # Check the error was InsufficientStockError
        failed_res = res_a if res_a[0] == "ERROR" else res_b
        assert isinstance(failed_res[1], (InsufficientStockError, sqlite3.OperationalError))

        # Check stock in database: must be exactly 7 - 5 = 2
        verify_conn = get_connection(db_file)
        final_stock = get_stock("Amul Butter", verify_conn)["quantity"]
        verify_conn.close()

        assert final_stock == 2.0
        assert final_stock >= 0
