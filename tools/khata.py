"""
tools/khata.py
==============
Khata credit ledger management tools for the Supermarket Ops Agent.

Operations:
- create_credit(customer_name, amount, reference=None, conn=None)
    Finds or creates a customer by name, records a credit transaction (debt owed
    to the shop), and returns the new outstanding balance.
- record_credit_payment(customer_name, amount, reference=None, conn=None)
    Finds existing customer (rejects if nonexistent), records a payment transaction,
    and returns the new balance. Rejects invalid amounts (<= 0) or overpayments
    that would make the balance negative.
- get_credit_balance(customer_name, conn=None)
    Derives outstanding balance dynamically from transaction history:
    SUM(credits) - SUM(payments). Balance is never stored as a cached column.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any


class CustomerNotFoundError(LookupError):
    """Raised when an operation targets a nonexistent customer."""


class InvalidTransactionError(ValueError):
    """Raised when transaction parameters violate validation rules."""


def _normalize_name(name: str) -> str:
    if not name or not str(name).strip():
        raise InvalidTransactionError("Customer name must be non-empty.")
    return str(name).strip()


def _normalize_amount(amount: float | Decimal) -> float:
    try:
        amt = float(amount)
    except (TypeError, ValueError) as exc:
        raise InvalidTransactionError(f"Amount must be numeric: {exc}") from exc

    if amt <= 0:
        raise InvalidTransactionError(f"Amount must be positive (> 0), got {amt}")
    return round(amt, 2)


def get_credit_balance(
    customer_name: str,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> float:
    """
    Compute and return the customer's outstanding balance dynamically
    from durable transaction history:
        balance = SUM(credits) - SUM(payments)

    Parameters:
        customer_name: Full or partial name of customer.
        conn: Open sqlite3.Connection (positional or keyword).

    Returns:
        Outstanding balance as float (0.0 if customer does not exist or has no transactions).
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("get_credit_balance requires an open sqlite3.Connection (conn).")

    name = _normalize_name(customer_name)

    row = c.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN kt.type = 'credit' THEN kt.amount ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN kt.type = 'payment' THEN kt.amount ELSE 0 END), 0) AS balance
        FROM khata_customers kc
        LEFT JOIN khata_transactions kt ON kt.customer_id = kc.id
        WHERE LOWER(kc.name) = LOWER(?)
        """,
        (name,),
    ).fetchone()

    if not row:
        return 0.0

    return round(float(row["balance"]), 2)


def create_credit(
    customer_name: str,
    amount: float | Decimal,
    reference: str | None = None,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> float:
    """
    Find or create the customer by name, insert a 'credit' transaction row,
    and return the updated outstanding balance.

    Parameters:
        customer_name: Customer name.
        amount: Credit amount (> 0).
        reference: Optional reference note (e.g. invoice number or memo).
        conn: Open sqlite3.Connection.

    Returns:
        New outstanding balance as float.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("create_credit requires an open sqlite3.Connection (conn).")

    name = _normalize_name(customer_name)
    amt = _normalize_amount(amount)

    with c:
        # Find or create customer
        cust_row = c.execute(
            "SELECT id FROM khata_customers WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()

        if cust_row:
            cust_id = cust_row["id"]
        else:
            cur = c.execute(
                "INSERT INTO khata_customers (name) VALUES (?)", (name,)
            )
            cust_id = cur.lastrowid

        # Insert credit transaction
        c.execute(
            """
            INSERT INTO khata_transactions (customer_id, type, amount, reference)
            VALUES (?, 'credit', ?, ?)
            """,
            (cust_id, amt, reference),
        )

    return get_credit_balance(name, conn=c)


def record_credit_payment(
    customer_name: str,
    amount: float | Decimal,
    reference: str | None = None,
    conn: sqlite3.Connection | None = None,
    **kwargs: Any,
) -> float:
    """
    Find existing customer (rejects if customer does not exist), insert
    a 'payment' transaction row, and return the new balance.

    Rejection rules:
    - Rejects if customer does not exist (does not silently auto-create).
    - Rejects if amount <= 0.
    - Rejects if payment amount > current balance (overpayment prevention:
      an Indian kirana khata tracks store credit owed by customers; a customer
      cannot overpay to create negative debt balance).

    Parameters:
        customer_name: Customer name.
        amount: Payment amount (> 0).
        reference: Optional reference note (e.g., 'UPI-REF-1234', 'Cash payment').
        conn: Open sqlite3.Connection.

    Returns:
        New outstanding balance as float.
    """
    c = conn or kwargs.get("conn")
    if c is None:
        raise ValueError("record_credit_payment requires an open sqlite3.Connection (conn).")

    name = _normalize_name(customer_name)
    amt = _normalize_amount(amount)

    # Check customer existence
    cust_row = c.execute(
        "SELECT id, name FROM khata_customers WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()

    if not cust_row:
        raise CustomerNotFoundError(
            f"Customer {customer_name!r} does not exist. Cannot record payment for an unknown customer."
        )

    cust_id = cust_row["id"]
    current_balance = get_credit_balance(name, conn=c)

    # Prevent overpayment that would turn balance negative
    if amt > current_balance:
        raise InvalidTransactionError(
            f"Payment amount (₹{amt:.2f}) exceeds current outstanding balance (₹{current_balance:.2f}). "
            f"Overpayment is not permitted."
        )

    with c:
        c.execute(
            """
            INSERT INTO khata_transactions (customer_id, type, amount, reference)
            VALUES (?, 'payment', ?, ?)
            """,
            (cust_id, amt, reference),
        )

    return get_credit_balance(name, conn=c)
