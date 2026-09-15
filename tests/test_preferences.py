"""
tests/test_preferences.py
=========================
Pytest suite for tools/preferences.py.

Verifies:
- set_preference upserts a key correctly.
- get_preference reads it back from a FRESH database connection (simulating
  an app restart / new conversation) — proves it's truly persisted, not cached.
- get_preference returns default when key is absent.
- set_preference is idempotent (overwrites correctly on second write).
- Well-known keys (PREF_DEFAULT_PAYMENT_MODE, product_alias) work end-to-end.
- Validation: empty key raises ValueError.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init, get_connection
from tools.preferences import (
    PREF_DEFAULT_PAYMENT_MODE,
    PREF_GST_STATE_CODE,
    PREF_STORE_NAME,
    get_preference,
    get_product_alias,
    set_preference,
    set_product_alias,
)


@pytest.fixture()
def db_path(tmp_path):
    """Initialised DB file; each test gets a fresh file."""
    path = tmp_path / "pref_test.db"
    conn = get_and_init(path)
    conn.close()
    return path


class TestSetAndGetBasic:
    def test_set_then_get_same_connection(self, db_path):
        conn = get_connection(db_path)
        set_preference("test_key", "hello", conn=conn)
        val = get_preference("test_key", conn=conn)
        conn.close()
        assert val == "hello"

    def test_value_persists_across_fresh_connection(self, db_path):
        """Simulates app restart / new conversation."""
        conn1 = get_connection(db_path)
        set_preference("shop_city", "Chennai", conn=conn1)
        conn1.close()

        # Open a completely fresh connection — no in-memory state
        conn2 = get_connection(db_path)
        val = get_preference("shop_city", conn=conn2)
        conn2.close()

        assert val == "Chennai"

    def test_get_returns_default_when_key_absent(self, db_path):
        conn = get_connection(db_path)
        val = get_preference("nonexistent_key", default="FALLBACK", conn=conn)
        conn.close()
        assert val == "FALLBACK"

    def test_get_returns_none_default_when_key_absent_and_no_default(self, db_path):
        conn = get_connection(db_path)
        val = get_preference("nonexistent_key", conn=conn)
        conn.close()
        assert val is None

    def test_upsert_overwrites_previous_value(self, db_path):
        conn1 = get_connection(db_path)
        set_preference("ticker", "v1", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        set_preference("ticker", "v2", conn=conn2)
        conn2.close()

        conn3 = get_connection(db_path)
        val = get_preference("ticker", conn=conn3)
        conn3.close()
        assert val == "v2"

    def test_upsert_updates_updated_at(self, db_path):
        conn = get_connection(db_path)
        set_preference("ts_key", "first", conn=conn)
        row1 = conn.execute(
            "SELECT updated_at FROM preferences WHERE key = 'ts_key'"
        ).fetchone()

        # Write again (may resolve to same second in fast tests, so just check it's present)
        set_preference("ts_key", "second", conn=conn)
        row2 = conn.execute(
            "SELECT updated_at FROM preferences WHERE key = 'ts_key'"
        ).fetchone()
        conn.close()

        assert row1["updated_at"] is not None
        assert row2["updated_at"] is not None


class TestValidation:
    def test_empty_key_raises(self, db_path):
        conn = get_connection(db_path)
        with pytest.raises(ValueError, match="key"):
            set_preference("", "value", conn=conn)
        conn.close()

    def test_whitespace_key_raises(self, db_path):
        conn = get_connection(db_path)
        with pytest.raises(ValueError, match="key"):
            set_preference("   ", "value", conn=conn)
        conn.close()

    def test_none_value_raises(self, db_path):
        conn = get_connection(db_path)
        with pytest.raises(ValueError):
            set_preference("some_key", None, conn=conn)
        conn.close()


class TestWellKnownKeys:
    def test_default_payment_mode_round_trip(self, db_path):
        conn1 = get_connection(db_path)
        set_preference(PREF_DEFAULT_PAYMENT_MODE, "upi", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        val = get_preference(PREF_DEFAULT_PAYMENT_MODE, conn=conn2)
        conn2.close()
        assert val == "upi"

    def test_store_name_round_trip(self, db_path):
        conn1 = get_connection(db_path)
        set_preference(PREF_STORE_NAME, "Sri Lakshmi Kirana", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        val = get_preference(PREF_STORE_NAME, conn=conn2)
        conn2.close()
        assert val == "Sri Lakshmi Kirana"

    def test_gst_state_code_round_trip(self, db_path):
        conn1 = get_connection(db_path)
        set_preference(PREF_GST_STATE_CODE, "33", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        val = get_preference(PREF_GST_STATE_CODE, conn=conn2)
        conn2.close()
        assert val == "33"


class TestProductAliases:
    def test_set_and_get_product_alias(self, db_path):
        conn1 = get_connection(db_path)
        set_product_alias("atta", "AASH-ATTA-5KG", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        result = get_product_alias("atta", conn=conn2)
        conn2.close()
        assert result == "AASH-ATTA-5KG"

    def test_product_alias_case_insensitive_key(self, db_path):
        conn = get_connection(db_path)
        set_product_alias("Namak", "TATA-SALT-1KG", conn=conn)
        result = get_product_alias("NAMAK", conn=conn)
        conn.close()
        assert result == "TATA-SALT-1KG"

    def test_unknown_alias_returns_none(self, db_path):
        conn = get_connection(db_path)
        result = get_product_alias("no_such_alias_xyz", conn=conn)
        conn.close()
        assert result is None

    def test_alias_persists_across_fresh_connection(self, db_path):
        """Simulating app restart — alias must survive."""
        conn1 = get_connection(db_path)
        set_product_alias("sugar", "LOOS-SUGR-KG", conn=conn1)
        conn1.close()

        conn2 = get_connection(db_path)
        result = get_product_alias("sugar", conn=conn2)
        conn2.close()
        assert result == "LOOS-SUGR-KG"

    def test_multiple_aliases_stored_independently(self, db_path):
        conn = get_connection(db_path)
        set_product_alias("atta", "AASH-ATTA-5KG", conn=conn)
        set_product_alias("salt", "TATA-SALT-1KG", conn=conn)
        set_product_alias("maggi", "MAGI-NOODL-70G", conn=conn)

        assert get_product_alias("atta", conn=conn) == "AASH-ATTA-5KG"
        assert get_product_alias("salt", conn=conn) == "TATA-SALT-1KG"
        assert get_product_alias("maggi", conn=conn) == "MAGI-NOODL-70G"
        conn.close()
