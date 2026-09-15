"""
tools/gst.py
============
GST calculation utilities for intra-state Indian retail sales.

Pure functions implementing precise half-up rounding (ROUND_HALF_UP)
to 2 decimal places.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import TypedDict


class GSTBreakdown(TypedDict):
    taxable_amount: float
    gst_rate: float
    cgst: float
    sgst: float
    total_gst: float
    total: float


def _round_currency(val: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_gst(taxable_amount: float | Decimal, gst_rate: float | Decimal) -> GSTBreakdown:
    """
    Calculate CGST, SGST, and total for an intra-state sale.

    Parameters:
        taxable_amount: Taxable value before GST (must be >= 0).
        gst_rate: GST rate percentage (e.g., 0, 5, 12, 18). Must be >= 0.

    Returns:
        GSTBreakdown dictionary with:
            - taxable_amount (float)
            - gst_rate (float)
            - cgst (float)
            - sgst (float)
            - total_gst (float)
            - total (float)
    """
    amt = Decimal(str(taxable_amount))
    rate = Decimal(str(gst_rate))

    if amt < 0:
        raise ValueError(f"taxable_amount must be >= 0, got {amt}")
    if rate < 0:
        raise ValueError(f"gst_rate must be >= 0, got {rate}")

    amt_rounded = _round_currency(amt)

    # For intra-state sales, GST is split equally into CGST and SGST
    half_rate = rate / Decimal("2")
    cgst = _round_currency((amt_rounded * half_rate) / Decimal("100"))
    sgst = _round_currency((amt_rounded * half_rate) / Decimal("100"))

    total_gst = cgst + sgst
    total = amt_rounded + total_gst

    return {
        "taxable_amount": float(amt_rounded),
        "gst_rate": float(rate),
        "cgst": float(cgst),
        "sgst": float(sgst),
        "total_gst": float(total_gst),
        "total": float(total),
    }
