"""
tools/analytics.py
==================
Daily business analytics and operational reporting for the Supermarket Ops Agent.

Pure SQL aggregations:
- daily_summary(date=None, conn=None)
    Aggregates finalized bills for a specific date (defaults to UTC today YYYY-MM-DD):
    - total sales (grand total of finalized bills)
    - number of finalized bills
    - total GST collected (with CGST / SGST split)
    - totals broken down by payment_mode (cash, upi, card, credit, etc.)
    - top-selling products by quantity and by revenue for that date
"""
from __future__ import annotations

import datetime
import sqlite3
from typing import Any


def daily_summary(
    date: str | datetime.date | None = None,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Calculate and return daily sales, GST, payment mode breakdown,
    and top-selling products for finalized bills on a given date.

    Parameters:
        date: Date in 'YYYY-MM-DD' format or datetime.date object.
              Defaults to current UTC date if None.
        conn: Open sqlite3.Connection (positional or keyword).

    Returns:
        dict with:
            - date (str: 'YYYY-MM-DD')
            - total_sales (float)
            - total_bills (int)
            - gst_summary (dict):
                - total_gst (float)
                - cgst_total (float)
                - sgst_total (float)
            - payment_modes (dict[str, dict]): breakdown with total_amount and bill_count
            - top_products_by_quantity (list[dict]): rank, sku, name, total_quantity, total_revenue
            - top_products_by_revenue (list[dict]): rank, sku, name, total_quantity, total_revenue
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("daily_summary requires an open sqlite3.Connection (conn).")

    if date is None:
        target_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(date, datetime.date):
        target_date = date.strftime("%Y-%m-%d")
    else:
        target_date = str(date).strip()

    # Query 1: Overall totals for finalized bills on target_date
    summary_row = c.execute(
        """
        SELECT
            COUNT(id) AS total_bills,
            COALESCE(SUM(subtotal), 0) AS total_subtotal,
            COALESCE(SUM(cgst_total), 0) AS total_cgst,
            COALESCE(SUM(sgst_total), 0) AS total_sgst,
            COALESCE(SUM(gst_total), 0) AS total_gst,
            COALESCE(SUM(grand_total), 0) AS total_sales
        FROM bills
        WHERE status = 'finalized'
          AND date(COALESCE(finalized_at, created_at)) = date(?)
        """,
        (target_date,),
    ).fetchone()

    total_bills = int(summary_row["total_bills"]) if summary_row else 0
    total_sales = round(float(summary_row["total_sales"]), 2) if summary_row else 0.0
    total_subtotal = round(float(summary_row["total_subtotal"]), 2) if summary_row else 0.0
    total_cgst = round(float(summary_row["total_cgst"]), 2) if summary_row else 0.0
    total_sgst = round(float(summary_row["total_sgst"]), 2) if summary_row else 0.0
    total_gst = round(float(summary_row["total_gst"]), 2) if summary_row else 0.0

    # Query 2: Breakdown by payment mode
    payment_rows = c.execute(
        """
        SELECT
            COALESCE(LOWER(payment_mode), 'unspecified') AS mode,
            COUNT(id) AS bill_count,
            COALESCE(SUM(grand_total), 0) AS total_amount
        FROM bills
        WHERE status = 'finalized'
          AND date(COALESCE(finalized_at, created_at)) = date(?)
        GROUP BY mode
        ORDER BY total_amount DESC
        """,
        (target_date,),
    ).fetchall()

    payment_modes: dict[str, dict[str, Any]] = {}
    for r in payment_rows:
        payment_modes[r["mode"]] = {
            "bill_count": int(r["bill_count"]),
            "total_amount": round(float(r["total_amount"]), 2),
        }

    # Query 3: Top selling products by quantity
    qty_rows = c.execute(
        """
        SELECT
            p.id AS product_id,
            p.sku,
            p.name,
            p.unit,
            SUM(bi.quantity) AS total_quantity,
            ROUND(SUM(bi.total), 2) AS total_revenue
        FROM bill_items bi
        JOIN bills b ON b.id = bi.bill_id
        JOIN products p ON p.id = bi.product_id
        WHERE b.status = 'finalized'
          AND date(COALESCE(b.finalized_at, b.created_at)) = date(?)
        GROUP BY p.id
        ORDER BY total_quantity DESC, total_revenue DESC
        """,
        (target_date,),
    ).fetchall()

    top_by_qty = []
    for rank, r in enumerate(qty_rows, start=1):
        top_by_qty.append({
            "rank": rank,
            "product_id": r["product_id"],
            "sku": r["sku"],
            "name": r["name"],
            "unit": r["unit"],
            "total_quantity": float(r["total_quantity"]),
            "total_revenue": float(r["total_revenue"]),
        })

    # Query 4: Top selling products by revenue
    rev_rows = c.execute(
        """
        SELECT
            p.id AS product_id,
            p.sku,
            p.name,
            p.unit,
            SUM(bi.quantity) AS total_quantity,
            ROUND(SUM(bi.total), 2) AS total_revenue
        FROM bill_items bi
        JOIN bills b ON b.id = bi.bill_id
        JOIN products p ON p.id = bi.product_id
        WHERE b.status = 'finalized'
          AND date(COALESCE(b.finalized_at, b.created_at)) = date(?)
        GROUP BY p.id
        ORDER BY total_revenue DESC, total_quantity DESC
        """,
        (target_date,),
    ).fetchall()

    top_by_rev = []
    for rank, r in enumerate(rev_rows, start=1):
        top_by_rev.append({
            "rank": rank,
            "product_id": r["product_id"],
            "sku": r["sku"],
            "name": r["name"],
            "unit": r["unit"],
            "total_quantity": float(r["total_quantity"]),
            "total_revenue": float(r["total_revenue"]),
        })

    return {
        "date": target_date,
        "total_sales": total_sales,
        "total_subtotal": total_subtotal,
        "total_bills": total_bills,
        "gst_summary": {
            "total_gst": total_gst,
            "cgst_total": total_cgst,
            "sgst_total": total_sgst,
        },
        "payment_modes": payment_modes,
        "top_products_by_quantity": top_by_qty,
        "top_products_by_revenue": top_by_rev,
    }
