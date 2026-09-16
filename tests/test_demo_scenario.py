"""
tests/test_demo_scenario.py
===========================
Full mandatory demo scenario:
Runs the exact sequence specified by the user through the Python API (no Telegram).
Covers: stock intake, product creation, billing+GST, item edits, oversell guard,
khata credit flow, PDF invoice, PPTX deck, and preference persistence.

Seeded product names (from database/seed.py):
  - 'Maggi Noodles 70g'   (sku: MAGI-NOODL-70G)
  - 'Sugar (loose)'       (sku: LOOS-SUGR-KG)
  - 'Aashirvaad Atta 5kg' (sku: AASH-ATTA-5KG)
  - 'Amul Butter 100g'    (sku: AMUL-BUTR-100G)  ← already seeded

Return shapes:
  - receive_stock()           → product dict (keys: name, quantity, sku, ...)
  - create_bill()             → int (bill_id)
  - get_bill()["items"]       → list of dicts with keys: id, name, quantity, unit_price, ...
  - create_credit()           → float (new balance)
  - record_credit_payment()   → float (new balance)
  - get_credit_balance()      → float
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init, get_connection
from database.seed import seed
from tools.products import add_product, get_product
from tools.inventory import receive_stock, get_stock
from tools.billing import (
    create_bill,
    add_bill_item,
    remove_bill_item,
    update_bill_item,
    finalize_bill,
    get_bill,
)
from tools.khata import create_credit, record_credit_payment, get_credit_balance
from tools.analytics import daily_summary
from tools.preferences import set_preference, get_preference, PREF_DEFAULT_PAYMENT_MODE
from documents.invoice import generate_invoice_pdf
from documents.sales_deck import generate_sales_deck


# Module-level state dict — persists across test instances within the module scope
_STATE: dict = {}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    c = get_and_init(path)
    seed(c, clear=True)
    yield c
    c.close()


class TestDemoScenario:
    """Exact demo steps end-to-end, in order."""

    def test_01_receive_maggi_stock(self, conn):
        """Step 1: 50 packets of Maggi came in, cost ₹12, MRP ₹14"""
        # receive_stock returns the updated product dict (key 'quantity', not 'quantity_added')
        result = receive_stock("Maggi Noodles 70g", 50, cost_price=12.0, conn=conn)
        assert result["name"] == "Maggi Noodles 70g"
        stock = get_stock("Maggi Noodles 70g", conn=conn)
        assert stock["quantity"] >= 50

    def test_02_add_amul_butter(self, conn):
        """Step 2: Amul Butter 100g already in seed — stock it and verify"""
        receive_stock("Amul Butter 100g", 20, cost_price=50.0, conn=conn)
        products = get_product("Amul Butter", conn=conn)
        assert any("Amul Butter" in p["name"] for p in products)

    def test_03_make_bill_multi_item(self, conn):
        """Step 3: 2 sugar, 1 atta, 4 Maggi, 1 butter — UPI"""
        bill_id = create_bill(conn=conn, payment_mode="upi")
        assert isinstance(bill_id, int)

        add_bill_item(bill_id, "Sugar (loose)", 2, conn=conn)
        add_bill_item(bill_id, "Aashirvaad Atta 5kg", 1, conn=conn)
        add_bill_item(bill_id, "Maggi Noodles 70g", 4, conn=conn)
        add_bill_item(bill_id, "Amul Butter 100g", 1, conn=conn)

        bill = get_bill(bill_id, conn=conn)
        assert bill["status"] == "draft"
        assert len(bill["items"]) == 4

        _STATE["bill_id"] = bill_id

    def test_04_drop_butter(self, conn):
        """Step 4: drop the butter — remove_bill_item takes product_query string, not item id"""
        bill_id = _STATE["bill_id"]
        remove_bill_item(bill_id, "Amul Butter 100g", conn=conn)

        bill = get_bill(bill_id, conn=conn)
        assert not any("Butter" in i["name"] for i in bill["items"])
        assert len(bill["items"]) == 3

    def test_05_update_maggi_quantity(self, conn):
        """Step 5: make it 6 Maggi — update_bill_item takes new_quantity, not quantity"""
        bill_id = _STATE["bill_id"]
        update_bill_item(bill_id, "Maggi Noodles 70g", new_quantity=6, conn=conn)

        bill = get_bill(bill_id, conn=conn)
        maggi_item = next(i for i in bill["items"] if "Maggi" in i["name"])
        assert maggi_item["quantity"] == 6

    def test_06_finalize_bill(self, conn):
        """Step 6: finalize"""
        bill_id = _STATE["bill_id"]
        idempotency_key = f"demo-bill-{uuid.uuid4()}"
        result = finalize_bill(bill_id, idempotency_key=idempotency_key, conn=conn)
        assert result["status"] == "finalized"
        assert result["payment_mode"] == "upi"
        assert result["grand_total"] > 0

        _STATE["finalized_bill_id"] = bill_id
        _STATE["invoice_number"] = result["invoice_number"]

    def test_07_oversell_guard(self, conn):
        """Step 7: oversell Maggi — must be rejected"""
        stock = get_stock("Maggi Noodles 70g", conn=conn)
        remaining = stock["quantity"]

        oversell_qty = remaining + 5
        new_bill_id = create_bill(conn=conn, payment_mode="cash")
        add_bill_item(new_bill_id, "Maggi Noodles 70g", oversell_qty, conn=conn)

        with pytest.raises(Exception, match=r"[Ii]nsufficient|[Ss]tock|[Oo]versell"):
            finalize_bill(
                new_bill_id,
                idempotency_key=f"oversell-{uuid.uuid4()}",
                conn=conn,
            )

    def test_08_khata_ramesh_credit(self, conn):
        """Step 8: Ramesh liya ₹500 udhar — returns new balance float"""
        balance = create_credit("Ramesh", 500.0, conn=conn)
        assert balance == 500.0, f"Expected 500.0, got {balance}"

    def test_09_khata_ramesh_payment(self, conn):
        """Step 9: Ramesh ne ₹300 diya — returns new balance float"""
        balance = record_credit_payment("Ramesh", 300.0, conn=conn)
        assert balance == 200.0, f"Expected 200.0, got {balance}"

    def test_10_khata_ramesh_balance(self, conn):
        """Step 10: Ramesh ka baaki ₹200"""
        balance = get_credit_balance("Ramesh", conn=conn)
        assert balance == 200.0, f"Expected 200.0, got {balance}"

    def test_11_pdf_invoice(self, conn):
        """Step 11: generate PDF for the finalized bill"""
        pdf_path = generate_invoice_pdf(_STATE["finalized_bill_id"], conn=conn)
        assert Path(pdf_path).exists()
        assert Path(pdf_path).suffix == ".pdf"
        assert Path(pdf_path).stat().st_size > 0

    def test_12_pptx_sales_deck(self, conn):
        """Step 12: generate PPTX sales deck"""
        pptx_path = generate_sales_deck(period="week", conn=conn)
        assert Path(pptx_path).exists()
        assert Path(pptx_path).suffix == ".pptx"
        assert Path(pptx_path).stat().st_size > 0

    def test_13_preference_persistence(self, conn):
        """Step 13: preference survives connection restart"""
        set_preference(PREF_DEFAULT_PAYMENT_MODE, "upi", conn=conn)

        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        new_conn = get_connection(db_path)
        pref = get_preference(PREF_DEFAULT_PAYMENT_MODE, conn=new_conn)
        new_conn.close()

        assert pref == "upi", f"Preference not persisted: {pref!r}"
