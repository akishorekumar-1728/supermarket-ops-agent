"""
tools/billing.py
================
Draft billing and invoice management tools for the Supermarket Ops Agent.

Operations on bills:
- create_bill(conn, payment_mode=None)
- add_bill_item(bill_id, product_query, quantity, conn)
- remove_bill_item(bill_id, product_query, conn)
- update_bill_item(bill_id, product_query, new_quantity, conn)

Stock isolation guarantee:
Stock quantities are NOT touched during draft creation, item additions,
updates, or removals. Stock changes only happen upon finalization.
"""
from __future__ import annotations

import sqlite3
import uuid
from decimal import Decimal
from typing import Any

from tools.gst import calculate_gst
from tools.products import ProductNotFoundError, ValidationError, get_product


class BillNotFoundError(LookupError):
    """Raised when a bill is not found."""


class BillStateError(ValueError):
    """Raised when attempting an illegal operation on a finalized or void bill."""


def _check_bill_active(bill_id: int, conn: sqlite3.Connection) -> sqlite3.Row:
    """Check bill exists and is in 'draft' status. Return bill row."""
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise BillNotFoundError(f"Bill with ID {bill_id} not found.")
    if bill["status"] != "draft":
        raise BillStateError(
            f"Cannot modify bill {bill_id}: status is '{bill['status']}', expected 'draft'."
        )
    return bill


def _recalculate_bill_totals(bill_id: int, conn: sqlite3.Connection) -> dict[str, float]:
    """
    Recalculate subtotal, cgst_total, sgst_total, gst_total, and grand_total
    from all items belonging to bill_id and update the bills table.
    """
    items = conn.execute(
        "SELECT taxable_amount, cgst_amount, sgst_amount, total FROM bill_items WHERE bill_id = ?",
        (bill_id,),
    ).fetchall()

    subtotal = sum(Decimal(str(item["taxable_amount"])) for item in items)
    cgst_total = sum(Decimal(str(item["cgst_amount"])) for item in items)
    sgst_total = sum(Decimal(str(item["sgst_amount"])) for item in items)
    gst_total = cgst_total + sgst_total
    grand_total = sum(Decimal(str(item["total"])) for item in items)

    conn.execute(
        """
        UPDATE bills
        SET subtotal = ?,
            cgst_total = ?,
            sgst_total = ?,
            gst_total = ?,
            grand_total = ?
        WHERE id = ?
        """,
        (
            float(subtotal),
            float(cgst_total),
            float(sgst_total),
            float(gst_total),
            float(grand_total),
            bill_id,
        ),
    )

    return {
        "subtotal": float(subtotal),
        "cgst_total": float(cgst_total),
        "sgst_total": float(sgst_total),
        "gst_total": float(gst_total),
        "grand_total": float(grand_total),
    }


def _resolve_single_product(product_query: str, conn: sqlite3.Connection) -> dict[str, Any]:
    """Resolve product query to a single product or raise descriptive error."""
    matches = get_product(product_query, conn)
    if not matches:
        raise ProductNotFoundError(f"No product found matching {product_query!r}.")
    if len(matches) > 1:
        names = [f"{m['name']} (SKU: {m['sku']})" for m in matches]
        raise ValueError(
            f"Ambiguous product query {product_query!r} — matches multiple products: {names}."
        )
    return matches[0]


def create_bill(
    conn: sqlite3.Connection,
    payment_mode: str | None = None,
    *,
    idempotency_key: str | None = None,
    invoice_number: str | None = None,
) -> int:
    """
    Create a new draft bill.

    Parameters:
        conn: Open sqlite3.Connection.
        payment_mode: Optional payment mode ('cash', 'upi', 'card', 'credit').
        idempotency_key: Optional uniqueness key. Defaults to a random UUID.
        invoice_number: Optional custom invoice number. Defaults to 'INV-{short-uuid}'.

    Returns:
        bill_id (int) of the created draft bill.
    """
    if idempotency_key is None:
        idempotency_key = f"bill-{uuid.uuid4()}"

    if invoice_number is None:
        # Generate an invoice number prefix
        short_id = uuid.uuid4().hex[:8].upper()
        invoice_number = f"INV-{short_id}"

    with conn:
        cur = conn.execute(
            """
            INSERT INTO bills (
                invoice_number,
                status,
                payment_mode,
                subtotal,
                cgst_total,
                sgst_total,
                gst_total,
                grand_total,
                idempotency_key
            ) VALUES (?, 'draft', ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?)
            """,
            (invoice_number, payment_mode, idempotency_key),
        )
        bill_id = cur.lastrowid

    return bill_id


def add_bill_item(
    bill_id: int,
    product_query: str,
    quantity: float,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """
    Add a product line item to a draft bill and recalculate running totals.
    Does NOT modify stock quantities.

    Parameters:
        bill_id: ID of the target draft bill.
        product_query: Product name or SKU.
        quantity: Item quantity (must be > 0).
        conn: Open sqlite3.Connection.

    Returns:
        dict containing the inserted bill_item details and updated bill totals.
    """
    _check_bill_active(bill_id, conn)

    try:
        qty = float(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Quantity must be numeric: {exc}") from exc

    if qty <= 0:
        raise ValidationError(f"Quantity must be > 0, got {qty}")

    product = _resolve_single_product(product_query, conn)
    product_id = product["id"]
    unit_price = float(product["selling_price"])
    cost_price = float(product["cost_price"])
    gst_rate = float(product["gst_rate"])
    hsn_code = str(product["hsn_code"] or "")

    # Calculate item amounts
    taxable_amount = round(unit_price * qty, 2)
    gst_info = calculate_gst(taxable_amount, gst_rate)
    cgst_amount = gst_info["cgst"]
    sgst_amount = gst_info["sgst"]
    total = gst_info["total"]

    with conn:
        cur = conn.execute(
            """
            INSERT INTO bill_items (
                bill_id, product_id, quantity, unit_price, cost_price,
                taxable_amount, gst_rate, hsn_code, cgst_amount, sgst_amount, total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill_id,
                product_id,
                qty,
                unit_price,
                cost_price,
                taxable_amount,
                gst_rate,
                hsn_code,
                cgst_amount,
                sgst_amount,
                total,
            ),
        )
        item_id = cur.lastrowid
        totals = _recalculate_bill_totals(bill_id, conn)

    return {
        "item_id": item_id,
        "bill_id": bill_id,
        "product_id": product_id,
        "sku": product["sku"],
        "name": product["name"],
        "quantity": qty,
        "unit_price": unit_price,
        "taxable_amount": taxable_amount,
        "gst_rate": gst_rate,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "total": total,
        "bill_totals": totals,
    }


def remove_bill_item(
    bill_id: int,
    product_query: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """
    Remove line item(s) for the specified product from a draft bill
    and recalculate running totals. Does NOT modify stock.

    Parameters:
        bill_id: ID of the draft bill.
        product_query: Product name or SKU.
        conn: Open sqlite3.Connection.

    Returns:
        dict with removed product info and updated bill totals.
    """
    _check_bill_active(bill_id, conn)
    product = _resolve_single_product(product_query, conn)
    product_id = product["id"]

    # Verify item exists in this bill
    existing = conn.execute(
        "SELECT id FROM bill_items WHERE bill_id = ? AND product_id = ?",
        (bill_id, product_id),
    ).fetchall()

    if not existing:
        raise LookupError(
            f"Product {product['name']!r} (SKU: {product['sku']}) is not in bill {bill_id}."
        )

    with conn:
        conn.execute(
            "DELETE FROM bill_items WHERE bill_id = ? AND product_id = ?",
            (bill_id, product_id),
        )
        totals = _recalculate_bill_totals(bill_id, conn)

    return {
        "bill_id": bill_id,
        "removed_product_id": product_id,
        "sku": product["sku"],
        "name": product["name"],
        "bill_totals": totals,
    }


def update_bill_item(
    bill_id: int,
    product_query: str,
    new_quantity: float,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """
    Update the quantity of a line item in a draft bill and recalculate running totals.
    Does NOT modify stock.

    Parameters:
        bill_id: ID of the draft bill.
        product_query: Product name or SKU.
        new_quantity: New quantity (must be > 0).
        conn: Open sqlite3.Connection.

    Returns:
        dict with updated line item details and updated bill totals.
    """
    _check_bill_active(bill_id, conn)

    try:
        qty = float(new_quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Quantity must be numeric: {exc}") from exc

    if qty <= 0:
        raise ValidationError(f"Quantity must be > 0, got {qty}")

    product = _resolve_single_product(product_query, conn)
    product_id = product["id"]

    existing = conn.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? AND product_id = ?",
        (bill_id, product_id),
    ).fetchone()

    if not existing:
        raise LookupError(
            f"Product {product['name']!r} (SKU: {product['sku']}) is not in bill {bill_id}."
        )

    unit_price = float(existing["unit_price"])
    gst_rate = float(existing["gst_rate"])

    taxable_amount = round(unit_price * qty, 2)
    gst_info = calculate_gst(taxable_amount, gst_rate)
    cgst_amount = gst_info["cgst"]
    sgst_amount = gst_info["sgst"]
    total = gst_info["total"]

    with conn:
        conn.execute(
            """
            UPDATE bill_items
            SET quantity = ?,
                taxable_amount = ?,
                cgst_amount = ?,
                sgst_amount = ?,
                total = ?
            WHERE id = ?
            """,
            (qty, taxable_amount, cgst_amount, sgst_amount, total, existing["id"]),
        )
        totals = _recalculate_bill_totals(bill_id, conn)

    return {
        "item_id": existing["id"],
        "bill_id": bill_id,
        "product_id": product_id,
        "sku": product["sku"],
        "name": product["name"],
        "quantity": qty,
        "unit_price": unit_price,
        "taxable_amount": taxable_amount,
        "gst_rate": gst_rate,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "total": total,
        "bill_totals": totals,
    }


def get_bill(bill_id: int, conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Retrieve full bill details including header and all line items.
    """
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise BillNotFoundError(f"Bill with ID {bill_id} not found.")

    items = conn.execute(
        """
        SELECT bi.*, p.sku, p.name, p.unit
        FROM bill_items bi
        JOIN products p ON p.id = bi.product_id
        WHERE bi.bill_id = ?
        ORDER BY bi.id
        """,
        (bill_id,),
    ).fetchall()

    bill_dict = dict(bill)
    bill_dict["items"] = [dict(it) for it in items]
    return bill_dict
