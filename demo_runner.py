"""
demo_runner.py
==============
Runs the full mandatory demo scenario through the agent (no Telegram required).
Prints each step with the user message, tool calls, and agent reply.

Usage:
    python demo_runner.py

Environment variables:
    OLLAMA_HOST   (default: http://localhost:11434)
    OLLAMA_MODEL  (default: qwen3:4b)
    DEMO_DB       (default: ./demo_run.db  — re-created fresh each run)
"""
from __future__ import annotations

import os
import sys
import uuid
import shutil
from pathlib import Path

# UTF-8 stdout so ₹ doesn't crash on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.connection import get_and_init
from database.seed import seed
from agent.agent import chat_turn

DEMO_DB = Path(os.environ.get("DEMO_DB", ROOT / "demo_run.db"))
MODEL    = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
HOST     = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

SEP = "─" * 70


def step(number: int, label: str, msg: str, conn, history: list, *, new_session: bool = False) -> list:
    """Run one agent turn and print results. Returns updated history."""
    if new_session:
        history = []  # fresh conversation
        print(f"\n{'═'*70}")
        print(f"  ⚡ NEW SESSION (history cleared — simulating bot restart)")
        print(f"{'═'*70}")

    print(f"\n{SEP}")
    print(f"  Step {number}: {label}")
    print(f"  User ▶ {msg}")
    print(SEP)

    reply, history, tools = chat_turn(
        msg,
        conversation_history=history if history else None,
        conn=conn,
        model=MODEL,
        host=HOST,
        timeout=300,
    )

    if tools:
        print("  Tool calls:")
        for t in tools:
            args = {k: v for k, v in t.get("arguments", {}).items()}
            result_preview = str(t.get("result", ""))[:120]
            print(f"    • {t['tool']}({args}) → {result_preview}")

    print(f"\n  Agent ◀ {reply}")
    return history


def main():
    # ── Fresh DB ──────────────────────────────────────────────────────────
    if DEMO_DB.exists():
        DEMO_DB.unlink()
    conn = get_and_init(DEMO_DB)
    seed(conn, clear=True)
    print(f"Demo DB: {DEMO_DB}")
    print(f"Model:   {MODEL}")

    history: list = []

    # ── Steps 1-6: stock intake → billing → finalize ─────────────────────
    history = step(1,  "Stock intake — Maggi",
                   "50 packets of Maggi came in, cost ₹12, MRP ₹14",
                   conn, history)

    history = step(2,  "New product — Amul Butter",
                   "new item: Amul Butter 100g, GST 12%, MRP ₹62",
                   conn, history)

    history = step(3,  "Create multi-item bill",
                   "make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, 1 Amul butter, UPI",
                   conn, history)

    history = step(4,  "Drop the butter",
                   "drop the butter",
                   conn, history)

    history = step(5,  "Update Maggi qty",
                   "make it 6 Maggi",
                   conn, history)

    history = step(6,  "Finalize",
                   "finalize",
                   conn, history)

    # ── Step 7: oversell guard ────────────────────────────────────────────
    # Check remaining Maggi stock first
    remaining = conn.execute(
        "SELECT quantity FROM inventory i JOIN products p ON p.id=i.product_id "
        "WHERE LOWER(p.name) LIKE '%maggi%'"
    ).fetchone()
    remaining_qty = int(remaining[0]) if remaining else 0
    oversell_qty = remaining_qty + 5

    history = step(7,  f"Oversell guard (try {oversell_qty} Maggi, only {remaining_qty} left)",
                   f"make a bill and sell {oversell_qty} packets of Maggi, cash",
                   conn, history)

    # ── Steps 8-11: Khata ────────────────────────────────────────────────
    history = step(8,  "Khata — Ramesh credit ₹500",
                   "put ₹500 on Ramesh's credit",
                   conn, history)

    history = step(9,  "Khata — Ramesh balance check",
                   "Ramesh's balance?",
                   conn, history)

    history = step(10, "Khata — Ramesh payment ₹300",
                   "Ramesh paid ₹300",
                   conn, history)

    history = step(11, "Khata — Ramesh balance after payment",
                   "Ramesh's balance?",
                   conn, history)

    # ── Step 12: PDF invoice ─────────────────────────────────────────────
    history = step(12, "PDF invoice",
                   "send me that bill as a PDF",
                   conn, history)

    # Verify PDF actually exists
    pdf_files = list(Path(ROOT / "generated").glob("*.pdf"))
    if pdf_files:
        latest = max(pdf_files, key=lambda p: p.stat().st_mtime)
        size_kb = latest.stat().st_size // 1024
        print(f"\n  ✅ PDF file confirmed: {latest.name} ({size_kb} KB)")
    else:
        print("\n  ⚠️  No PDF found in generated/")

    # ── Step 13: PPTX sales deck ─────────────────────────────────────────
    history = step(13, "PPTX sales deck",
                   "make this week's sales analysis deck",
                   conn, history)

    pptx_files = list(Path(ROOT / "generated").glob("*.pptx"))
    if pptx_files:
        latest = max(pptx_files, key=lambda p: p.stat().st_mtime)
        size_kb = latest.stat().st_size // 1024
        print(f"\n  ✅ PPTX file confirmed: {latest.name} ({size_kb} KB)")
    else:
        print("\n  ⚠️  No PPTX found in generated/")

    # ── Step 14: Preference persistence across restart ───────────────────
    history = step(14, "Set UPI preference",
                   "always assume UPI unless I say cash",
                   conn, history)

    # Verify stored
    pref_row = conn.execute(
        "SELECT value FROM preferences WHERE key='default_payment_mode'"
    ).fetchone()
    stored = pref_row[0] if pref_row else None
    if stored == "upi":
        print(f"\n  ✅ Preference stored in DB: default_payment_mode = '{stored}'")
    else:
        print(f"\n  ⚠️  Preference not stored correctly: {stored!r}")

    # NEW SESSION — simulate bot restart
    history = step(14, "New bill in fresh session (should use UPI from preference)",
                   "make and finalize a new bill for 2 Maggi Noodles",
                   conn, [], new_session=True)   # empty history = fresh session

    # Check payment mode of last finalized bill
    last_bill = conn.execute(
        "SELECT payment_mode FROM bills WHERE status='finalized' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last_bill:
        mode = last_bill[0]
        icon = "✅" if mode == "upi" else "⚠️ "
        print(f"\n  {icon} Last finalized bill payment_mode = '{mode}' (expected 'upi')")

    conn.close()
    print(f"\n{'═'*70}")
    print("  Demo complete.")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
