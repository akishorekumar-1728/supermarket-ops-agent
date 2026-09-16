"""
agent/fast_path.py
==================
Zero-latency fast path for standard supermarket operational queries.

Pattern matches common kirana shopkeeper requests and executes tools directly
in Python (< 5ms response time), bypassing LLM prompt evaluation latency completely.
Falls back to LLM for open-ended, complex, or conversational messages.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any

from tools.inventory import get_stock, get_low_stock, receive_stock
from tools.khata import get_credit_balance, record_credit_payment, create_credit
from tools.analytics import daily_summary
from tools.preferences import set_preference, get_preference, PREF_DEFAULT_PAYMENT_MODE
from tools.billing import (
    create_bill,
    add_bill_item,
    get_bill,
    remove_bill_item,
    update_bill_item,
    finalize_bill,
)
from documents.invoice import generate_invoice_pdf
from documents.invoice import generate_invoice_pdf
from documents.sales_deck import generate_sales_deck


def resolve_product_name(query: str, conn: sqlite3.Connection) -> str:
    """Resolve a user's short product name (e.g. 'maggi', 'atta', 'butter') to the exact catalog product name."""
    cur = conn.cursor()
    q = query.strip()
    # Check if a custom store preference alias exists
    pref_row = cur.execute("SELECT value FROM preferences WHERE key = LOWER(?)", (f"product_alias:{q.lower()}",)).fetchone()
    if pref_row and pref_row["value"]:
        q = pref_row["value"].strip()

    row = cur.execute("SELECT name FROM products WHERE LOWER(sku) = LOWER(?) OR LOWER(name) = LOWER(?)", (q, q)).fetchone()
    if row:
        return row["name"]
    row = cur.execute("SELECT name FROM products WHERE LOWER(name) LIKE LOWER(?) ORDER BY LENGTH(name) ASC LIMIT 1", (f"{q}%",)).fetchone()
    if row:
        return row["name"]
    row = cur.execute("SELECT name FROM products WHERE LOWER(name) LIKE LOWER(?) ORDER BY LENGTH(name) ASC LIMIT 1", (f"%{q}%",)).fetchone()
    if row:
        return row["name"]
    return q


def try_fast_path(
    user_message: str,
    conn: sqlite3.Connection,
) -> tuple[str, list[dict[str, Any]]] | None:
    """
    Attempt to fulfill query via high-speed deterministic pattern matching.

    Returns:
        tuple of (reply_text, executed_tools) if matched, or None to fall back to LLM.
    """
    msg = user_message.strip()
    msg_lower = msg.lower().rstrip("!.,?")

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Stock check: "how much <item> is left?" / "how much <item>?" / "stock of <item>"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(
        r"^(?:how much|how many|what is the stock of|stock of|check stock of)\s+(.+?)(?:\s+(?:is|are)?\s*(?:left|in stock|available|remaining))?$",
        msg_lower,
    )
    if m:
        item_query = m.group(1).strip()
        item_query = re.sub(r"^(?:packets? of|bottles? of|bags? of|boxes? of)\s+", "", item_query)
        if item_query and not any(k in item_query for k in ("we sell", "sold", "today", "yesterday", "bill")):
            try:
                exact_name = resolve_product_name(item_query, conn=conn)
                stock_data = get_stock(exact_name, conn=conn)
                qty = stock_data["quantity"]
                unit = stock_data.get("unit", "units")
                name = stock_data["name"]
                reorder = stock_data.get("reorder_level", 0)
                low_warn = f" ⚠️ *Low stock alert!* (At or below reorder level of {reorder} {unit})" if stock_data.get("is_low_stock") else ""
                reply = f"📦 Current stock for *{name}*: **{qty} {unit}**.{low_warn}"
                return reply, [{"tool": "get_stock", "arguments": {"product_query": exact_name}, "result": stock_data}]
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Low stock alert: "what's running out?" / "what is low on stock?"
    # ─────────────────────────────────────────────────────────────────────────
    if re.search(r"^(?:what(?:'s|\s+is)?\s+running\s+out|running\s+out|what is low on stock|low stock|low stock items|what needs to be ordered|items low on stock|what is low)\??$", msg_lower):
        try:
            items = get_low_stock(conn=conn)
            if not items:
                reply = "✅ All inventory items are currently above their reorder thresholds!"
            else:
                lines = [f"⚠️ *Low Stock Alert ({len(items)} items need reordering):*"]
                for it in items:
                    lines.append(f"• *{it['name']}*: **{it['quantity']} {it['unit']}** remaining (Reorder level: {it['reorder_level']} {it['unit']}, Shortfall: {it['shortfall']} {it['unit']})")
                reply = "\n".join(lines)
            return reply, [{"tool": "get_low_stock", "arguments": {}, "result": items}]
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Stock arrival: "50 packets of Maggi came in, cost ₹12, MRP ₹14"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(
        r"^(\d+(?:\.\d+)?)\s*(?:packets?|pkts?|bags?|kg|bottles?|units?|pieces?|pcs?)?\s*(?:of\s+)?(.+?)\s+(?:came in|received|arrived|stocked)(?:.*?cost\s*(?:price|is|rs\.?|₹)?\s*(\d+(?:\.\d+)?))?(?:.*?mrp\s*(?:is|rs\.?|₹)?\s*(\d+(?:\.\d+)?))?",
        msg_lower,
    )
    if m:
        qty = float(m.group(1))
        item_query = m.group(2).strip()
        cost_p = float(m.group(3)) if m.group(3) else None
        mrp = float(m.group(4)) if m.group(4) else None
        try:
            kwargs = {}
            if cost_p is not None:
                kwargs["cost_price"] = cost_p
            if mrp is not None:
                kwargs["mrp"] = mrp
            exact_name = resolve_product_name(item_query, conn=conn)
            res = receive_stock(exact_name, qty, conn=conn, **kwargs)
            cost_str = f" at cost ₹{cost_p:.2f}" if cost_p else ""
            mrp_str = f" (MRP ₹{mrp:.2f})" if mrp else ""
            reply = f"✅ Received **{qty} {res.get('unit','units')}** of *{res['name']}*{cost_str}{mrp_str}. New total stock: **{res['quantity']} {res.get('unit','units')}**."
            return reply, [{"tool": "receive_stock", "arguments": {"product_query": exact_name, "quantity": qty, **kwargs}, "result": res}]
        except Exception as exc:
            return f"⚠️ Could not record stock: {str(exc)}", []

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Khata balance: "Ramesh's balance?" / "Ramesh balance?" / "how much does Ramesh owe?"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^([a-zA-Z\s]+?)(?:'s|\s+)?\s+balance\??$", msg_lower)
    if not m:
        m = re.search(r"^(?:balance of|how much does)\s+([a-zA-Z\s]+?)(?:\s+owe|\s+balance)?\??$", msg_lower)
    if m:
        cust_name = m.group(1).strip()
        if cust_name not in ("today", "daily", "sales", "bank", "my"):
            try:
                bal = get_credit_balance(cust_name, conn=conn)
                reply = f"📖 Customer *{cust_name.title()}* outstanding balance: **₹{bal:.2f}**"
                return reply, [{"tool": "get_credit_balance", "arguments": {"customer_name": cust_name}, "result": bal}]
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Khata repayment: "Ramesh paid ₹300" / "Ramesh paid 300"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^([a-zA-Z\s]+?)\s+paid\s+(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)$", msg_lower)
    if m:
        cust_name = m.group(1).strip()
        amt = float(m.group(2))
        try:
            new_bal = record_credit_payment(cust_name, amt, conn=conn)
            reply = f"✅ Recorded payment of **₹{amt:.2f}** from *{cust_name.title()}*. Remaining balance: **₹{new_bal:.2f}**."
            return reply, [{"tool": "record_credit_payment", "arguments": {"customer_name": cust_name, "amount": amt}, "result": new_bal}]
        except Exception as exc:
            return f"⚠️ {str(exc)}", [{"tool": "record_credit_payment", "arguments": {"customer_name": cust_name, "amount": amt}, "result": {"error": str(exc)}}]

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Khata credit: "put ₹500 on Ramesh's credit" / "add 500 on Ramesh credit"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^(?:put|add|give)\s+(?:rs\.?|₹)?\s*(\d+(?:\.\d+)?)\s+(?:on|to)\s+([a-zA-Z\s]+?)(?:'s|\s+)?\s+(?:credit|khata|udhar)$", msg_lower)
    if m:
        amt = float(m.group(1))
        cust_name = m.group(2).strip()
        try:
            new_bal = create_credit(cust_name, amt, conn=conn)
            reply = f"📖 Added **₹{amt:.2f}** credit to *{cust_name.title()}*'s khata. New balance: **₹{new_bal:.2f}**."
            return reply, [{"tool": "create_credit", "arguments": {"customer_name": cust_name, "amount": amt}, "result": new_bal}]
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 7. PDF invoice request: "send me that bill as a PDF" / "bill pdf" / "give a pdf"
    # ─────────────────────────────────────────────────────────────────────────
    if "pdf" in msg_lower or (("invoice" in msg_lower or "bill" in msg_lower) and any(w in msg_lower for w in ("send", "give", "download", "get", "print", "share"))):
        cur = conn.cursor()
        row = cur.execute("SELECT id, invoice_number, status FROM bills WHERE status = 'finalized' ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            draft_row = cur.execute("SELECT id, invoice_number, status FROM bills WHERE status = 'draft' ORDER BY id DESC LIMIT 1").fetchone()
            if draft_row:
                idem_key = f"sale-{uuid.uuid4()}"
                finalize_bill(draft_row["id"], idempotency_key=idem_key, conn=conn)
                row = cur.execute("SELECT id, invoice_number, status FROM bills WHERE id = ?", (draft_row["id"],)).fetchone()

        if row:
            try:
                pdf_path = generate_invoice_pdf(row["id"], conn=conn)
                reply = f"🧾 Generated PDF Tax Invoice for bill **{row['invoice_number']}**."
                return reply, [{"tool": "generate_invoice_pdf", "arguments": {"bill_id": str(row["id"])}, "result": pdf_path}]
            except Exception as exc:
                return f"⚠️ Could not generate PDF: {str(exc)}", []
        else:
            return "⚠️ No bill found to generate invoice for. Please create a bill first.", []

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Sales deck: "make this week's sales analysis deck" / "sales deck"
    # ─────────────────────────────────────────────────────────────────────────
    if re.search(r"(?:sales\s+(?:analysis\s+)?deck|powerpoint\s+deck|presentation\s+deck|weekly\s+deck)", msg_lower):
        period = "month" if "month" in msg_lower else ("day" if "day" in msg_lower or "today" in msg_lower else "week")
        try:
            pptx_path = generate_sales_deck(period=period, conn=conn)
            reply = f"📊 Generated PowerPoint Sales Analysis Deck for period: **{period.upper()}**."
            return reply, [{"tool": "generate_sales_deck", "arguments": {"period": period}, "result": pptx_path}]
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Daily sales summary / Daily close: "today's sales?" / "close the day"
    # ─────────────────────────────────────────────────────────────────────────
    if re.search(r"^(?:today'?s?\s+sales(?:\s+report|\s+summary|\?)?|close\s+the\s+day|daily\s+close|day\s+close|daily\s+summary|daily\s+report|how much (?:did )?we sell today\??)$", msg_lower):
        try:
            summary = daily_summary(conn=conn)
            total = summary.get("total_sales", 0.0)
            bills_cnt = summary.get("total_bills", 0)
            gst = summary.get("total_gst", 0.0)
            cgst = summary.get("cgst_total", 0.0)
            sgst = summary.get("sgst_total", 0.0)
            top_prods = summary.get("top_products", [])
            modes_info = summary.get("payment_modes", {})
            modes_str = ", ".join([f"{k.upper()}: ₹{v.get('total_amount', 0):.2f}" for k, v in modes_info.items()]) if modes_info else "None yet"

            lines = [
                f"📊 *Daily Close & Sales Summary:*",
                f"• Total Revenue: **₹{total:.2f}** ({bills_cnt} bills)",
                f"• Total Tax Collected: **₹{gst:.2f}** (CGST: ₹{cgst:.2f}, SGST: ₹{sgst:.2f})",
                f"• Payment Breakdown: **{modes_str}**",
            ]
            if top_prods:
                lines.append("• Top Products:")
                for tp in top_prods[:3]:
                    lines.append(f"  - {tp['name']}: {tp['quantity_sold']} units (₹{tp['revenue']:.2f})")

            reply = "\n".join(lines)
            return reply, [{"tool": "daily_summary", "arguments": {}, "result": summary}]
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Preference: "always assume UPI unless I say cash" or "default atta = Aashirvaad 5kg"
    # ─────────────────────────────────────────────────────────────────────────
    if re.search(r"always\s+assume\s+(upi|cash|card|credit)", msg_lower):
        m = re.search(r"always\s+assume\s+(upi|cash|card|credit)", msg_lower)
        mode = m.group(1).lower()
        try:
            set_preference(PREF_DEFAULT_PAYMENT_MODE, mode, conn=conn)
            reply = f"⚙️ Saved preference! Default payment mode is now set to **{mode.upper()}** for all future bills."
            return reply, [{"tool": "set_preference", "arguments": {"key": PREF_DEFAULT_PAYMENT_MODE, "value": mode}, "result": mode}]
        except Exception:
            pass

    m_pref = re.search(r"^(?:default|alias)\s+(.+?)\s*=\s*(.+)$", msg_lower)
    if m_pref:
        alias_key = m_pref.group(1).strip().lower()
        alias_val = m_pref.group(2).strip()
        try:
            pref_k = f"product_alias:{alias_key}"
            set_preference(pref_k, alias_val, conn=conn)
            reply = f"⚙️ Saved preference! Default for *'{alias_key}'* is now set to *'{alias_val}'* across all chats."
            return reply, [{"tool": "set_preference", "arguments": {"key": pref_k, "value": alias_val}, "result": alias_val}]
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Finalize bill: "finalize" / "finalize bill" / "yes" / "done"
    # ─────────────────────────────────────────────────────────────────────────
    if re.search(r"^(?:finalize|finalize\s+bill|finalise|checkout|complete\s+sale|yes|yep|confirm|done|ok|okay|no|none|that's all)$", msg_lower):
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM bills WHERE status = 'draft' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            try:
                idem_key = f"sale-{uuid.uuid4()}"
                fin = finalize_bill(row["id"], idempotency_key=idem_key, conn=conn)
                pdf_path = generate_invoice_pdf(row["id"], conn=conn)
                reply = (
                    f"🧾 Bill finalized successfully!\n"
                    f"• Invoice No: **{fin['invoice_number']}**\n"
                    f"• Grand Total: **₹{fin['grand_total']:.2f}** (Payment: {fin['payment_mode'].upper()})\n"
                    f"• Items: {len(fin.get('items', []))}\n\n"
                    f"📄 Attached your official GST Tax Invoice PDF below."
                )
                return reply, [
                    {"tool": "finalize_bill", "arguments": {"bill_id": row["id"], "idempotency_key": idem_key}, "result": fin},
                    {"tool": "generate_invoice_pdf", "arguments": {"bill_id": str(row["id"])}, "result": pdf_path},
                ]
            except Exception as exc:
                reply = f"⚠️ Could not finalize bill: {str(exc)}"
                return reply, [{"tool": "finalize_bill", "arguments": {"bill_id": row["id"]}, "result": {"error": str(exc)}}]

    # ─────────────────────────────────────────────────────────────────────────
    # 13. Create multi-item bill: "make a bill: 2kg sugar, 4 Maggi, UPI"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^(?:make\s+(?:a\s+)?bill|create\s+(?:a\s+)?bill|bill)\s*:?\s*(.+)$", msg_lower)
    if m:
        body = m.group(1).strip()
        parts = [p.strip() for p in body.split(",") if p.strip()]
        if parts:
            try:
                payment_mode = None
                if parts[-1].lower() in ("upi", "cash", "card", "credit"):
                    payment_mode = parts.pop().lower()

                tools_called = []
                bill_id = create_bill(conn=conn, payment_mode=payment_mode)
                tools_called.append({"tool": "create_bill", "arguments": {"payment_mode": payment_mode}, "result": bill_id})

                added_lines = []
                for p in parts:
                    qty = 1.0
                    item_name = p
                    qm = re.match(r"^(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?|bags?|bottles?|units?|pieces?|pcs?|loaf|carton|tetra|can)?\s+(.+)$", p)
                    if qm:
                        qty = float(qm.group(1))
                        item_name = qm.group(2).strip()
                    else:
                        qm2 = re.match(r"^(.+?)\s+(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?|bags?|bottles?|units?|pieces?|pcs?|loaf|carton|tetra|can)?$", p)
                        if qm2:
                            item_name = qm2.group(1).strip()
                            qty = float(qm2.group(2))

                    exact_name = resolve_product_name(item_name, conn=conn)
                    item_res = add_bill_item(bill_id, exact_name, qty, conn=conn)
                    tools_called.append({"tool": "add_bill_item", "arguments": {"bill_id": bill_id, "product_query": exact_name, "quantity": qty}, "result": item_res})
                    added_lines.append(f"• *{item_res['name']}*: {qty} × ₹{item_res['unit_price']:.2f} = ₹{item_res['total']:.2f}")

                bill_summary = get_bill(bill_id, conn=conn)
                tools_called.append({"tool": "get_bill", "arguments": {"bill_id": bill_id}, "result": bill_summary})

                mode_display = (bill_summary.get("payment_mode") or "CASH").upper()
                reply = (
                    f"🧾 *Draft Bill #{bill_id} Created ({mode_display}):*\n"
                    + "\n".join(added_lines) + "\n\n"
                    f"• Subtotal: **₹{bill_summary['subtotal']:.2f}**\n"
                    f"• GST (CGST+SGST): **₹{bill_summary['gst_total']:.2f}**\n"
                    f"• Grand Total: **₹{bill_summary['grand_total']:.2f}**\n\n"
                    f"Say 'finalize' to complete the sale, or 'drop <item>' to edit."
                )
                return reply, tools_called
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # 14. Composite bill edit: "drop the butter, make it 6 Maggi"
    # ─────────────────────────────────────────────────────────────────────────
    if ("drop" in msg_lower or "remove" in msg_lower) and ("make it" in msg_lower or "change" in msg_lower or "update" in msg_lower):
        parts = [p.strip() for p in msg_lower.split(",") if p.strip()]
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM bills WHERE status = 'draft' ORDER BY id DESC LIMIT 1").fetchone()
        if row and len(parts) >= 2:
            tools_called = []
            action_notes = []
            final_tot = 0.0
            for pt in parts:
                m_drop = re.search(r"^(?:drop\s+the|remove\s+the|remove|drop)\s+(.+?)$", pt)
                if m_drop:
                    it_drop = resolve_product_name(m_drop.group(1).strip(), conn=conn)
                    try:
                        res = remove_bill_item(row["id"], it_drop, conn=conn)
                        final_tot = res.get("bill_totals", {}).get("grand_total", 0.0)
                        tools_called.append({"tool": "remove_bill_item", "arguments": {"bill_id": row["id"], "product_query": it_drop}, "result": res})
                        action_notes.append(f"• Removed *{it_drop}*")
                    except Exception:
                        pass
                m_qty = re.search(r"^(?:make\s+it|change\s+it\s+to|change|update)\s+(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?)?\s*(.+)$", pt)
                if not m_qty:
                    m_qty = re.search(r"^(?:make\s+it|change|update)\s+(.+?)\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?)?$", pt)
                    if m_qty:
                        it_qty = m_qty.group(1).strip()
                        n_qty = float(m_qty.group(2))
                else:
                    n_qty = float(m_qty.group(1))
                    it_qty = m_qty.group(2).strip()
                if m_qty:
                    it_qty_resolved = resolve_product_name(it_qty, conn=conn)
                    try:
                        res = update_bill_item(row["id"], it_qty_resolved, n_qty, conn=conn)
                        final_tot = res.get("bill_totals", {}).get("grand_total", 0.0)
                        tools_called.append({"tool": "update_bill_item", "arguments": {"bill_id": row["id"], "product_query": it_qty_resolved, "new_quantity": n_qty}, "result": res})
                        action_notes.append(f"• Updated *{it_qty_resolved}* quantity to **{n_qty}**")
                    except Exception:
                        pass
            if tools_called:
                reply = f"📝 Bill updated successfully:\n" + "\n".join(action_notes) + f"\n\n• New Grand Total: **₹{final_tot:.2f}**."
                return reply, tools_called

    # ─────────────────────────────────────────────────────────────────────────
    # 15. Single update quantity: "make it 6 Maggi" / "change Maggi to 6"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^(?:make\s+it|change\s+it\s+to|change|update)\s+(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?)?\s*(.+)$", msg_lower)
    if not m:
        m = re.search(r"^(?:make\s+it|change|update)\s+(.+?)\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*(?:kg|pkts?|packets?)?$", msg_lower)
        if m:
            item_query = m.group(1).strip()
            new_qty = float(m.group(2))
    else:
        new_qty = float(m.group(1))
        item_query = m.group(2).strip()

    if m:
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM bills WHERE status = 'draft' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            try:
                exact_name = resolve_product_name(item_query, conn=conn)
                updated_bill = update_bill_item(row["id"], exact_name, new_qty, conn=conn)
                tot = updated_bill.get("bill_totals", {}).get("grand_total", updated_bill.get("grand_total", 0.0))
                reply = f"✏️ Updated *{exact_name}* quantity to **{new_qty}**. New grand total: **₹{tot:.2f}**."
                return reply, [{"tool": "update_bill_item", "arguments": {"bill_id": row["id"], "product_query": exact_name, "new_quantity": new_qty}, "result": updated_bill}]
            except Exception as exc:
                return f"⚠️ Could not update item: {str(exc)}", []

    # ─────────────────────────────────────────────────────────────────────────
    # 16. Single drop item: "drop the <item>" / "remove <item>"
    # ─────────────────────────────────────────────────────────────────────────
    m = re.search(r"^(?:drop\s+the|remove\s+the|remove|drop)\s+(.+?)$", msg_lower)
    if m:
        item_query = m.group(1).strip()
        cur = conn.cursor()
        row = cur.execute("SELECT id FROM bills WHERE status = 'draft' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            try:
                exact_name = resolve_product_name(item_query, conn=conn)
                updated_bill = remove_bill_item(row["id"], exact_name, conn=conn)
                tot = updated_bill.get("bill_totals", {}).get("grand_total", updated_bill.get("grand_total", 0.0))
                reply = f"🗑️ Removed *{exact_name}* from current bill. New grand total: **₹{tot:.2f}**."
                return reply, [{"tool": "remove_bill_item", "arguments": {"bill_id": row["id"], "product_query": exact_name}, "result": updated_bill}]
            except Exception as exc:
                return f"⚠️ Could not remove item: {str(exc)}", []

    # ─────────────────────────────────────────────────────────────────────────
    # 17. New item inquiry: "new item: Amul Butter 100g, GST 12%, MRP ₹62"
    # ─────────────────────────────────────────────────────────────────────────
    m_new = re.search(r"^(?:new\s+item|new\s+product|add\s+item|add\s+product):\s*(.+)$", msg_lower)
    if m_new:
        body = m_new.group(1).strip()
        parts = [p.strip() for p in body.split(",") if p.strip()]
        prod_name = parts[0] if parts else ""
        cur = conn.cursor()
        exact_row = cur.execute("SELECT * FROM products WHERE LOWER(name) LIKE LOWER(?)", (f"%{prod_name}%",)).fetchone()
        if exact_row:
            reply = (
                f"🏷️ Product *'{exact_row['name']}'* is verified in your catalog:\n"
                f"• SKU: `{exact_row['sku']}`\n"
                f"• MRP: ₹{exact_row['mrp']:.2f} | Selling Price: ₹{exact_row['selling_price']:.2f} | Cost: ₹{exact_row['cost_price']:.2f}\n"
                f"• GST Rate: {exact_row['gst_rate']}% (HSN: `{exact_row['hsn_code']}`)\n"
                f"Ready for billing and stock intake!"
            )
            return reply, [{"tool": "get_product", "arguments": {"query": prod_name}, "result": dict(exact_row)}]

    return None
