"""
tests/test_sales_deck.py
========================
Pytest suite for documents/sales_deck.py (generate_sales_deck).

Verifies:
- Seeds finalized bills across a date range.
- Generates a .pptx file in generated/.
- Asserts file exists, is non-empty, and can be opened by python-pptx.
- Asserts sensible number of slides (7 slides).
- Asserts embedded images/charts are present in the presentation shapes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from pptx import Presentation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.billing import add_bill_item, create_bill, finalize_bill
from documents.sales_deck import generate_sales_deck


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "sales_deck_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)

    # Seed multiple finalized bills with different payment modes
    b1 = create_bill(c)
    add_bill_item(b1, "Tata Salt 1kg", 3, c)
    add_bill_item(b1, "Amul Butter", 2, c)
    finalize_bill(b1, idempotency_key="deck-test-b1", payment_mode="cash", conn=c)

    b2 = create_bill(c)
    add_bill_item(b2, "Fortune Sunflower Oil", 2, c)
    finalize_bill(b2, idempotency_key="deck-test-b2", payment_mode="upi", conn=c)

    b3 = create_bill(c)
    add_bill_item(b3, "Sugar (loose)", 5, c)
    finalize_bill(b3, idempotency_key="deck-test-b3", payment_mode="card", conn=c)

    yield c
    c.close()


class TestGenerateSalesDeck:
    def test_generate_sales_deck_creates_valid_pptx(self, conn, tmp_path):
        file_path = generate_sales_deck(period="week", conn=conn, output_dir=tmp_path)

        # 1. Assert file exists and is non-empty
        assert os.path.exists(file_path)
        assert os.path.getsize(file_path) > 5000  # valid pptx file is at least a few KB

        # 2. Open via python-pptx
        prs = Presentation(file_path)

        # 3. Assert slide count (Title, Sales Summary, GST, Payment, Top Products, Stock Health, Insights)
        assert len(prs.slides) == 7

        # 4. Assert embedded images are present on slides 4 & 5 (Payment chart & Top products chart)
        images_found = 0
        for slide in prs.slides:
            for shape in slide.shapes:
                if shape.shape_type == 13:  # 13 = MSO_SHAPE_TYPE.PICTURE
                    images_found += 1

        assert images_found >= 2, f"Expected at least 2 embedded chart images, found {images_found}"

    def test_generate_sales_deck_empty_data(self, tmp_path):
        # Empty DB (no finalized bills)
        db_path = tmp_path / "empty_deck.db"
        c = get_and_init(db_path)
        seed(c, clear=True)

        file_path = generate_sales_deck(period="day", conn=c, output_dir=tmp_path)
        c.close()

        assert os.path.exists(file_path)
        prs = Presentation(file_path)
        assert len(prs.slides) == 7
