"""
agent/tools_registry.py
=======================
Registers every tool as an Ollama-compatible function schema
(name, description, JSON-schema of parameters).

Tool functions are also imported here so agent.py can look them
up by name and call them without an if-elif chain.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

# ── import every tool function ────────────────────────────────────────────
from tools.products import add_product, get_product
from tools.inventory import receive_stock, get_stock, get_low_stock
from tools.billing import (
    create_bill,
    add_bill_item,
    remove_bill_item,
    update_bill_item,
    finalize_bill,
    get_bill,
)
from tools.khata import create_credit, record_credit_payment, get_credit_balance
from tools.analytics import daily_summary
from tools.preferences import set_preference, get_preference

from documents.invoice import generate_invoice_pdf

# Placeholders for future document-generation tools
def generate_sales_deck(**kwargs: Any) -> dict[str, Any]:
    """Stub: will generate a sales summary deck. Not yet implemented."""
    return {"status": "not_implemented", "message": "generate_sales_deck not yet built."}


# ── callable registry: name -> Python function ───────────────────────────
TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "add_product":             add_product,
    "get_product":             get_product,
    "receive_stock":           receive_stock,
    "get_stock":               get_stock,
    "get_low_stock":           get_low_stock,
    "create_bill":             create_bill,
    "add_bill_item":           add_bill_item,
    "remove_bill_item":        remove_bill_item,
    "update_bill_item":        update_bill_item,
    "finalize_bill":           finalize_bill,
    "get_bill":                get_bill,
    "create_credit":           create_credit,
    "record_credit_payment":   record_credit_payment,
    "get_credit_balance":      get_credit_balance,
    "daily_summary":           daily_summary,
    "set_preference":          set_preference,
    "get_preference":          get_preference,
    "generate_invoice_pdf":    generate_invoice_pdf,
    "generate_sales_deck":     generate_sales_deck,
}


# ── Ollama tool schemas ───────────────────────────────────────────────────
TOOL_SCHEMAS: list[dict[str, Any]] = [
    # ── Products ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "add_product",
            "description": (
                "Add a brand-new product to the product catalogue. "
                "Use this only when the product does NOT yet exist. "
                "Requires all fields: SKU, name, unit (kg/pcs/pkt/litre), "
                "cost_price (what the shop paid), selling_price (what customer pays), "
                "MRP (printed on pack), GST rate (valid Indian slab: 0/5/12/18/28 %), "
                "HSN code, and reorder_level. "
                "Do NOT guess any price — ask the shopkeeper if missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sku":           {"type": "string", "description": "Unique stock-keeping unit code, e.g. TATA-SALT-1KG."},
                    "name":          {"type": "string", "description": "Human-readable product name, e.g. 'Tata Salt 1kg'."},
                    "unit":          {"type": "string", "description": "Selling unit: kg, pkt, pcs, bag, litre, etc."},
                    "cost_price":    {"type": "number", "description": "Landed cost per unit paid by the shop (>= 0)."},
                    "selling_price": {"type": "number", "description": "Price charged to customer per unit (>= cost_price)."},
                    "mrp":           {"type": "number", "description": "Maximum Retail Price printed on packaging (>= selling_price)."},
                    "gst_rate":      {"type": "number", "description": "GST percentage slab: 0, 5, 12, 18, or 28."},
                    "hsn_code":      {"type": "string", "description": "4-6 digit HSN/SAC code for GST invoicing."},
                    "reorder_level": {"type": "integer", "description": "Stock alert threshold: reorder when quantity <= this."},
                    "initial_stock": {"type": "number", "description": "Opening stock on hand (default 0)."},
                },
                "required": ["sku", "name", "unit", "cost_price", "selling_price",
                             "mrp", "gst_rate", "hsn_code", "reorder_level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": (
                "Look up a product by SKU (exact) or by partial name (fuzzy). "
                "Returns a list of all matches so you can ask for clarification "
                "when multiple products match — never guess. "
                "Use this before billing or any operation that needs product_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SKU or partial product name to search for."},
                },
                "required": ["query"],
            },
        },
    },

    # ── Inventory ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "receive_stock",
            "description": (
                "Record new stock arriving at the shop. "
                "Finds the product by name or SKU and atomically increments its quantity. "
                "Optionally updates cost_price and/or MRP if prices changed on the new batch. "
                "Use this when the shopkeeper says stock arrived / goods received."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_query": {"type": "string", "description": "Product name or SKU."},
                    "quantity":      {"type": "number", "description": "Quantity received (must be > 0)."},
                    "cost_price":    {"type": "number", "description": "New cost price if it changed (optional)."},
                    "mrp":           {"type": "number", "description": "New MRP if it changed (optional)."},
                },
                "required": ["product_query", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock",
            "description": (
                "Get the current stock quantity for a specific product. "
                "Also returns whether the product is currently low on stock "
                "(quantity <= reorder_level). Use this to answer 'how much X is left?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_query": {"type": "string", "description": "Product name or SKU."},
                },
                "required": ["product_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock",
            "description": (
                "Return all products whose stock quantity is at or below their reorder level. "
                "Sorted by urgency (shortfall) descending. "
                "Use this to generate a reorder list or answer 'what needs to be ordered?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    # ── Billing ──────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_bill",
            "description": (
                "Create a new draft bill. Returns the bill_id. "
                "Always call this first before adding items. "
                "Optionally supply payment_mode (cash/upi/card/credit)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_mode": {"type": "string", "description": "cash, upi, card, or credit (optional)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_bill_item",
            "description": (
                "Add a product line item to an existing draft bill. "
                "Computes taxable amount, CGST, SGST, and total using the product's GST rate. "
                "Does NOT deduct stock — stock only moves on finalization. "
                "Call once per product per bill."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id":       {"type": "integer", "description": "ID of the draft bill (from create_bill)."},
                    "product_query": {"type": "string", "description": "Product name or SKU."},
                    "quantity":      {"type": "number", "description": "Quantity to sell (> 0)."},
                },
                "required": ["bill_id", "product_query", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_bill_item",
            "description": (
                "Remove a product line item from a draft bill and recalculate totals. "
                "Only works on draft bills; rejects finalized/void bills."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id":       {"type": "integer", "description": "ID of the draft bill."},
                    "product_query": {"type": "string", "description": "Product name or SKU to remove."},
                },
                "required": ["bill_id", "product_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_bill_item",
            "description": (
                "Update the quantity of an existing line item in a draft bill and recalculate totals. "
                "Only works on draft bills."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id":       {"type": "integer", "description": "ID of the draft bill."},
                    "product_query": {"type": "string", "description": "Product name or SKU to update."},
                    "new_quantity":  {"type": "number", "description": "New quantity (> 0)."},
                },
                "required": ["bill_id", "product_query", "new_quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_bill",
            "description": (
                "Finalize a draft bill: validate stock, deduct inventory, assign invoice number, "
                "and mark status as 'finalized'. "
                "Rejects if any item oversells available stock or is priced below cost. "
                "Safe to retry with the same idempotency_key — will not double-deduct stock. "
                "Always call this to complete a sale — draft bills do NOT deduct stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id":          {"type": "integer", "description": "ID of the draft bill to finalize."},
                    "idempotency_key":  {"type": "string", "description": "Unique key for this finalize attempt (e.g. 'sale-2024-09-15-001')."},
                    "payment_mode":     {"type": "string", "description": "cash, upi, card, or credit."},
                    "payment_reference":{"type": "string", "description": "UPI transaction ID, card last-4, etc. (optional)."},
                },
                "required": ["bill_id", "idempotency_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bill",
            "description": (
                "Retrieve full bill details including all line items, GST breakdown, "
                "and totals. Use to confirm what's on a bill before finalizing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {"type": "integer", "description": "ID of the bill."},
                },
                "required": ["bill_id"],
            },
        },
    },

    # ── Khata ────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_credit",
            "description": (
                "Record a credit (debt) for a customer in the khata (credit ledger). "
                "Creates the customer automatically if they don't yet exist. "
                "Use when a customer takes goods on credit / udhar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer's full name."},
                    "amount":        {"type": "number", "description": "Credit amount in rupees (> 0)."},
                    "reference":     {"type": "string", "description": "Optional note, e.g. 'Weekly groceries'."},
                },
                "required": ["customer_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_credit_payment",
            "description": (
                "Record a payment received from a khata customer against their outstanding balance. "
                "Customer must already exist — will reject for unknown customers. "
                "Rejects overpayment (amount > outstanding balance). "
                "Use when a customer pays back their credit/udhar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer's full name."},
                    "amount":        {"type": "number", "description": "Payment amount in rupees (> 0, <= outstanding balance)."},
                    "reference":     {"type": "string", "description": "Optional note, e.g. 'GPay ref 12345'."},
                },
                "required": ["customer_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_credit_balance",
            "description": (
                "Get a khata customer's current outstanding balance (credits minus payments). "
                "Returns 0 if the customer doesn't exist or has no transactions. "
                "Use to answer 'how much does Ramesh owe?' or 'what is X's khata balance?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer's full name."},
                },
                "required": ["customer_name"],
            },
        },
    },

    # ── Analytics ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "daily_summary",
            "description": (
                "Generate daily sales analytics for a given date (defaults to today). "
                "Returns: total sales, number of bills, GST collected (with CGST/SGST split), "
                "sales breakdown by payment mode (cash/UPI/card), and top products by quantity and revenue. "
                "Use to answer questions like 'how much did we sell today?' or 'daily report'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format. Omit for today."},
                },
                "required": [],
            },
        },
    },

    # ── Preferences ──────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "set_preference",
            "description": (
                "Save a persistent app preference as a key-value pair. "
                "Well-known keys: 'default_payment_mode', 'store_name', 'gst_state_code'. "
                "Product aliases use 'product_alias:{alias}' -> SKU or product name. "
                "Settings survive app restarts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key":   {"type": "string", "description": "Preference key (e.g. 'default_payment_mode', 'product_alias:atta')."},
                    "value": {"type": "string", "description": "Preference value (e.g. 'upi', 'AASH-ATTA-5KG')."},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_preference",
            "description": (
                "Read a persistent app preference by key. "
                "Returns null/default if the key has never been set. "
                "Use before defaulting to hardcoded values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key":     {"type": "string", "description": "Preference key to read."},
                    "default": {"type": "string", "description": "Value to return if key is not set (optional)."},
                },
                "required": ["key"],
            },
        },
    },

    # ── Document stubs (future phases) ───────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "generate_invoice_pdf",
            "description": (
                "Generate a GST-compliant PDF invoice for a finalized bill. "
                "Can take either a numeric bill_id or an invoice_number string (e.g. 'INV-00001'). "
                "Returns the absolute file path to the generated PDF file in generated/. "
                "Use this whenever the user asks for a bill/invoice as a PDF or document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_id": {
                        "type": "string",
                        "description": "ID of the bill (e.g. 1) or the invoice number (e.g. 'INV-00001').",
                    },
                },
                "required": ["bill_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_sales_deck",
            "description": (
                "Generate a sales summary presentation/report. "
                "NOT YET IMPLEMENTED — will be added in a future phase."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                },
                "required": [],
            },
        },
    },
]
