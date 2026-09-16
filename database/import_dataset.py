"""
database/import_dataset.py
==========================
Imports the comprehensive supermarket dataset from data/supermarket_catalog.json
into the active SQLite database (data/supermarket.db).

Imports:
  - 50+ real Indian supermarket products across all retail categories
  - Opening stock on hand for every item
  - Store metadata preferences (name, GSTIN, default payment mode)
  - Khata customers and opening credit balances
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from tools.preferences import set_preference
from tools.khata import create_credit

DEFAULT_JSON = ROOT / "data" / "supermarket_catalog.json"
DEFAULT_DB = ROOT / "data" / "supermarket.db"


def import_dataset(
    json_path: Path | str = DEFAULT_JSON,
    db_path: Path | str = DEFAULT_DB,
    *,
    clear: bool = False,
) -> dict[str, int]:
    """
    Import supermarket catalog JSON into the database.

    Returns dict of counts: products_imported, customers_imported, preferences_set.
    """
    json_path = Path(json_path)
    db_path = Path(db_path)

    if not json_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_and_init(db_path)
    cur = conn.cursor()

    if clear:
        cur.execute("DELETE FROM bill_items")
        cur.execute("DELETE FROM bills")
        cur.execute("DELETE FROM khata_transactions")
        cur.execute("DELETE FROM khata_customers")
        cur.execute("DELETE FROM stock")
        cur.execute("DELETE FROM products")
        cur.execute("DELETE FROM preferences")

    # 1. Store preferences
    prefs = data.get("store_info", {})
    pref_count = 0
    for k, v in prefs.items():
        set_preference(k, str(v), conn=conn)
        pref_count += 1

    # 2. Products & Stock
    products = data.get("products", [])
    prod_count = 0
    for p in products:
        cur.execute(
            """
            INSERT INTO products (
                sku, name, unit, cost_price, selling_price, mrp,
                gst_rate, hsn_code, reorder_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku) DO UPDATE SET
                cost_price = excluded.cost_price,
                selling_price = excluded.selling_price,
                mrp = excluded.mrp,
                gst_rate = excluded.gst_rate,
                reorder_level = excluded.reorder_level
            """,
            (
                p["sku"],
                p["name"],
                p["unit"],
                float(p["cost_price"]),
                float(p["selling_price"]),
                float(p["mrp"]),
                float(p.get("gst_rate", 0)),
                str(p.get("hsn_code", "")),
                int(p.get("reorder_level", 0)),
            ),
        )

        prod_id = cur.execute("SELECT id FROM products WHERE sku = ?", (p["sku"],)).fetchone()["id"]

        cur.execute(
            """
            INSERT INTO stock (product_id, quantity)
            VALUES (?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                quantity = excluded.quantity
            """,
            (prod_id, float(p.get("initial_stock", 0))),
        )
        prod_count += 1

    # 3. Customers & initial khata credit
    customers = data.get("customers", [])
    cust_count = 0
    for c in customers:
        name = c["name"]
        initial_credit = float(c.get("initial_credit", 0))
        if initial_credit > 0:
            create_credit(name, initial_credit, reference=c.get("reference", "Opening balance"), conn=conn)
        else:
            cur.execute(
                "INSERT INTO khata_customers (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
                (name,),
            )
        cust_count += 1

    conn.commit()
    conn.close()

    return {
        "products_imported": prod_count,
        "customers_imported": cust_count,
        "preferences_set": pref_count,
    }


if __name__ == "__main__":
    db_target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    print(f"Importing dataset into {db_target}...")
    stats = import_dataset(db_path=db_target)
    print(f"✅ Imported {stats['products_imported']} products & stock rows")
    print(f"✅ Imported {stats['customers_imported']} customers & khata balances")
    print(f"✅ Set {stats['preferences_set']} store preferences")
