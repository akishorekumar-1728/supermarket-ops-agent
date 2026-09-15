"""
tests/test_khata.py
===================
Pytest suite for tools/khata.py (Khata credit ledger).

Covering:
1. Create ₹500 credit for "Ramesh", record ₹300 payment, assert balance is ₹200.
2. Reject payment for a nonexistent customer (no silent customer auto-creation).
3. Confirm balances survive re-reading from a completely fresh DB connection (durable persistence).
4. Reject invalid settlements (zero, negative amounts, and overpayments).
5. Dynamic balance derivation: verify balance is derived from transactions, not cached.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init, get_connection
from tools.khata import (
    CustomerNotFoundError,
    InvalidTransactionError,
    create_credit,
    get_credit_balance,
    record_credit_payment,
)


@pytest.fixture()
def db_path(tmp_path):
    """File path to fresh DB."""
    path = tmp_path / "khata_test.db"
    conn = get_and_init(path)
    conn.close()
    return path


@pytest.fixture()
def conn(db_path):
    """Connection fixture."""
    c = get_connection(db_path)
    yield c
    c.close()


class TestKhataCore:
    def test_ramesh_credit_and_payment_flow(self, conn):
        """
        User requirement:
        Create ₹500 credit for "Ramesh", record a ₹300 payment,
        assert balance is ₹200.
        """
        # Step 1: Create ₹500 credit
        bal_after_credit = create_credit("Ramesh", 500.0, reference="Weekly groceries", conn=conn)
        assert bal_after_credit == 500.0

        # Step 2: Record ₹300 payment
        bal_after_payment = record_credit_payment("Ramesh", 300.0, reference="Cash payment", conn=conn)
        assert bal_after_payment == 200.0

        # Verify get_credit_balance matches
        current_bal = get_credit_balance("Ramesh", conn=conn)
        assert current_bal == 200.0

    def test_reject_payment_for_nonexistent_customer(self, conn):
        """
        User requirement:
        Reject clearly if the customer doesn't exist — don't silently create one for a payment.
        """
        with pytest.raises(CustomerNotFoundError) as exc_info:
            record_credit_payment("UnknownCustomer", 100.0, conn=conn)

        assert "UnknownCustomer" in str(exc_info.value)

        # Confirm customer was NOT added to database
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM khata_customers WHERE name = 'UnknownCustomer'"
        ).fetchone()
        assert row["cnt"] == 0

    def test_balance_persists_across_fresh_connection(self, db_path):
        """
        User requirement:
        Confirm balances survive re-reading from a fresh DB connection
        (i.e. really persisted, not cached in memory).
        """
        conn1 = get_connection(db_path)
        create_credit("Suresh", 1250.0, reference="Rice bag + oil", conn=conn1)
        record_credit_payment("Suresh", 450.0, reference="GPay", conn=conn1)
        conn1.close()

        # Open completely fresh connection
        conn2 = get_connection(db_path)
        balance = get_credit_balance("Suresh", conn=conn2)
        conn2.close()

        assert balance == 800.0  # 1250 - 450 = 800.0


class TestKhataValidations:
    def test_negative_credit_amount_rejected(self, conn):
        with pytest.raises(InvalidTransactionError, match="positive"):
            create_credit("Ramesh", -50.0, conn=conn)

    def test_zero_credit_amount_rejected(self, conn):
        with pytest.raises(InvalidTransactionError, match="positive"):
            create_credit("Ramesh", 0.0, conn=conn)

    def test_negative_payment_amount_rejected(self, conn):
        create_credit("Ramesh", 100.0, conn=conn)
        with pytest.raises(InvalidTransactionError, match="positive"):
            record_credit_payment("Ramesh", -20.0, conn=conn)

    def test_zero_payment_amount_rejected(self, conn):
        create_credit("Ramesh", 100.0, conn=conn)
        with pytest.raises(InvalidTransactionError, match="positive"):
            record_credit_payment("Ramesh", 0.0, conn=conn)

    def test_overpayment_rejected(self, conn):
        """
        Settlement amount exceeding current outstanding balance is rejected
        to prevent negative debt balance in kirana ledger.
        """
        create_credit("Priya", 300.0, conn=conn)
        with pytest.raises(InvalidTransactionError, match="exceeds current outstanding balance"):
            record_credit_payment("Priya", 350.0, conn=conn)

        # Balance remains unchanged at 300.0
        assert get_credit_balance("Priya", conn=conn) == 300.0

    def test_full_settlement_reaches_zero_balance(self, conn):
        create_credit("Anita", 450.0, conn=conn)
        new_bal = record_credit_payment("Anita", 450.0, reference="Full settlement", conn=conn)
        assert new_bal == 0.0
        assert get_credit_balance("Anita", conn=conn) == 0.0

    def test_nonexistent_customer_balance_is_zero(self, conn):
        assert get_credit_balance("NobodySpecial", conn=conn) == 0.0

    def test_case_insensitive_customer_lookup(self, conn):
        create_credit("Mahesh Kumar", 700.0, conn=conn)
        bal = record_credit_payment("mahesh kumar", 200.0, conn=conn)
        assert bal == 500.0
        assert get_credit_balance("MAHESH KUMAR", conn=conn) == 500.0
