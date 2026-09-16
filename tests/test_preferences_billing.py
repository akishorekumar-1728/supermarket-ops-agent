"""
tests/test_preferences_billing.py
==================================
Integration tests verifying preferences affect agent behavior and billing flows
across complete database/process restarts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init, get_connection
from database.seed import seed
from tools.preferences import get_preference, set_preference, PREF_DEFAULT_PAYMENT_MODE
from tools.billing import create_bill, add_bill_item, finalize_bill, get_bill
from agent.agent import chat_turn

TEST_MODEL = os.environ.get("OLLAMA_TEST_MODEL", "llama3.2:3b")


@pytest.fixture()
def db_path(tmp_path):
    """DB file path with seed data."""
    path = tmp_path / "pref_billing_test.db"
    c = get_and_init(path)
    seed(c, clear=True)
    c.close()
    return path


class TestPreferencesBillingIntegration:
    def test_default_payment_mode_preference_used_in_billing_functions(self, db_path):
        """
        Direct Python-level check:
        When set_preference('default_payment_mode', 'upi') is configured,
        create_bill and finalize_bill default to 'upi' when no payment_mode is supplied.
        """
        conn1 = get_connection(db_path)
        set_preference(PREF_DEFAULT_PAYMENT_MODE, "upi", conn=conn1)
        conn1.close()

        # Restart connection (simulating restart)
        conn2 = get_connection(db_path)
        bill_id = create_bill(conn=conn2)
        add_bill_item(bill_id, "Tata Salt", 1, conn=conn2)
        finalized = finalize_bill(bill_id, idempotency_key="pref-bill-1", conn=conn2)
        conn2.close()

        assert finalized["payment_mode"] == "upi"

    def test_agent_stores_preference_and_uses_it_after_restart(self, db_path):
        """
        End-to-End Agent test:
        1. Session 1: Send preference instruction -> agent calls set_preference.
        2. Session 2: Multi-turn billing sequence (create, add item, finalize) with no payment
           mode — confirm the finalized bill inherits the stored UPI preference.
        """
        # ── Session 1: store the preference ──────────────────────────────────
        conn1 = get_connection(db_path)
        prompt1 = "always assume UPI unless I say cash"
        reply1, history1, tools1 = chat_turn(
            prompt1, conn=conn1, model=TEST_MODEL, timeout=180
        )
        conn1.close()

        assert any(t["tool"] == "set_preference" for t in tools1), (
            f"Expected set_preference tool call in session 1, got: {tools1}"
        )

        conn_check = get_connection(db_path)
        stored_pref = get_preference(PREF_DEFAULT_PAYMENT_MODE, conn=conn_check)
        conn_check.close()
        assert stored_pref == "upi", f"Preference not persisted: {stored_pref!r}"

        # ── Session 2: completely new connection + empty conversation history ─
        conn2 = get_connection(db_path)
        history2: list = []

        # Step A: create the draft bill
        _, history2, tools_a = chat_turn(
            "Create a new bill",
            conversation_history=history2,
            conn=conn2,
            model=TEST_MODEL,
            timeout=180,
        )
        assert any(t["tool"] == "create_bill" for t in tools_a), (
            f"Expected create_bill in step A, got: {tools_a}"
        )

        # Step B: add 2 Maggi to the bill
        _, history2, tools_b = chat_turn(
            "Add 2 Maggi to the bill",
            conversation_history=history2,
            conn=conn2,
            model=TEST_MODEL,
            timeout=180,
        )
        assert any(t["tool"] == "add_bill_item" for t in tools_b), (
            f"Expected add_bill_item in step B, got: {tools_b}"
        )

        # Step C: finalize — no payment mode specified; preference should kick in
        _, history2, tools_c = chat_turn(
            "Finalize the bill",
            conversation_history=history2,
            conn=conn2,
            model=TEST_MODEL,
            timeout=180,
        )
        assert any(t["tool"] == "finalize_bill" for t in tools_c), (
            f"Expected finalize_bill in step C, got: {tools_c}"
        )

        # Verify DB: finalized bill must have payment_mode = 'upi'
        finalized_bills = conn2.execute(
            "SELECT * FROM bills WHERE status = 'finalized'"
        ).fetchall()
        conn2.close()

        assert len(finalized_bills) >= 1, "No finalized bills found in DB"
        last_bill = dict(finalized_bills[-1])
        assert last_bill["payment_mode"] == "upi", (
            f"Expected payment_mode='upi', got {last_bill['payment_mode']!r}"
        )
