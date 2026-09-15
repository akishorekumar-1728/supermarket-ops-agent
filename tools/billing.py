"""
tools/billing.py
================
Draft billing and invoice management tools for the Supermarket Ops Agent.

Operations on bills:
- create_bill(bill_id, payment_mode=None, ...)
- add_bill_item(bill_id, product_query, quantity, conn)
- remove_bill_item(bill_id, product_query, conn)
- update_bill_item(bill_id, product_query, new_quantity, conn)
- finalize_bill(bill_id, idempotency_key, payment_mode=None, payment_reference=None, conn=None)
- get_bill(bill_id, conn)

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


class InsufficientStockError(ValueError):
    """Raised when an item cannot be fulfilled due to insufficient stock."""


class BelowCostSaleError(ValueError):
    """Raised when an item is priced below cost price."""


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
    conn: sqlite3.Connection | None = None,
    payment_mode: str | None = None,
    *,
    idempotency_key: str | None = None,
    invoice_number: str | None = None,
    **kwargs: Any,
) -> int:
    """
    Create a new draft bill.

    Accepts connection either as first positional argument or keyword argument 'conn'.

    Parameters:
        conn: Open sqlite3.Connection.
        payment_mode: Optional payment mode ('cash', 'upi', 'card', 'credit').
        idempotency_key: Optional uniqueness key. Defaults to a random UUID.
        invoice_number: Optional custom invoice number. Defaults to 'DRAFT-{short-uuid}'.

    Returns:
        bill_id (int) of the created draft bill.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("create_bill requires an open sqlite3.Connection (conn).")

    if idempotency_key is None:
        idempotency_key = f"draft-{uuid.uuid4()}"

    if invoice_number is None:
        short_id = uuid.uuid4().hex[:8].upper()
        invoice_number = f"INV-DRAFT-{short_id}"

    with c:
        cur = c.execute(
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


def _generate_sequential_invoice_number(conn: sqlite3.Connection) -> str:
    """
    Generate the next sequential invoice number format 'INV-YYYYMMDD-XXXX'
    or 'INV-XXXXX' based on the max existing finalized invoice.
    """
    # Find max invoice number with prefix 'INV-'
    row = conn.execute(
        """
        SELECT invoice_number
        FROM bills
        WHERE status = 'finalized' AND invoice_number LIKE 'INV-%'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    next_num = 1
    if row and row["invoice_number"]:
        inv_str = row["invoice_number"]
        parts = inv_str.split("-")
        try:
            next_num = int(parts[-1]) + 1
        except ValueError:
            next_num = 1

    return f"INV-{next_num:05d}"


def finalize_bill(
    bill_id: int,
    idempotency_key: str,
    payment_mode: str | None = None,
    payment_reference: str | None = None,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Finalize a draft bill with hard business guards:
    - Transactional atomicity (BEGIN IMMEDIATE) to prevent concurrent race conditions.
    - Idempotency: if already finalized with this idempotency_key, returns the existing bill.
    - Oversell guard: checks every item against available stock. If any item exceeds stock,
      rejects entire finalize with InsufficientStockError and leaves stock unchanged.
    - Below-cost guard: checks unit_price >= cost_price for every item. Rejects with BelowCostSaleError.
    - Decrements stock for each item atomically.
    - Generates sequential invoice_number, sets status='finalized', finalized_at, and commits.

    Parameters:
        bill_id: Target bill ID to finalize.
        idempotency_key: Unique client request identifier.
        payment_mode: Optional payment mode ('cash', 'upi', 'card', 'credit').
        payment_reference: Optional payment reference.
        conn: Open sqlite3.Connection (can be passed positional or keyword).

    Returns:
        Full finalized bill details dict.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("finalize_bill requires an open sqlite3.Connection (conn).")

    if not idempotency_key or not str(idempotency_key).strip():
        raise ValidationError("idempotency_key must be provided and non-empty.")

    idempotency_key = str(idempotency_key).strip()

    # Step 1: Idempotency check BEFORE acquiring immediate lock
    # If a bill with this idempotency_key is ALREADY finalized, return it immediately.
    existing_finalized = c.execute(
        "SELECT id FROM bills WHERE idempotency_key = ? AND status = 'finalized'",
        (idempotency_key,),
    ).fetchone()
    if existing_finalized:
        return get_bill(existing_finalized["id"], c)

    # Step 2: Begin IMMEDIATE transaction to lock database against concurrent writers
    c.execute("BEGIN IMMEDIATE")
    try:
        # Re-check idempotency under lock in case another transaction just committed it
        existing_finalized = c.execute(
            "SELECT id FROM bills WHERE idempotency_key = ? AND status = 'finalized'",
            (idempotency_key,),
        ).fetchone()
        if existing_finalized:
            c.execute("COMMIT")
            return get_bill(existing_finalized["id"], c)

        # Retrieve bill under lock
        bill = c.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            raise BillNotFoundError(f"Bill with ID {bill_id} not found.")

        if bill["status"] == "finalized":
            # If bill was already finalized under another key, raise error
            raise BillStateError(
                f"Bill {bill_id} is already finalized (invoice: {bill['invoice_number']})."
            )
        if bill["status"] == "void":
            raise BillStateError(f"Cannot finalize void bill {bill_id}.")

        # Retrieve bill items
        items = c.execute(
            """
            SELECT bi.*, p.name, p.sku, p.cost_price AS master_cost_price
            FROM bill_items bi
            JOIN products p ON p.id = bi.product_id
            WHERE bi.bill_id = ?
            """,
            (bill_id,),
        ).fetchall()

        if not items:
            raise ValidationError(f"Cannot finalize bill {bill_id}: bill has no items.")

        # Aggregate requested quantities per product
        # (in case the same product was added multiple times across lines)
        product_req_qty: dict[int, float] = {}
        for it in items:
            pid = it["product_id"]
            product_req_qty[pid] = product_req_qty.get(pid, 0.0) + float(it["quantity"])

        # Validate below-cost guard for all line items
        for it in items:
            unit_price = float(it["unit_price"])
            cost_price = float(it["cost_price"])
            if unit_price < cost_price:
                raise BelowCostSaleError(
                    f"Item {it['name']!r} (SKU: {it['sku']}) selling price ({unit_price}) "
                    f"is below its cost price ({cost_price}). Sale rejected."
                )

        # Validate stock availability for every product in the bill
        for pid, req_qty in product_req_qty.items():
            stock_row = c.execute(
                "SELECT quantity FROM stock WHERE product_id = ?", (pid,)
            ).fetchone()
            current_stock = float(stock_row["quantity"]) if stock_row else 0.0

            if req_qty > current_stock:
                shortfall = req_qty - current_stock
                # Find product name
                prod_info = next(it for it in items if it["product_id"] == pid)
                raise InsufficientStockError(
                    f"Cannot finalize bill: Insufficient stock for {prod_info['name']!r} "
                    f"(SKU: {prod_info['sku']}). Requested: {req_qty}, "
                    f"Available: {current_stock}, Shortfall: {shortfall}."
                )

        # All checks passed! Decrement stock atomically
        for pid, req_qty in product_req_qty.items():
            c.execute(
                """
                UPDATE stock
                SET quantity = quantity - ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE product_id = ?
                """,
                (req_qty, pid),
            )

        # Generate sequential invoice number
        invoice_number = _generate_sequential_invoice_number(c)

        # Determine effective payment mode
        eff_payment_mode = payment_mode or bill["payment_mode"] or "cash"

        # Update bill header to 'finalized'
        c.execute(
            """
            UPDATE bills
            SET invoice_number = ?,
                status = 'finalized',
                payment_mode = ?,
                payment_reference = ?,
                finalized_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                idempotency_key = ?
            WHERE id = ?
            """,
            (
                invoice_number,
                eff_payment_mode,
                payment_reference,
                idempotency_key,
                bill_id,
            ),
        )

        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise

    return get_bill(bill_id, c)


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
