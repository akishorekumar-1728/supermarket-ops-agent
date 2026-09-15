"""
tests/test_gst.py
=================
Direct unit tests for tools/gst.py (calculate_gst).
"""
from __future__ import annotations

import pytest
from tools.gst import calculate_gst


class TestCalculateGST:
    def test_standard_5_percent(self):
        # 100 at 5% -> CGST 2.50, SGST 2.50, Total 105.00
        res = calculate_gst(100.0, 5.0)
        assert res["taxable_amount"] == 100.0
        assert res["gst_rate"] == 5.0
        assert res["cgst"] == 2.50
        assert res["sgst"] == 2.50
        assert res["total_gst"] == 5.00
        assert res["total"] == 105.00

    def test_zero_percent_gst(self):
        # 250 at 0% -> CGST 0.0, SGST 0.0, Total 250.00
        res = calculate_gst(250.0, 0.0)
        assert res["taxable_amount"] == 250.0
        assert res["cgst"] == 0.0
        assert res["sgst"] == 0.0
        assert res["total_gst"] == 0.0
        assert res["total"] == 250.0

    def test_12_percent_gst(self):
        # 60 at 12% -> 6% CGST (3.60), 6% SGST (3.60), Total 67.20
        res = calculate_gst(60.0, 12.0)
        assert res["cgst"] == 3.60
        assert res["sgst"] == 3.60
        assert res["total_gst"] == 7.20
        assert res["total"] == 67.20

    def test_18_percent_gst(self):
        # 185 at 18% -> 9% CGST (16.65), 9% SGST (16.65), Total 218.30
        res = calculate_gst(185.0, 18.0)
        assert res["cgst"] == 16.65
        assert res["sgst"] == 16.65
        assert res["total_gst"] == 33.30
        assert res["total"] == 218.30

    def test_half_up_rounding_odd_amount(self):
        # Odd amount test: 33.33 at 5% GST
        # half_rate = 2.5% -> 33.33 * 0.025 = 0.83325 -> rounds to 0.83
        res = calculate_gst(33.33, 5.0)
        assert res["cgst"] == 0.83
        assert res["sgst"] == 0.83
        assert res["total_gst"] == 1.66
        assert res["total"] == 34.99

    def test_half_up_exact_half(self):
        # 10.00 at 5% -> 10 * 0.025 = 0.25 -> exactly 0.25
        res = calculate_gst(10.0, 5.0)
        assert res["cgst"] == 0.25
        assert res["sgst"] == 0.25
        assert res["total"] == 10.50

        # 30.00 at 5% -> 30 * 0.025 = 0.75 -> exactly 0.75
        res = calculate_gst(30.0, 5.0)
        assert res["cgst"] == 0.75
        assert res["sgst"] == 0.75
        assert res["total"] == 31.50

    def test_fractional_cent_round_up(self):
        # 15.00 at 5% -> 15 * 0.025 = 0.375 -> half-up rounds to 0.38
        res = calculate_gst(15.0, 5.0)
        assert res["cgst"] == 0.38
        assert res["sgst"] == 0.38
        assert res["total_gst"] == 0.76
        assert res["total"] == 15.76

    def test_negative_taxable_amount_raises(self):
        with pytest.raises(ValueError, match="taxable_amount"):
            calculate_gst(-10.0, 5.0)

    def test_negative_gst_rate_raises(self):
        with pytest.raises(ValueError, match="gst_rate"):
            calculate_gst(100.0, -5.0)
