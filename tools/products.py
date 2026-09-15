"""
tools/products.py
=================
Product-management tool functions for the Supermarket Ops Agent.

Each function is a plain Python callable.  The docstring doubles as the
tool schema (name, description, parameters) so it can be registered with
the Ollama function-calling agent later.

Tool functions
--------------
add_product(sku, name, unit, cost_price, selling_price, mrp,
            gst_rate, hsn_code, reorder_level, conn)
    Create a new product and its initial stock row (quantity = 0).

get_product(query, conn)
    Search products by SKU (exact, case-insensitive) or by name
    (LIKE fuzzy match).  Returns a list so the caller can handle
    multiple matches.
"""
from __future__ import annotations

import sqlite3
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid GST slabs used in India (common rates; list can be extended)
VALID_GST_RATES: frozenset[float] = frozenset(
    {0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 9.0, 12.0, 14.0, 18.0, 28.0}
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ValidationError(ValueError):
    """Raised when tool-input validation fails."""


class ProductNotFoundError(LookupError):
    """Raised when a product lookup returns no results."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _validate_add_product(
    sku: Any,
    name: Any,
    unit: Any,
    cost_price: Any,
    selling_price: Any,
    mrp: Any,
    gst_rate: Any,
    hsn_code: Any,
    reorder_level: Any,
) -> None:
    """
    Raise ValidationError with a descriptive message if any field is
    missing or violates a business rule.  Never silently defaults values.
    """
    # Check for None / empty strings
    missing = [
        fname
        for fname, val in [
            ("sku", sku), ("name", name), ("unit", unit),
            ("cost_price", cost_price), ("selling_price", selling_price),
            ("mrp", mrp), ("gst_rate", gst_rate),
            ("hsn_code", hsn_code), ("reorder_level", reorder_level),
        ]
        if val is None or (isinstance(val, str) and not val.strip())
    ]
    if missing:
        raise ValidationError(f"Required field(s) missing or empty: {missing}")

    # Numeric conversions
    try:
        cost_price    = float(cost_price)
        selling_price = float(selling_price)
        mrp           = float(mrp)
        gst_rate      = float(gst_rate)
        reorder_level = int(reorder_level)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Non-numeric value in price/rate/level: {exc}") from exc

    if cost_price < 0:
        raise ValidationError(f"cost_price must be >= 0, got {cost_price}")
    if selling_price < 0:
        raise ValidationError(f"selling_price must be >= 0, got {selling_price}")
    if mrp < 0:
        raise ValidationError(f"mrp must be >= 0, got {mrp}")
    if reorder_level < 0:
        raise ValidationError(f"reorder_level must be >= 0, got {reorder_level}")

    # Price hierarchy: cost_price <= selling_price <= mrp
    if selling_price < cost_price:
        raise ValidationError(
            f"selling_price ({selling_price}) must be >= cost_price ({cost_price})"
        )
    if mrp < selling_price:
        raise ValidationError(
            f"mrp ({mrp}) must be >= selling_price ({selling_price})"
        )

    # GST slab validation
    if gst_rate not in VALID_GST_RATES:
        raise ValidationError(
            f"gst_rate {gst_rate}% is not a recognised Indian GST slab. "
            f"Valid values: {sorted(VALID_GST_RATES)}"
        )


# ---------------------------------------------------------------------------
# Tool: add_product
# ---------------------------------------------------------------------------

def add_product(
    sku: str,
    name: str,
    unit: str,
    cost_price: float,
    selling_price: float,
    mrp: float,
    gst_rate: float,
    hsn_code: str,
    reorder_level: int,
    conn: sqlite3.Connection,
    *,
    initial_stock: float = 0.0,
) -> dict[str, Any]:
    """
    Tool: add_product
    -----------------
    Description:
        Add a new product to the catalogue and create its stock entry.
        Raises a clear ValidationError for any missing or inconsistent field.

    Parameters:
        sku           (str)   : Unique SKU code, e.g. "TATA-SALT-1KG".
        name          (str)   : Human-readable product name.
        unit          (str)   : Selling unit — "pkt", "kg", "litre", "pcs", etc.
        cost_price    (float) : Landed cost per unit (>= 0).
        selling_price (float) : Customer selling price (>= cost_price).
        mrp           (float) : Max Retail Price on packaging (>= selling_price).
        gst_rate      (float) : GST percentage from valid Indian slabs
                                (0, 5, 12, 18, ...).
        hsn_code      (str)   : HSN / SAC code for GST invoicing.
        reorder_level (int)   : Alert threshold — reorder when stock <= this.
        conn                  : Open sqlite3.Connection (WAL + FK ON).
        initial_stock (float) : Opening stock quantity (default 0).

    Returns:
        dict — all product fields plus current stock ``quantity``.

    Raises:
        ValidationError        : Any field missing, out-of-range, or inconsistent.
        sqlite3.IntegrityError : Duplicate SKU.
    """
    _validate_add_product(
        sku, name, unit, cost_price, selling_price,
        mrp, gst_rate, hsn_code, reorder_level,
    )

    # Coerce to correct Python types after validation passes
    sku           = str(sku).strip()
    name          = str(name).strip()
    unit          = str(unit).strip()
    cost_price    = float(cost_price)
    selling_price = float(selling_price)
    mrp           = float(mrp)
    gst_rate      = float(gst_rate)
    hsn_code      = str(hsn_code).strip()
    reorder_level = int(reorder_level)
    initial_stock = float(initial_stock)

    with conn:
        cur = conn.execute(
            """
            INSERT INTO products
                (sku, name, unit, cost_price, selling_price, mrp,
                 gst_rate, hsn_code, reorder_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sku, name, unit, cost_price, selling_price, mrp,
             gst_rate, hsn_code, reorder_level),
        )
        product_id = cur.lastrowid

        conn.execute(
            "INSERT INTO stock (product_id, quantity) VALUES (?, ?)",
            (product_id, initial_stock),
        )

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
# Tool: get_product
# ---------------------------------------------------------------------------

def get_product(
    query: str,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """
    Tool: get_product
    -----------------
    Description:
        Look up a product by SKU (exact, case-insensitive) or by name
        (LIKE fuzzy match).  Returns ALL matching products so the calling
        agent can present choices to the user when more than one matches —
        never guesses.

    Parameters:
        query (str) : SKU or partial product name to search for.
                      e.g. "Maggi", "MAGI-NOODL-70G", "atta".
        conn        : Open sqlite3.Connection to the supermarket DB.

    Returns:
        list[dict] — zero or more products (each with all product fields
        plus current stock ``quantity``).  Empty list means not found.

    Raises:
        ValidationError : If query is empty or None.
    """
    if not query or not str(query).strip():
        raise ValidationError("get_product: query must not be empty")

    q = str(query).strip()

    rows = conn.execute(
        """
        SELECT p.*, s.quantity
        FROM   products p
        JOIN   stock s ON s.product_id = p.id
        WHERE  LOWER(p.sku) = LOWER(?)
           OR  LOWER(p.name) LIKE LOWER(?)
        ORDER  BY p.name
        """,
        (q, f"%{q}%"),
    ).fetchall()

    return [_row_to_dict(r) for r in rows]
