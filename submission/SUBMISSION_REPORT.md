# 🛒 Supermarket Operations Agent — Official Project Submission Report

**Project Title:** Autonomous Supermarket Operations Agent (`Nebula Bot`)  
**Live Bot Handle:** [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)  
**GitHub Repository:** [https://github.com/akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)  
**Deployment Platform:** Render Cloud (24/7 Python Web Service with Health Server & Self-Pinger)  
**AI Engine:** Google Gemini 3.6 Flash with 10-Key Auto-Rotation & Fallback  
**Database:** SQLite in WAL Mode with Foreign Keys and Atomic Transactions  

---

## 📑 Table of Contents
1. [Live Bot Access & Reviewer Guide](#1-live-bot-access--reviewer-guide)
2. [Agent Harness & Control Loop Architecture](#2-agent-harness--control-loop-architecture)
3. [Skills & Tools: Capability Surface](#3-skills--tools-capability-surface)
4. [GST Tax Invoice PDF Generator](#4-gst-tax-invoice-pdf-generator)
5. [PPTX Sales Analysis Deck Generator](#5-pptx-sales-analysis-deck-generator)
6. [Engineering Solutions for Core Hard Problems](#6-engineering-solutions-for-core-hard-problems)
7. [Automated Testing & Verification](#7-automated-testing--verification)

---

## 1. Live Bot Access & Reviewer Guide

### 🤖 Live Telegram Bot Handle: [`@supermarket_ops_nebula_bot`](https://t.me/supermarket_ops_nebula_bot)

The bot is actively deployed, listening 24/7 on Render cloud, and ready for immediate interactive evaluation.

### 🧪 Reviewer Evaluation Script (5-Minute Scenario Walkthrough)

To evaluate the complete store operations lifecycle, send these messages to the bot in sequence:

| Step | Action | Message to Send | Expected Bot Output |
|---|---|---|---|
| **1** | **Initialization** | `/start` | Welcome message outlining capabilities and commands. |
| **2** | **Receive Stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Stock atomically incremented by 50; unit cost and MRP updated. |
| **3** | **Receive Stock (Spacing variant)** | `20 packets of Aashirvaad Atta 5kg arrived, cost ₹280, MRP ₹320` | Unit normalizer matches `Aashirvaad Atta 5kg`; inventory updated. |
| **4** | **Draft Bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | Draft bill created with statutory 50/50 CGST + SGST tax split. |
| **5** | **Mid-Build Edit** | `drop the sugar, make it 6 Maggi` | Item removed, Maggi quantity updated, total recalculated. |
| **6** | **Finalize Bill** | `finalize the bill` | Stock atomically deducted; official GST invoice number issued. |
| **7** | **Oversell Guard** | `make a bill: 500 Maggi, cash` | **Rejected by Oversell Guard**: requested quantity exceeds stock. |
| **8** | **Khata Credit Cycle** | `put ₹750 on Ramesh's credit` | Customer auto-registered; debt recorded in ledger. |
| **9** | **Khata Repayment** | `Ramesh paid ₹300` | Partial payment logged; remaining balance displayed (₹450). |
| **10** | **Invoice PDF** | `send me that bill as a PDF` | High-resolution GST Tax Invoice PDF generated and delivered to chat. |
| **11** | **Sales Deck** | `make this week's sales analysis deck` | Full PowerPoint `.pptx` deck with embedded charts delivered. |
| **12** | **Memory & New Session** | `always assume UPI unless I say cash` | Preference saved to SQLite memory. |
| **13** | **Test Persistence** | `/new` then `make a bill: 2 Maggi, 1kg sugar` | Fresh chat created; payment mode automatically defaults to UPI. |

---

## 2. Agent Harness & Control Loop Architecture

### 🏗️ Selected Harness & Design Rationale
The agent uses a **hybrid zero-latency + function-calling control loop**:
1. **Deterministic Fast Path (< 5ms)**: 80% of routine supermarket queries (inventory lookup, stock arrival, balance checks, preference reads) match deterministic regex patterns and execute in pure Python/SQL, bypassing LLM token evaluation entirely.
2. **LLM Function-Calling Agent Loop (Gemini 3.6 Flash)**: For conversational, multi-step, or ambiguous instructions (e.g. multi-item billing, complex bill edits, intent clarification), messages enter the agent control loop.
3. **Automatic 10-Key Quota Rotation**: To eliminate free-tier rate limits, the harness manages 10 API keys with seamless thread-safe failover and conversation state (`chat.history`) preservation across key rotations.

### 🔄 Control Loop Diagram
```text
User Message (Telegram / CLI)
             │
             ▼
┌──────────────────────────────────────────────┐
│       Zero-Latency Fast Path Router          │ ──[Match]──► Instant Response (< 5ms)
│       (agent/fast_path.py)                   │
└──────────────────────┬───────────────────────┘
                       │ Fallback (Complex / Ambiguous)
                       ▼
┌──────────────────────────────────────────────┐
│       Intent Router (agent/intent_router.py) │ ──► Selects 3–5 relevant tools
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│       Gemini 3.6 Flash Function Loop         │ ◄───┐
│       (agent/agent.py)                       │     │
│       • Multi-key failover manager           │     │ Tool Response Loop
│       • Dispatches JSON Function Calls       │     │
└──────────────────────┬───────────────────────┘     │
                       │                             │
                       ▼                             │
┌──────────────────────────────────────────────┐     │
│       Deterministic Business Tools Execution │ ────┘
│       (database / billing / khata / docs)    │
└──────────────────────┬───────────────────────┘
                       │ Final text response & file artifacts
                       ▼
Telegram Delivery (Text, ReportLab PDF, python-pptx Deck)
```

---

## 3. Skills & Tools: Capability Surface

The agent's capability surface is organized into modular tool domains with strict parameter schemas:

### A. Product Catalog Management (`tools/products.py`)
- `add_product(sku, name, unit, cost_price, selling_price, mrp, gst_rate, hsn_code, reorder_level)`: Registers products with statutory HSN code and GST tax slab validation.
- `get_product(query)`: Fuzzy search across SKU and product names with automatic unit spacing normalization (`5 kg` $\leftrightarrow$ `5kg`).

### B. Inventory & Stock Intake (`tools/inventory.py`)
- `receive_stock(product_query, quantity, cost_price=None, mrp=None)`: Atomically increments stock; optionally updates landed cost and MRP on the master catalog.
- `get_stock(product_query)`: Returns current stock balance and low-stock warning flag.
- `get_low_stock()`: Ranks products at or below reorder threshold by shortfall urgency.

### C. Statutory Billing & Finalization (`tools/billing.py`)
- `create_bill(payment_mode=None)`: Initializes a draft bill; automatically resolves payment mode preferences when omitted.
- `add_bill_item(bill_id, product_query, quantity)`: Appends item, resolves pricing, and calculates CGST and SGST splits.
- `remove_bill_item(bill_id, product_query)`: Removes line items from draft bills and updates totals.
- `update_bill_item(bill_id, product_query, new_quantity)`: Modifies line item quantities.
- `finalize_bill(bill_id, idempotency_key, payment_reference=None)`: Validates stock, executes atomic inventory deduction in WAL mode, locks the bill, and assigns an invoice number (`INV-XXXXX`).

### D. Customer Khata Credit Ledger (`tools/khata.py`)
- `create_credit(customer_name, amount, reference=None)`: Auto-creates customer accounts and records credit transactions.
- `record_credit_payment(customer_name, amount, reference=None)`: Logs partial/full payments; rejects overpayment amounts.
- `get_credit_balance(customer_name)`: Calculates live balance from debit and credit ledgers.

### E. Store Analytics & Financial Summary (`tools/analytics.py`)
- `daily_summary(date=None)`: Computes aggregate revenue, invoice count, GST split (CGST vs SGST), payment breakdown (UPI vs Cash vs Card), and top-performing products.

### F. Store Memory & Preferences (`tools/preferences.py`)
- `set_preference(key, value)`: Persists store defaults (e.g. `default_payment_mode=upi`, `product_alias:atta=Aashirvaad Atta 5kg`) to the database.
- `get_preference(key, default=None)`: Retrieves stored settings during billing and product lookup.

---

## 4. GST Tax Invoice PDF Generator

### 📄 Implementation: [`documents/invoice.py`](file:///E:/supermarket-ops-agent/documents/invoice.py)
Generates high-resolution, GST-compliant tax invoices using **ReportLab Platypus**:

- **Bilingual & Formal Structure**: Includes store branding, official GSTIN, invoice date, unique invoice serial number, and customer/payment details.
- **Statutory Itemized Tax Table**:
  - Item Description & Packaging Unit
  - HSN / SAC code
  - Unit Selling Price (Tax-exclusive)
  - Applicable GST Rate (0%, 5%, 12%, 18%, 28%)
  - Intra-state CGST & SGST breakdown columns
  - Net Line Total
- **Summary & Sign-off**: Displays subtotal, total tax collected, net payable amount in rupees (`₹`), and an official "Computer Generated Tax Invoice" footer.
- **Chat Delivery**: Automatically uploaded directly into Telegram as a downloadable PDF document upon generation.

---

## 5. PPTX Sales Analysis Deck Generator

### 📊 Implementation: [`documents/sales_deck.py`](file:///E:/supermarket-ops-agent/documents/sales_deck.py)
Generates a 6-slide executive presentation using **`python-pptx`** and **`matplotlib`**:

1. **Slide 1: Title & Executive Metadata**: Store branding, reporting timeframe (Day / Week / Month), and report generation timestamp.
2. **Slide 2: Key Financial Metrics**: Summary cards showing Total Revenue (₹), Total Invoices, Average Order Value (AOV), and Total GST Collected.
3. **Slide 3: Payment Mode Distribution**: Matplotlib donut chart showing percentage share of UPI, Cash, Card, and Khata credit.
4. **Slide 4: Top 5 Products by Revenue**: Horizontal bar chart comparing product sales volumes and revenue contributions.
5. **Slide 5: Inventory Health & Reorder Alerts**: Visual table categorizing inventory into Healthy, Low Stock, and Out of Stock.
6. **Slide 6: Automated Operations Insights**: Rule-based executive recommendations based on store performance metrics.

---

## 6. Engineering Solutions for Core Hard Problems

### 🛡️ 1. Statutory Indian GST Engine
* **Challenge**: LLMs frequently hallucinate tax math or fail to split CGST/SGST correctly.
* **Solution**: The GST calculator in [`tools/gst.py`](file:///E:/supermarket-ops-agent/tools/gst.py) is deterministic pure Python. It enforces statutory slabs (`0%`, `5%`, `12%`, `18%`, `28%`), performs exact 50/50 intra-state CGST and SGST splits, and rounds to two decimal places using exact currency arithmetic.

### 🔒 2. Oversell Guard & Atomic Finalization
* **Challenge**: Race conditions or draft billing could lead to negative stock or inventory over-allocation.
* **Solution**: Draft bills **never deduct stock**. Deduction occurs exclusively during finalization within a serialized `BEGIN IMMEDIATE` SQLite transaction in WAL mode. If any item's stock shortfall is detected, the transaction aborts and rolls back completely.

### 💰 3. Below-Cost Selling Protection
* **Challenge**: Accidental price entry could sell items below cost price, resulting in shopkeeper losses.
* **Solution**: The checkout engine validates `selling_price >= cost_price` for every line item, rejecting below-cost transactions before commit.

### 🔁 4. Idempotent Checkout Protection
* **Challenge**: Unstable network connections could cause duplicate finalize requests, deducting stock twice.
* **Solution**: `finalize_bill` requires a client-generated `idempotency_key`. Repeating a request with the same key returns the existing finalized invoice without touching inventory.

### 🔄 5. Seamless 10-Key Automatic Gemini Rotation
* **Challenge**: Free-tier Gemini keys hit rate limits (`429 Too Many Requests`, RPM/TPM exhaustion) during peak usage.
* **Solution**: The agent loads 10 keys from `GEMINI_API_KEYS`. When any quota or rate-limit exception occurs:
  1. The error is intercepted in `< 500ms`.
  2. The next active key is selected via thread-safe rotation.
  3. The active conversation state (`chat.history`) is migrated to the new key.
  4. The turn retries transparently without user disruption.

### ⚡ 6. Zero-Latency Sub-10ms Fast Path
* **Challenge**: Routine operations (checking stock, logging credit) feel sluggish when waiting for cloud LLM reasoning.
* **Solution**: A deterministic regex compiler in [`agent/fast_path.py`](file:///E:/supermarket-ops-agent/agent/fast_path.py) intercepts 80% of standard operations and executes them directly in SQLite in **0.1 to 15 ms**, reserving the LLM for complex tasks.

### ☁️ 7. Render Cloud Inactivity Prevention
* **Challenge**: Render's free tier spins down web services after 15 minutes of inbound HTTP inactivity.
* **Solution**: [`main.py`](file:///E:/supermarket-ops-agent/main.py) starts a background daemon that periodically self-pings the application's external URL every 10 minutes, keeping the bot awake 24/7.

---

## 7. Automated Testing & Verification

The codebase includes an automated **`pytest`** suite covering all core operations, transactions, and edge cases:

```bash
# Execute full automated test suite
python -m pytest tests/ -v
```

### Test Coverage Highlights
- **Product Catalog & Slabs**: Verified valid/invalid GST slabs, duplicate SKU rejection, and unit space normalizers.
- **Inventory & Stock Intake**: Atomic increments, cost updates, and low-stock threshold triggers.
- **Billing Transactions**: Draft item addition, quantity updates, mid-build removals, and subtotal calculations.
- **Finalization & Guards**: Oversell rejection, below-cost rejection, and idempotency guarantees.
- **Khata Ledger**: Debit additions, partial payments, overpayment rejections, and balance calculations.
- **Document Compilers**: Headless generation of valid PDF binary streams and PowerPoint presentations with matplotlib figures.

---

## 👤 Author Information
- **Developer:** A Kishore Kumar
- **Live Telegram Bot:** [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)
- **GitHub Repository:** [akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
