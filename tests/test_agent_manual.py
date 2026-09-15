"""
tests/test_agent_manual.py
==========================
Integration tests for agent/agent.py using the real local Ollama instance.

Tests natural-language prompts:
1. "50 packets of Maggi came in, cost 12, MRP 15" -> checks receive_stock tool call & stock update
2. "how much sugar is left?" -> checks get_stock tool call
3. "new item: Parle Rusk 200g, SKU: PARL-RUSK-200G, unit: pkt, cost: 20, selling: 25, MRP: 30, GST 5%, HSN 1905, reorder 10" -> checks add_product
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

# Ensure utf-8 stdout encoding on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from tools.inventory import get_stock
from agent.agent import chat_turn, OLLAMA_MODEL


# Prefer llama3.2:3b for fast local evaluation, configurable via env
TEST_MODEL = os.environ.get("OLLAMA_TEST_MODEL", "llama3.2:3b")


@pytest.fixture()
def conn(tmp_path):
    """Fresh seeded database per test."""
    db_path = tmp_path / "agent_test.db"
    c = get_and_init(db_path)
    seed(c, clear=True)
    yield c
    c.close()


def test_agent_get_stock(conn):
    prompt = "how much sugar is left?"
    reply, history, tool_calls = chat_turn(prompt, conn=conn, model=TEST_MODEL, timeout=180)

    print(f"\n--- Prompt: {prompt} ---")
    print(f"Tool calls: {tool_calls}")
    print(f"Agent reply: {reply}")

    assert len(tool_calls) >= 1
    assert any(tc["tool"] in ("get_stock", "get_product") for tc in tool_calls)
    assert "35" in reply or "35.0" in reply or any("35" in str(tc["result"]) for tc in tool_calls)


def test_agent_receive_stock(conn):
    init_stock = get_stock("Maggi", conn)["quantity"]
    assert init_stock == 25.0

    prompt = "50 packets of Maggi came in, cost 12, MRP 15"
    reply, history, tool_calls = chat_turn(prompt, conn=conn, model=TEST_MODEL, timeout=180)

    print(f"\n--- Prompt: {prompt} ---")
    print(f"Tool calls: {tool_calls}")
    print(f"Agent reply: {reply}")

    assert len(tool_calls) >= 1
    assert any(tc["tool"] == "receive_stock" for tc in tool_calls)

    # Check that stock actually updated in SQLite to 25 + 50 = 75
    new_stock = get_stock("Maggi", conn)["quantity"]
    assert new_stock == 75.0


def test_agent_add_product(conn):
    prompt = (
        "Add a new product: Parle Rusk 200g with SKU PARL-RUSK-200G, unit pkt, "
        "cost price 20, selling price 25, MRP 30, GST 5%, HSN 1905, reorder level 10"
    )
    reply, history, tool_calls = chat_turn(prompt, conn=conn, model=TEST_MODEL, timeout=180)

    print(f"\n--- Prompt: {prompt} ---")
    print(f"Tool calls: {tool_calls}")
    print(f"Agent reply: {reply}")

    assert len(tool_calls) >= 1
    assert any(tc["tool"] == "add_product" for tc in tool_calls)

    # Verify product exists in database
    row = conn.execute("SELECT * FROM products WHERE sku = 'PARL-RUSK-200G'").fetchone()
    assert row is not None
    assert row["name"] == "Parle Rusk 200g"


if __name__ == "__main__":
    from database.connection import get_and_init
    c = get_and_init(":memory:")
    seed(c)
    print("Running test_agent_get_stock...")
    test_agent_get_stock(c)
    print("test_agent_get_stock PASSED!")

    print("\nRunning test_agent_receive_stock...")
    test_agent_receive_stock(c)
    print("test_agent_receive_stock PASSED!")

    print("\nRunning test_agent_add_product...")
    test_agent_add_product(c)
    print("test_agent_add_product PASSED!")
    print("\nALL AGENT MANUAL TESTS PASSED SUCCESSFULLY!")
