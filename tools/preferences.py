"""
tools/preferences.py
====================
Persistent key-value preferences backed by the SQLite 'preferences' table.

Well-known keys (documented below as module constants) can be consulted
by the billing and other flows at runtime.  The key namespace is
intentionally open-ended — any string key is valid, so new preferences
can be added without code changes.

Well-known key conventions
--------------------------
PREF_DEFAULT_PAYMENT_MODE = "default_payment_mode"
    Value: one of "cash", "upi", "card", "credit".
    Used by the billing flow when the customer hasn't specified a mode.

PREF_PRODUCT_ALIAS_PREFIX = "product_alias:"
    Pattern: "product_alias:{alias}" -> SKU or product name fragment.
    Example: set_preference("product_alias:atta", "AASH-ATTA-5KG")
    The billing agent can expand a short alias like "atta" to the
    canonical product before calling add_bill_item().

PREF_STORE_NAME = "store_name"
    Value: Free-text shop name printed on GST invoices.

PREF_GST_STATE_CODE = "gst_state_code"
    Value: 2-digit Indian state code for the shop's GSTIN (e.g. "33" for TN).
"""
from __future__ import annotations

import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# Well-known key constants (add more as needed — keep generic, not hardcoded)
# ---------------------------------------------------------------------------
PREF_DEFAULT_PAYMENT_MODE: str = "default_payment_mode"
PREF_PRODUCT_ALIAS_PREFIX: str = "product_alias:"
PREF_STORE_NAME: str = "store_name"
PREF_GST_STATE_CODE: str = "gst_state_code"


def set_preference(
    key: str,
    value: str,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> None:
    """
    Upsert a preference key→value pair into the 'preferences' table,
    updating updated_at on every write.

    Parameters:
        key:   Preference key string (non-empty).
        value: Preference value (any string; non-None).
        conn:  Open sqlite3.Connection.

    Raises:
        ValueError: If key is empty/None or value is None.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("set_preference requires an open sqlite3.Connection (conn).")
    if not key or not str(key).strip():
        raise ValueError("Preference key must be non-empty.")
    if value is None:
        raise ValueError(f"Preference value for {key!r} must not be None.")

    key = str(key).strip()
    value = str(value)

    with c:
        c.execute(
            """
            INSERT INTO preferences (key, value, updated_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            """,
            (key, value),
        )


def get_preference(
    key: str,
    default: str | None = None,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> str | None:
    """
    Read a preference from the 'preferences' table.
    Returns *default* (None unless supplied) when the key is not set.

    Parameters:
        key:     Preference key to look up.
        default: Value to return if the key is absent.
        conn:    Open sqlite3.Connection.

    Returns:
        Stored string value or *default*.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("get_preference requires an open sqlite3.Connection (conn).")
    if not key or not str(key).strip():
        raise ValueError("Preference key must be non-empty.")

    key = str(key).strip()
    row = c.execute(
        "SELECT value FROM preferences WHERE key = ?", (key,)
    ).fetchone()

    return row["value"] if row else default


def get_product_alias(
    alias: str,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> str | None:
    """
    Convenience wrapper: look up a product alias registered as
    'product_alias:{alias}' and return the target SKU/name, or None.

    Example:
        set_preference("product_alias:atta", "AASH-ATTA-5KG", conn=conn)
        get_product_alias("atta", conn=conn)  # -> "AASH-ATTA-5KG"
    """
    c = conn or kwargs.get("conn")
    pref_key = f"{PREF_PRODUCT_ALIAS_PREFIX}{alias.strip().lower()}"
    return get_preference(pref_key, default=None, conn=c)


def set_product_alias(
    alias: str,
    target: str,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> None:
    """
    Register a short alias for a product SKU or name fragment.

    Example:
        set_product_alias("atta", "AASH-ATTA-5KG", conn=conn)
        # billing agent can expand "atta" -> "AASH-ATTA-5KG" before lookup
    """
    c = conn or kwargs.get("conn")
    pref_key = f"{PREF_PRODUCT_ALIAS_PREFIX}{alias.strip().lower()}"
    set_preference(pref_key, target, conn=c)
