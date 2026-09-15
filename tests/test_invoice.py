"""
tests/test_invoice.py
=====================
Pytest suite for documents/invoice.py (generate_invoice_pdf).

Verifies:
- Generating a PDF invoice for a finalized bill creates a valid PDF file.
- The output file starts with '%PDF'.
- Text extraction (via pypdf) confirms store name, invoice number, line items,
  GST numbers, and grand total appear in the PDF content.
- Generates successfully using both integer bill_id and string invoice_number.
- Attempting to generate an invoice for a draft/unfinalized bill raises BillStateError.
- Generating for a nonexistent bill raises BillNotFoundError.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.billing import add_bill_item, create_bill, finalize_bill, BillStateError, BillNotFoundError
from tools.preferences import set_preference
from documents.invoice import generate_invoice_pdf


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "invoice_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


class TestGenerateInvoicePDF:
    def test_happy_path_pdf_generation_and_content(self, conn, tmp_path):
        # Configure store preferences
        set_preference("store_name", "Lakshmi Supermarket", conn=conn)
        set_preference("gstin", "33AAAAA0000A1Z5", conn=conn)

        # Create and finalize a bill
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt 1kg", 2, conn)    # 2 * 22 = 44 + 5% GST (2.20) = 46.20
        add_bill_item(bill_id, "Amul Butter", 1, conn)      # 1 * 60 = 60 + 12% GST (7.20) = 67.20
        finalized = finalize_bill(bill_id, idempotency_key="pdf-test-1", payment_mode="upi", conn=conn)

        invoice_number = finalized["invoice_number"]
        grand_total = finalized["grand_total"]  # 46.20 + 67.20 = 113.40

        # Generate PDF to temporary directory
        pdf_path = generate_invoice_pdf(bill_id, conn=conn, output_dir=tmp_path)

        # 1. Assert file exists and is non-empty
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 1000

        # 2. Assert file header is valid PDF
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            assert header.startswith(b"%PDF")

        # 3. Extract text and verify key elements
        reader = PdfReader(pdf_path)
        assert len(reader.pages) >= 1
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() or ""

        assert "Lakshmi Supermarket" in full_text
        assert "33AAAAA0000A1Z5" in full_text
        assert invoice_number in full_text
        assert "Tata Salt 1kg" in full_text
        assert "Amul Butter 100g" in full_text
        assert "113.40" in full_text
        assert "UPI" in full_text.upper()
        assert "TAX INVOICE" in full_text

    def test_lookup_by_invoice_number_string(self, conn, tmp_path):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Sugar (loose)", 2, conn)
        finalized = finalize_bill(bill_id, idempotency_key="pdf-test-2", payment_mode="cash", conn=conn)

        inv_num = finalized["invoice_number"]
        pdf_path = generate_invoice_pdf(inv_num, conn=conn, output_dir=tmp_path)

        assert os.path.exists(pdf_path)
        reader = PdfReader(pdf_path)
        text = reader.pages[0].extract_text()
        assert inv_num in text
        assert "Sugar (loose)" in text

    def test_unfinalized_draft_bill_raises_error(self, conn, tmp_path):
        bill_id = create_bill(conn)
        add_bill_item(bill_id, "Tata Salt 1kg", 1, conn)

        with pytest.raises(BillStateError, match="Bill must be finalized first"):
            generate_invoice_pdf(bill_id, conn=conn, output_dir=tmp_path)

    def test_nonexistent_bill_raises_error(self, conn, tmp_path):
        with pytest.raises(BillNotFoundError):
            generate_invoice_pdf(99999, conn=conn, output_dir=tmp_path)
