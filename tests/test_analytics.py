"""
tests/test_analytics.py
=======================
Pytest suite for tools/analytics.py (daily_summary).

Verifies purely SQL-derived daily analytics:
- Finalizes test bills with different payment modes (cash, UPI, card).
- Tests different products and quantities.
- Asserts calculated metrics match exact hand-calculated expected values.
- Tests date filtering and default today date handling.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.analytics import daily_summary
from tools.billing import add_bill_item, create_bill, finalize_bill


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "analytics_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


class TestDailySummary:
    def test_daily_summary_hand_calculated_match(self, conn):
        """
        Create and finalize 3 distinct bills with known products and payment modes:

        Bill 1 (Cash):
        - Tata Salt 1kg: 2 units @ ₹22.0 = ₹44.0 taxable, 5% GST -> ₹1.10 CGST, ₹1.10 SGST, ₹46.20 total.
        - Parle-G: 1 unit @ ₹45.0 = ₹45.0 taxable, 5% GST -> ₹1.13 CGST, ₹1.13 SGST, ₹47.26 total.
        Bill 1 Total: Subtotal ₹89.0, CGST ₹2.23, SGST ₹2.23, Total GST ₹4.46, Grand Total ₹93.46.

        Bill 2 (UPI):
        - Fortune Sunflower Oil 1L: 2 units @ ₹150.0 = ₹300.0 taxable, 5% GST -> ₹7.50 CGST, ₹7.50 SGST, ₹315.00 total.
        Bill 2 Total: Subtotal ₹300.0, CGST ₹7.50, SGST ₹7.50, Total GST ₹15.00, Grand Total ₹315.00.

        Bill 3 (Card):
        - Sugar (loose): 2.5 kg @ ₹44.0 = ₹110.0 taxable, 0% GST -> ₹0 CGST, ₹0 SGST, ₹110.00 total.
        - Tata Salt 1kg: 1 unit @ ₹22.0 = ₹22.0 taxable, 5% GST -> ₹0.55 CGST, ₹0.55 SGST, ₹23.10 total.
        Bill 3 Total: Subtotal ₹132.0, CGST ₹0.55, SGST ₹0.55, Total GST ₹1.10, Grand Total ₹133.10.

        Total Aggregations:
        - Total Finalized Bills: 3
        - Subtotal: 89.0 + 300.0 + 132.0 = ₹521.00
        - CGST Total: 2.23 + 7.50 + 0.55 = ₹10.28
        - SGST Total: 2.23 + 7.50 + 0.55 = ₹10.28
        - GST Total: 4.46 + 15.00 + 1.10 = ₹20.56
        - Grand Total (Total Sales): 93.46 + 315.00 + 133.10 = ₹541.56

        Payment Modes:
        - cash: 1 bill, ₹93.46
        - upi: 1 bill, ₹315.00
        - card: 1 bill, ₹133.10

        Products Quantities & Revenues:
        - Tata Salt 1kg: 3 units (Bill 1: 2, Bill 3: 1), Revenue: 46.20 + 23.10 = ₹69.30
        - Sugar (loose): 2.5 units, Revenue: ₹110.00
        - Fortune Oil 1L: 2 units, Revenue: ₹315.00
        - Parle-G: 1 unit, Revenue: ₹47.26
        """
        # Bill 1
        b1 = create_bill(conn)
        add_bill_item(b1, "Tata Salt 1kg", 2, conn)
        add_bill_item(b1, "Parle-G", 1, conn)
        finalize_bill(b1, idempotency_key="summary-b1", payment_mode="cash", conn=conn)

        # Bill 2
        b2 = create_bill(conn)
        add_bill_item(b2, "Fortune Sunflower Oil", 2, conn)
        finalize_bill(b2, idempotency_key="summary-b2", payment_mode="upi", conn=conn)

        # Bill 3
        b3 = create_bill(conn)
        add_bill_item(b3, "Sugar (loose)", 2.5, conn)
        add_bill_item(b3, "Tata Salt 1kg", 1, conn)
        finalize_bill(b3, idempotency_key="summary-b3", payment_mode="card", conn=conn)

        # Also create a draft bill that is NOT finalized (should NOT be included)
        draft_b = create_bill(conn)
        add_bill_item(draft_b, "Amul Butter", 2, conn)

        # Execute daily_summary (defaults to today)
        res = daily_summary(conn=conn)

        # Assert totals
        assert res["total_bills"] == 3
        assert res["total_subtotal"] == 521.00
        assert res["gst_summary"]["cgst_total"] == 10.28
        assert res["gst_summary"]["sgst_total"] == 10.28
        assert res["gst_summary"]["total_gst"] == 20.56
        assert res["total_sales"] == 541.56

        # Assert payment modes
        p_modes = res["payment_modes"]
        assert "cash" in p_modes
        assert p_modes["cash"]["bill_count"] == 1
        assert p_modes["cash"]["total_amount"] == 93.46

        assert "upi" in p_modes
        assert p_modes["upi"]["bill_count"] == 1
        assert p_modes["upi"]["total_amount"] == 315.00

        assert "card" in p_modes
        assert p_modes["card"]["bill_count"] == 1
        assert p_modes["card"]["total_amount"] == 133.10

        # Assert top selling products by quantity
        top_qty = res["top_products_by_quantity"]
        assert len(top_qty) == 4
        # Tata Salt had 3 units sold
        assert top_qty[0]["sku"] == "TATA-SALT-1KG"
        assert top_qty[0]["total_quantity"] == 3.0
        assert top_qty[0]["total_revenue"] == 69.30

        # Sugar had 2.5 kg sold
        assert top_qty[1]["sku"] == "LOOS-SUGR-KG"
        assert top_qty[1]["total_quantity"] == 2.5
        assert top_qty[1]["total_revenue"] == 110.00

        # Fortune Oil had 2 units sold
        assert top_qty[2]["sku"] == "FORT-OIL-1L"
        assert top_qty[2]["total_quantity"] == 2.0

        # Parle-G had 1 unit sold
        assert top_qty[3]["sku"] == "PARL-G-BSCT"
        assert top_qty[3]["total_quantity"] == 1.0

        # Assert top selling products by revenue
        top_rev = res["top_products_by_revenue"]
        assert len(top_rev) == 4
        # Fortune Oil brought ₹315.00
        assert top_rev[0]["sku"] == "FORT-OIL-1L"
        assert top_rev[0]["total_revenue"] == 315.00

        # Sugar brought ₹110.00
        assert top_rev[1]["sku"] == "LOOS-SUGR-KG"
        assert top_rev[1]["total_revenue"] == 110.00

        # Tata Salt brought ₹69.30
        assert top_rev[2]["sku"] == "TATA-SALT-1KG"
        assert top_rev[2]["total_revenue"] == 69.30

        # Parle-G brought ₹47.26
        assert top_rev[3]["sku"] == "PARL-G-BSCT"
        assert top_rev[3]["total_revenue"] == 47.26

    def test_daily_summary_empty_day(self, conn):
        """No finalized bills on this past date."""
        res = daily_summary(date="2020-01-01", conn=conn)
        assert res["date"] == "2020-01-01"
        assert res["total_bills"] == 0
        assert res["total_sales"] == 0.0
        assert res["gst_summary"]["total_gst"] == 0.0
        assert res["payment_modes"] == {}
        assert res["top_products_by_quantity"] == []
        assert res["top_products_by_revenue"] == []

    def test_daily_summary_accepts_date_object(self, conn):
        today = datetime.date.today()
        res = daily_summary(date=today, conn=conn)
        assert res["date"] == today.strftime("%Y-%m-%d")
