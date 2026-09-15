"""
database/seed.py
================
Seeds the database with realistic Indian kirana-store products.

GST rates applied (as per Indian tax slabs, approximate):
  - 0%  : loose staples (atta, rice, dal, sugar)  – HSN 1006/1702/1701/1101
  - 5%  : packaged staples (Aashirvaad Atta, Tata Salt, Maggi, Parle-G, oil)
  - 12% : packaged foods (Amul Butter)
  - 18% : FMCG detergents (Surf Excel)

Reorder levels are set deliberately:
  - Some products start BELOW reorder level so get_low_stock() has results.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SeedProduct:
    sku:           str
    name:          str
    unit:          str
    cost_price:    float
    selling_price: float
    mrp:           float
    gst_rate:      float    # percentage (0, 5, 12, 18)
    hsn_code:      str
    reorder_level: int
    initial_stock: float    # some deliberately at/below reorder_level


# ---------------------------------------------------------------------------
# Seed data – 10 realistic Indian kirana products
# ---------------------------------------------------------------------------

PRODUCTS: list[SeedProduct] = [
    # ── Packaged staples (5% GST) ─────────────────────────────────────────
    SeedProduct(
        sku="AASH-ATTA-5KG",
        name="Aashirvaad Atta 5kg",
        unit="bag",
        cost_price=195.00,
        selling_price=220.00,
        mrp=235.00,
        gst_rate=5.0,
        hsn_code="1101",
        reorder_level=10,
        initial_stock=8,   # BELOW reorder → triggers low-stock alert
    ),
    SeedProduct(
        sku="TATA-SALT-1KG",
        name="Tata Salt 1kg",
        unit="pkt",
        cost_price=18.00,
        selling_price=22.00,
        mrp=24.00,
        gst_rate=5.0,
        hsn_code="2501",
        reorder_level=20,
        initial_stock=20,  # AT reorder level
    ),
    SeedProduct(
        sku="MAGI-NOODL-70G",
        name="Maggi Noodles 70g",
        unit="pkt",
        cost_price=12.00,
        selling_price=15.00,
        mrp=15.00,
        gst_rate=5.0,
        hsn_code="1902",
        reorder_level=30,
        initial_stock=25,  # BELOW reorder → triggers low-stock alert
    ),
    SeedProduct(
        sku="PARL-G-BSCT",
        name="Parle-G Biscuits 800g",
        unit="pkt",
        cost_price=38.00,
        selling_price=45.00,
        mrp=50.00,
        gst_rate=5.0,
        hsn_code="1905",
        reorder_level=15,
        initial_stock=40,
    ),
    SeedProduct(
        sku="FORT-OIL-1L",
        name="Fortune Sunflower Oil 1L",
        unit="litre",
        cost_price=135.00,
        selling_price=150.00,
        mrp=165.00,
        gst_rate=5.0,
        hsn_code="1512",
        reorder_level=12,
        initial_stock=18,
    ),
    # ── FMCG – Dairy (12% GST) ────────────────────────────────────────────
    SeedProduct(
        sku="AMUL-BUTR-100G",
        name="Amul Butter 100g",
        unit="pkt",
        cost_price=52.00,
        selling_price=60.00,
        mrp=65.00,
        gst_rate=12.0,
        hsn_code="0405",
        reorder_level=10,
        initial_stock=7,   # BELOW reorder → triggers low-stock alert
    ),
    # ── FMCG – Detergent (18% GST) ───────────────────────────────────────
    SeedProduct(
        sku="SURF-EXCE-1KG",
        name="Surf Excel Washing Powder 1kg",
        unit="pkt",
        cost_price=155.00,
        selling_price=185.00,
        mrp=195.00,
        gst_rate=18.0,
        hsn_code="3402",
        reorder_level=8,
        initial_stock=5,   # BELOW reorder → triggers low-stock alert
    ),
    # ── Loose staples sold by weight (0% GST) ────────────────────────────
    SeedProduct(
        sku="LOOS-SUGR-KG",
        name="Sugar (loose)",
        unit="kg",
        cost_price=38.00,
        selling_price=44.00,
        mrp=50.00,
        gst_rate=0.0,
        hsn_code="1701",
        reorder_level=20,
        initial_stock=35,
    ),
    SeedProduct(
        sku="LOOS-RICE-KG",
        name="Rice Sona Masoori (loose)",
        unit="kg",
        cost_price=52.00,
        selling_price=62.00,
        mrp=70.00,
        gst_rate=0.0,
        hsn_code="1006",
        reorder_level=25,
        initial_stock=15,  # BELOW reorder → triggers low-stock alert
    ),
    SeedProduct(
        sku="LOOS-TOOR-KG",
        name="Toor Dal (loose)",
        unit="kg",
        cost_price=88.00,
        selling_price=105.00,
        mrp=120.00,
        gst_rate=0.0,
        hsn_code="0713",
        reorder_level=20,
        initial_stock=30,
    ),
]


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def seed(conn: sqlite3.Connection, *, clear: bool = False) -> None:
    """
    Insert seed products and their initial stock rows into *conn*.

    Parameters
    ----------
    conn:
        An open, configured SQLite connection (WAL + FK enforcement enabled).
    clear:
        If True, truncate products and stock before seeding.  Useful for
        idempotent test runs.  Default is False.
    """
    cur = conn.cursor()

    if clear:
        cur.execute("DELETE FROM stock")
        cur.execute("DELETE FROM products")

    for p in PRODUCTS:
        # Upsert product (skip if SKU already exists)
        cur.execute(
            """
            INSERT INTO products
                (sku, name, unit, cost_price, selling_price, mrp,
                 gst_rate, hsn_code, reorder_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO NOTHING
            """,
            (
                p.sku, p.name, p.unit, p.cost_price, p.selling_price,
                p.mrp, p.gst_rate, p.hsn_code, p.reorder_level,
            ),
        )

        # Retrieve the product id (whether just inserted or pre-existing)
        product_id = cur.execute(
            "SELECT id FROM products WHERE sku = ?", (p.sku,)
        ).fetchone()["id"]

        # Upsert stock row
        cur.execute(
            """
            INSERT INTO stock (product_id, quantity)
            VALUES (?, ?)
            ON CONFLICT(product_id) DO NOTHING
            """,
            (product_id, p.initial_stock),
        )

    conn.commit()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Allow optional DB path as first argument
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/supermarket.db")

    # Import connection helper relative-safe
    import importlib.util, os

    _here = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "connection", _here / "connection.py"
    )
    connection_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(connection_mod)

    conn = connection_mod.get_and_init(db_path)
    seed(conn)

    print(f"[seed] Seeded {len(PRODUCTS)} products into {db_path}")
    row = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()
    print(f"[seed] Total products in DB : {row['n']}")
    row = conn.execute("SELECT COUNT(*) AS n FROM stock").fetchone()
    print(f"[seed] Total stock rows     : {row['n']}")
    conn.close()
