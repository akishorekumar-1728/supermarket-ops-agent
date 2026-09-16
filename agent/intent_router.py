"""
agent/intent_router.py
======================
Intent-based tool router for fast response times.

The #1 latency bottleneck is prompt token count: 19 tool schemas = 2667 tokens = 63s.
Sending only 4 relevant schemas = 519 tokens = ~3-5s.

This module classifies the user's intent from keyword matching (0ms, no LLM call)
and returns the minimal subset of tool schemas relevant for that intent.

Intent groups:
    inventory   → receive_stock, get_stock, get_low_stock, get_product
    billing     → create_bill, add_bill_item, remove_bill_item,
                  update_bill_item, finalize_bill, get_bill, get_product
    khata       → create_credit, record_credit_payment, get_credit_balance
    analytics   → daily_summary
    preferences → set_preference, get_preference
    products    → add_product, get_product
    documents   → generate_invoice_pdf, generate_sales_deck
    mixed       → billing + inventory (e.g. "finalize and print PDF")
"""
from __future__ import annotations
import re
from typing import Any

# ── Keyword lists for each intent ────────────────────────────────────────────

_INVENTORY_KW = frozenset([
    "stock", "arrived", "came in", "received", "intake", "stocked", "restock",
    "refill", "supply", "quantity", "left", "remaining", "how many", "how much",
    "low stock", "reorder", "shortage", "available", "godown", "items left",
    "stock level", "order more", "what is low", "ki stock", "aaya", "maal",
])

_BILLING_KW = frozenset([
    "bill", "billing", "invoice", "checkout", "sale", "sell", "selling",
    "make a bill", "create bill", "new bill", "add item", "remove item",
    "drop the", "change quantity", "update quantity", "finalize", "finalise",
    "complete sale", "close bill", "total", "cart", "customer bill",
    "gsm", "gst bill", "payment", "upi", "cash", "card", "credit payment bill",
    "cheque", "neft", "scan", "qr", "receipt",
])

_KHATA_KW = frozenset([
    "khata", "credit", "udhar", "balance", "owe", "owes", "debt", "due",
    "paid", "repay", "payment received", "customer credit", "on credit",
    "credit balance", "credit ledger", "ledger", "baaki", "dena", "lena",
    "ramesh", "suresh", "priya", "anita", "rajesh",  # customer names
])

_ANALYTICS_KW = frozenset([
    "summary", "report", "analytics", "sales report", "today's sales",
    "revenue", "daily report", "how much today", "how much we sold",
    "gst collected", "total sales", "daily summary", "yesterday", "earnings",
])

_PREFERENCE_KW = frozenset([
    "remember", "always", "default", "set preference", "configure",
    "setting", "prefer", "store name", "shop name", "alias", "shortcut",
    "assume upi", "assume cash", "default payment",
])

_PRODUCT_KW = frozenset([
    "new product", "new item", "add product", "catalogue", "catalog",
    "create product", "register product", "new sku", "product details",
])

_DOCUMENT_KW = frozenset([
    "pdf", "invoice pdf", "print", "download", "document",
    "pptx", "powerpoint", "deck", "presentation", "slides",
    "sales deck", "send invoice", "share invoice", "weekly deck",
    "monthly deck", "analysis deck",
])

# ── Schema groups ─────────────────────────────────────────────────────────────

def _schemas_for(names: list[str], all_schemas: list[dict]) -> list[dict]:
    name_set = set(names)
    return [s for s in all_schemas if s["function"]["name"] in name_set]


def route(user_message: str, all_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Classify user message intent and return a minimal relevant schema subset.

    Always fast (keyword regex, no LLM call).
    Falls back to full schema if ambiguous or multiple intents detected.
    """
    msg = user_message.lower()
    # Remove punctuation for cleaner matching
    msg_clean = re.sub(r"[^\w\s]", " ", msg)
    words = set(msg_clean.split())

    # Score each intent category
    inventory_score   = len(words & {w for kw in _INVENTORY_KW   for w in kw.split()})
    billing_score     = len(words & {w for kw in _BILLING_KW     for w in kw.split()})
    khata_score       = len(words & {w for kw in _KHATA_KW       for w in kw.split()})
    analytics_score   = len(words & {w for kw in _ANALYTICS_KW   for w in kw.split()})
    preference_score  = len(words & {w for kw in _PREFERENCE_KW  for w in kw.split()})
    product_score     = len(words & {w for kw in _PRODUCT_KW     for w in kw.split()})
    document_score    = len(words & {w for kw in _DOCUMENT_KW    for w in kw.split()})

    # Phrase-level overrides (more reliable than single words)
    if any(p in msg for p in ["make a bill", "create bill", "new bill",
                               "add item", "remove item", "drop the",
                               "finalize", "finalise", "make bill"]):
        billing_score += 5

    if any(p in msg for p in ["came in", "arrived", "how much", "how many",
                               "is left", "in stock", "stock level",
                               "low stock", "what is low", "restock"]):
        inventory_score += 5

    if any(p in msg for p in ["on credit", "on khata", "udhar", "baaki",
                               "balance", "khata", "paid back", "owes"]):
        khata_score += 5

    if any(p in msg for p in ["pdf", "invoice pdf", "print bill",
                               "sales deck", "pptx", "powerpoint"]):
        document_score += 5

    if any(p in msg for p in ["today's sales", "daily summary", "sales report",
                               "how much we sold", "gst collected"]):
        analytics_score += 5

    if any(p in msg for p in ["always assume", "set default", "remember that",
                               "default payment"]):
        preference_score += 5

    if any(p in msg for p in ["new product", "new item", "add product"]):
        product_score += 5

    # Determine dominant intent(s)
    scores = {
        "inventory":   inventory_score,
        "billing":     billing_score,
        "khata":       khata_score,
        "analytics":   analytics_score,
        "preferences": preference_score,
        "products":    product_score,
        "documents":   document_score,
    }

    max_score = max(scores.values())

    if max_score == 0:
        # Cannot classify — return all schemas (safe fallback)
        return all_schemas

    # Find all intents that scored at least 60% of the max (multi-intent support)
    threshold = max(2, int(max_score * 0.6))
    active = {k for k, v in scores.items() if v >= threshold}

    # Build minimal schema list
    schema_names: list[str] = []

    if "inventory" in active:
        schema_names += ["receive_stock", "get_stock", "get_low_stock", "get_product"]
    if "billing" in active:
        schema_names += ["create_bill", "add_bill_item", "remove_bill_item",
                         "update_bill_item", "finalize_bill", "get_bill", "get_product"]
    if "khata" in active:
        schema_names += ["create_credit", "record_credit_payment", "get_credit_balance"]
    if "analytics" in active:
        schema_names += ["daily_summary"]
    if "preferences" in active:
        schema_names += ["set_preference", "get_preference"]
    if "products" in active:
        schema_names += ["add_product", "get_product"]
    if "documents" in active:
        schema_names += ["generate_invoice_pdf", "generate_sales_deck", "get_bill"]
        # Also add billing if document intent detected (likely finalizing before PDF)
        schema_names += ["finalize_bill"]

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for n in schema_names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    result = _schemas_for(unique, all_schemas)

    # Sanity: if something went wrong or result is empty, use all schemas
    return result if result else all_schemas
