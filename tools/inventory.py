"""
tools/inventory.py
==================
Inventory management tool functions for the Supermarket Ops Agent.

Tool functions
--------------
receive_stock(product_query, quantity, conn, cost_price=None, mrp=None)
    Find a product, then atomically increment its stock quantity.
    Optionally update cost_price and/or mrp on the product row.

get_stock(product_query, conn)
    Return the current stock quantity for a product.

get_low_stock(conn)
    Return all products where current stock quantity <= reorder_level.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from tools.products import (
    ValidationError,
    ProductNotFoundError,
    get_product,
    _row_to_dict,
)


# ---------------------------------------------------------------------------
# Tool: receive_stock
# ---------------------------------------------------------------------------

def receive_stock(
    product_query: str,
    quantity: float,
    conn: sqlite3.Connection,
    *,
    cost_price: float | None = None,
    mrp: float | None = None,
) -> dict[str, Any]:
    """
    Tool: receive_stock
    -------------------
    Description:
        Record stock arriving at the shop.  Finds the product by name or
        SKU, then atomically increments its stock quantity.  Optionally
        updates cost_price and/or mrp on the product master if prices have
        changed on the new consignment.

    Parameters:
        product_query (str)         : Product name or SKU to look up.
        quantity      (float)       : Quantity received (must be > 0).
        conn                        : Open sqlite3.Connection.
        cost_price    (float | None): New cost price to update (optional).
        mrp           (float | None): New MRP to update (optional).

    Returns:
        dict — updated product fields plus new stock ``quantity``.

    Raises:
        ValidationError        : quantity <= 0 or product_query empty.
        ProductNotFoundError   : No product matches product_query.
        ValueError             : Multiple products match — query is ambiguous.
    """
    if not product_query or not str(product_query).strip():
        raise ValidationError("receive_stock: product_query must not be empty")

    try:
        quantity = float(quantity)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"receive_stock: quantity must be numeric: {exc}") from exc

    if quantity <= 0:
        raise ValidationError(
            f"receive_stock: quantity must be > 0, got {quantity}"
        )

    # Locate the product
    matches = get_product(product_query, conn)
    if len(matches) == 0:
        raise ProductNotFoundError(
            f"No product found matching {product_query!r}"
        )
    if len(matches) > 1:
        names = [m["name"] for m in matches]
        raise ValueError(
            f"Ambiguous product query {product_query!r} — "
            f"multiple matches: {names}. Please be more specific."
        )

    product = matches[0]
    product_id = product["id"]

    # Optional price validation before writing
    if cost_price is not None:
        cost_price = float(cost_price)
        if cost_price < 0:
            raise ValidationError(f"cost_price must be >= 0, got {cost_price}")

    if mrp is not None:
        mrp = float(mrp)
        if mrp < 0:
            raise ValidationError(f"mrp must be >= 0, got {mrp}")

    # If both are provided, check mrp >= cost_price
    effective_cost  = cost_price if cost_price is not None else product["cost_price"]
    effective_mrp   = mrp        if mrp        is not None else product["mrp"]
    if effective_mrp < effective_cost:
        raise ValidationError(
            f"mrp ({effective_mrp}) must be >= cost_price ({effective_cost})"
        )

    # Atomic update inside a single transaction
    with conn:
        # Increment stock
        conn.execute(
            """
            UPDATE stock
            SET    quantity   = quantity + ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE  product_id = ?
            """,
            (quantity, product_id),
        )

        # Optionally update prices on the product master
        if cost_price is not None or mrp is not None:
            updates: list[str] = []
            params: list[Any]  = []
            if cost_price is not None:
                updates.append("cost_price = ?")
                params.append(cost_price)
            if mrp is not None:
                updates.append("mrp = ?")
                params.append(mrp)
            updates.append("updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')")
            params.append(product_id)
            conn.execute(
                f"UPDATE products SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    # Return the refreshed product + stock
    row = conn.execute(
        """
        SELECT p.*, s.quantity
        FROM   products p
        JOIN   stock s ON s.product_id = p.id
        WHERE  p.id = ?
        """,
        (product_id,),
    ).fetchone()

    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Tool: get_stock
# ---------------------------------------------------------------------------

def get_stock(
    product_query: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """
    Tool: get_stock
    ---------------
    Description:
        Return the current stock quantity for a specific product.

    Parameters:
        product_query (str) : Product name or SKU to look up.
        conn                : Open sqlite3.Connection.

    Returns:
        dict with keys:
            product_id, sku, name, unit, quantity, reorder_level,
            is_low_stock (bool — True if quantity <= reorder_level).

    Raises:
        ValidationError      : product_query is empty.
        ProductNotFoundError : No product matches.
        ValueError           : Ambiguous query (multiple matches).
    """
    if not product_query or not str(product_query).strip():
        raise ValidationError("get_stock: product_query must not be empty")

    matches = get_product(product_query, conn)
    if len(matches) == 0:
        raise ProductNotFoundError(
            f"No product found matching {product_query!r}"
        )
    if len(matches) > 1:
        names = [m["name"] for m in matches]
        raise ValueError(
            f"Ambiguous query {product_query!r} — multiple matches: {names}. "
            "Please be more specific."
        )

    p = matches[0]
    qty = p["quantity"]
    reorder = p["reorder_level"]

    return {
        "product_id":    p["id"],
        "sku":           p["sku"],
        "name":          p["name"],
        "unit":          p["unit"],
        "quantity":      qty,
        "reorder_level": reorder,
        "is_low_stock":  qty <= reorder,
    }


# ---------------------------------------------------------------------------
# Tool: get_low_stock
# ---------------------------------------------------------------------------

def get_low_stock(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Tool: get_low_stock
    -------------------
    Description:
        Return all products whose current stock is at or below their
        reorder_level.  Useful for generating purchase orders.

    Parameters:
        conn : Open sqlite3.Connection to the supermarket DB.

    Returns:
        list[dict] — each dict contains:
            product_id, sku, name, unit, quantity, reorder_level, shortfall.
        Sorted by shortfall descending (most urgent first).
        Returns an empty list if all stock is adequate.
    """
    rows = conn.execute(
        """
        SELECT  p.id          AS product_id,
                p.sku,
                p.name,
                p.unit,
                s.quantity,
                p.reorder_level,
                (p.reorder_level - s.quantity) AS shortfall
        FROM    stock s
        JOIN    products p ON p.id = s.product_id
        WHERE   s.quantity <= p.reorder_level
        ORDER   BY shortfall DESC, p.name
        """
    ).fetchall()

    return [dict(r) for r in rows]
