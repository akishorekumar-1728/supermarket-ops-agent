# Supermarket Ops Agent

An autonomous, local-first operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram or CLI, the agent handles product cataloging, inventory stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation. All state is persisted locally in SQLite with strict transactional consistency, oversell prevention, below-cost protections, and idempotency guarantees.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![Local LLM](https://img.shields.io/badge/Ollama-Local--First-orange?logo=ollama)](https://ollama.com)

---

## 🌟 What I Did in This Project (Summary of Accomplishments)

This project was built from scratch as an end-to-end, production-grade AI operations agent designed specifically for Indian retail and kirana environments. Here is everything designed, developed, and delivered:

### 1. 100% Zero-Budget Local Agent Architecture
- Built entirely on **local Ollama** (`llama3.2:3b` / `qwen3:4b`), running 100% on-device without a single paid API call (no OpenAI, no Claude API).
- Developed a custom cyclic **Observe → Reason → Act → Observe Result → Re-Reason → Respond** agent control loop using standard Python (`urllib.request`) and SQLite.
- Complete privacy and offline resilience: all store catalogs, sales records, customer balances, and tax details remain strictly on the local machine.

### 2. Sub-10ms Latency Optimization Engine
- **Root-Cause Discovery**: Diagnosed that sending 19 tool schemas into the LLM on every turn required evaluating 2,667 tokens, causing 60-second latencies on CPU.
- **Zero-Latency Fast Path (`agent/fast_path.py`)**: Designed an instant deterministic execution engine for stock arrivals, inventory lookups, billing, item edits, finalization, khata ledgers, PDF invoice delivery, and preference persistence. Common queries now execute in **1 to 50 milliseconds** (< 0.05s).
- **Smart Product Resolution (`resolve_product_name`)**: Implemented fuzzy mapping that connects informal shorthand terms (e.g. `"maggi"` → `Maggi Noodles 70g`, `"atta"` → `Aashirvaad Atta 5kg`, `"sugar"` → `Sugar (loose)`) directly to catalog items, eliminating ambiguous query errors.
- **Intent-Based Tool Router (`agent/intent_router.py`)**: For open-ended natural language requiring LLM reasoning, a keyword-based intent router trims schemas from 19 tools down to the 3–5 relevant tools (~300 tokens), dropping LLM prompt evaluation time from 60s to 1.5–2.5s.
- **Ollama Engine Tuning**: Configured 16-thread CPU parallelism, compact system prompts (reduced from 850 to 40 tokens), greedy decoding (`temperature=0`), and `keep_alive="10m"` to keep models hot in RAM.

### 3. Live Telegram Bot Integration (`main.py`)
- Live Telegram bot accessible at **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)** using `python-telegram-bot 22.8`.
- Supports `/start`, `/help`, `/reset`, conversational memory across turns, and interactive chat action status updates.
- **Direct File Delivery**: Generated GST Tax Invoice PDFs and PowerPoint Sales Analysis presentations are automatically transmitted as native downloadable documents directly within Telegram.
- Automatic PDF invoice generation whenever a sale is finalized.

### 4. Deterministic GST & Billing Engine
- **Strict Indian GST Compliance (`tools/gst.py`)**: Arithmetic is handled 100% in deterministic Python (never hallucinated by the LLM). Validates against official slabs (0%, 5%, 12%, 18%, 28%) and calculates accurate 50/50 intra-state splits between Central GST (CGST) and State GST (SGST).
- **Interactive Multi-Item Billing (`tools/billing.py`)**: Supports drafting bills, adding items, removing items (`"drop the atta"`), updating quantities (`"make it 6 Maggi"`), and verifying totals before committing sales.

### 5. Hardened Transaction Safeguards
- **Atomic Finalization (`tools/billing.py`)**: Uses `BEGIN IMMEDIATE` exclusive SQLite transactions in WAL mode.
- **Oversell Guard**: Inspects live inventory before decrementing stock. If requested quantity exceeds stock on hand, the transaction rolls back cleanly with an `InsufficientStockError`, keeping stock safe.
- **Below-Cost Protection**: Compares selling price against landed cost price (`unit_price >= cost_price`). Rejects below-cost loss sales with `BelowCostSaleError`.
- **Idempotency Guard**: Enforces unique `idempotency_key` constraints on all finalized bills, ensuring network retries never double-deduct inventory.

### 6. Customer Khata Credit Ledger (`tools/khata.py`)
- Complete double-entry digital ledger for store credit (*udhar*).
- Auto-provisions new customer records on first credit (`"put ₹500 on Ramesh credit"`).
- Guards against overpayment (`amount <= balance`) and maintains a full transactional audit history with running balances.

### 7. Persistent Memory & Shop Preferences (`tools/preferences.py`)
- Persistent key-value preference engine backed by SQLite.
- Preferences (e.g. `default_payment_mode=upi`, `store_name`, `gstin`, custom product aliases) survive application restarts, bot redeployments, and cleared chat histories.

### 8. Document Generation Pipelines
- **GST Invoice PDF (`documents/invoice.py`)**: Generates print-ready, professional PDF tax invoices using **ReportLab** with sequential numbering (`INV-00001`), store details, HSN codes, and itemized tax breakdowns.
- **PowerPoint Sales Decks (`documents/sales_deck.py`)**: Generates multi-slide executive sales reports using **python-pptx**, **pandas**, and **matplotlib**, featuring embedded pie charts (payment modes), bar charts (top selling items), stock health warnings, and business analytics.

### 9. Realistic Supermarket Dataset (`data/supermarket_catalog.json`)
- Built and imported a realistic dataset of **51 products** across 8 core Indian supermarket categories (Staples, Dairy, Oils, Spices, Snacks, Beverages, Personal Care, and Cleaning).
- Pre-seeded 5 customer khata accounts with realistic credit balances and configured store GST metadata.

### 10. Comprehensive Verification & Testing
- Developed 180+ test assertions across `tests/`, verifying:
  - Catalog lookup, additions, and validation.
  - Inventory arrivals, updates, and low-stock alerts.
  - GST slabs, rounding, and CGST/SGST splits.
  - Oversell guards and below-cost transaction rollbacks.
  - Idempotent finalization and concurrency locks.
  - Khata credit issuance, payments, and overpayment rejections.
  - Daily sales summaries and preference persistence across bot restarts.
  - Automated PDF and PPTX document creation.
  - Full 13-step end-to-end operational scenario (`tests/test_demo_scenario.py`).

---

## 🏗️ System Architecture

```text
               User (Shopkeeper via Telegram / CLI)
                                │
                                ▼
         ┌─────────────────────────────────────────────┐
         │     Telegram Bot (main.py) / CLI Runner     │
         └──────────────────────┬──────────────────────┘
                                │ User query
                                ▼
         ┌─────────────────────────────────────────────┐
         │     Zero-Latency Fast Path Engine           │
         │             (agent/fast_path.py)            │
         └──────────────────────┬──────────────────────┘
                   │ Matches?            │ Fallback (Complex Query)
          YES (< 5ms)                    ▼
                   │            ┌─────────────────────────────────────────┐
                   │            │ Intent-Based Router (intent_router.py)  │
                   │            └────────────────────┬────────────────────┘
                   │                                 │ Minimal schemas (~300 tokens)
                   │                                 ▼
                   │            ┌─────────────────────────────────────────┐
                   │            │ Ollama Agent Loop (agent/agent.py)      │
                   │            │ (16 CPU cores, compact prompt, keep hot)│
                   │            └────────────────────┬────────────────────┘
                   │                                 │ Tool call
                   ▼                                 ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                              Execution Layer                                │
  │  • SQLite Database (WAL mode, foreign keys, atomic transactions)            │
  │  • Product Catalog & Stock Intake (tools/products.py, tools/inventory.py)   │
  │  • Deterministic GST & Billing Engine (tools/gst.py, tools/billing.py)      │
  │  • Customer Khata Credit Ledger (tools/khata.py)                            │
  │  • Persistent Preferences Store (tools/preferences.py)                      │
  │  • Document Engines (documents/invoice.py, documents/sales_deck.py)         │
  └──────────────────────────────────────┬──────────────────────────────────────┘
                                         │ Result / Generated Document
                                         ▼
         ┌──────────────────────────────────────────────────────────────────────┐
         │                   Telegram Delivery Handler                          │
         │         • Markdown formatted text response                           │
         │         • Native PDF document upload (GST Tax Invoice)               │
         │         • Native PPTX presentation upload (Sales Deck)               │
         └──────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Performance Benchmarks

All operations tested live via `chat_turn` against the active SQLite database on an Intel 16-thread CPU:

| Operation | Query | Executed Tools | Response Latency |
|---|---|---|---|
| Stock Intake | `50 packets of Maggi came in, cost 12, MRP 14` | `receive_stock` | **15.9 ms** (0.015s) |
| Multi-Item Bill | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | `create_bill`, `add_bill_item` × 3, `get_bill` | **6.6 ms** (0.006s) |
| Edit Bill (Drop) | `drop the atta` | `remove_bill_item` | **2.0 ms** (0.002s) |
| Edit Bill (Qty) | `make it 6 Maggi` | `update_bill_item` | **0.7 ms** (0.0007s) |
| Finalize Sale | `finalize` / `yes` | `finalize_bill` + `generate_invoice_pdf` | **0.9 ms** (0.0009s) |
| Khata Credit | `put 500 on Ramesh credit` | `create_credit` | **0.7 ms** (0.0007s) |
| Khata Balance | `Ramesh balance?` | `get_credit_balance` | **0.1 ms** (0.0001s) |
| Khata Repayment | `Ramesh paid 300` | `record_credit_payment` | **0.3 ms** (0.0003s) |
| PDF Invoice | `send me that bill as a PDF` / `give a pdf` | `generate_invoice_pdf` | **44.5 ms** (0.044s) |
| Preferences | `always assume UPI unless I say cash` | `set_preference` | **0.4 ms** (0.0004s) |

**Total execution time for all 11 operations combined: 0.072 seconds (Average: 6.6 milliseconds per step).**

---

## 🛠️ Tool & Skill Surface

Every tool is registered in `agent/tools_registry.py` with strict schema validation:

| Tool | Purpose | Key Parameters | Safeguards |
|---|---|---|---|
| `add_product` | Adds new SKU to catalog | `sku`, `name`, `unit`, `cost_price`, `selling_price`, `mrp`, `gst_rate`, `hsn_code`, `reorder_level` | Validates GST slab, checks `mrp >= selling_price >= cost_price`. |
| `get_product` | Catalog search | `query` (SKU or partial name) | Returns list of matches; prevents arbitrary guessing. |
| `receive_stock` | Logs incoming stock | `product_query`, `quantity`, `cost_price`, `mrp` | Atomically increments quantity; updates batch prices. |
| `get_stock` | Inventory stock check | `product_query` | Returns quantity, reorder level, and `is_low_stock` flag. |
| `get_low_stock` | Replenishment alerts | None | Identifies products where `quantity <= reorder_level`, sorted by shortfall. |
| `create_bill` | Opens draft bill | `payment_mode` (optional) | Binds user-defined `default_payment_mode` preference automatically. |
| `add_bill_item` | Appends item to bill | `bill_id`, `product_query`, `quantity` | Calculates line-item GST; does not deduct stock in draft. |
| `remove_bill_item`| Removes item from bill | `bill_id`, `product_query` | Recalculates subtotal and tax totals dynamically. |
| `update_bill_item`| Changes item quantity | `bill_id`, `product_query`, `new_quantity` | Recalculates line-item and overall bill totals. |
| `get_bill` | Bill inspection | `bill_id` | Returns complete invoice breakdown with CGST/SGST itemization. |
| `finalize_bill` | Commits sale & deducts stock | `bill_id`, `idempotency_key` | **Oversell protection**, **below-cost guard**, and **idempotency lock**. |
| `create_credit` | Issues customer credit | `customer_name`, `amount`, `reference` | Auto-registers new customers; updates running balance. |
| `record_credit_payment` | Logs debt repayment | `customer_name`, `amount`, `reference` | **Overpayment guard** (`amount <= balance`). |
| `get_credit_balance` | Queries customer balance | `customer_name` | Returns net outstanding debt. |
| `daily_summary` | Daily sales analytics | `date` (defaults to today) | Aggregates revenue, tax collections, top products, payment modes. |
| `set_preference`| Saves shop settings | `key`, `value` | Persists configuration across bot restarts. |
| `get_preference`| Reads shop settings | `key`, `default` | Retrieves stored configuration keys. |
| `generate_invoice_pdf` | Generates PDF invoice | `bill_id` | Compiles GST tax invoice PDF with ReportLab. |
| `generate_sales_deck` | Builds PPTX sales deck | `period` ('day', 'week', 'month', 'all') | Builds PowerPoint presentation with embedded Matplotlib charts. |

---

## 🚀 Quickstart & Setup

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- [Ollama](https://ollama.com/) running locally

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/akishorekumar-1728/supermarket-ops-agent.git
   cd supermarket-ops-agent
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Pull Ollama model:**
   ```bash
   ollama pull llama3.2:3b
   ```

5. **Configure environment (`.env`):**
   ```env
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=llama3.2:3b
   TELEGRAM_BOT_TOKEN=8732475243:AAE6g9ol_CcprHdFcADoZjtBTeX5B0iPFPg
   ```

6. **Seed the database (51 products, 5 customers):**
   ```bash
   python database/import_dataset.py
   ```

7. **Run the automated test suite:**
   ```bash
   python -m pytest tests/ -v
   ```

8. **Start the Telegram Bot:**
   ```bash
   python main.py
   ```

---

## 🧪 Verified Test Suite

The test suite contains 180+ automated unit and integration tests:

```bash
python -m pytest tests/ -v
```

- `tests/test_database.py` — Schema creation, foreign keys, WAL mode, seed data.
- `tests/test_products.py` — SKU uniqueness, mandatory fields, price validation.
- `tests/test_inventory.py` — Stock reception, atomic updates, low stock calculations.
- `tests/test_gst.py` — GST slab validation, CGST/SGST 50/50 splits, rounding accuracy.
- `tests/test_billing.py` — Draft bill workflow, tax totals recalculation, item removal.
- `tests/test_finalize.py` — Atomic transactions, oversell guards, below-cost protection, idempotency locks.
- `tests/test_khata.py` — Auto-provisioning customers, credit entries, repayment overpayment guards.
- `tests/test_analytics.py` — Revenue aggregation, tax summaries, top product sorting.
- `tests/test_preferences.py` — Persistent memory across sessions and restarts.
- `tests/test_invoice.py` — PDF generation, layout validation, table generation.
- `tests/test_sales_deck.py` — PPTX deck compilation, chart generation, data filtering.
- `tests/test_demo_scenario.py` — Complete 13-step mandatory operational scenario.
- `tests/test_preferences_billing.py` — End-to-end agent preference persistence across restarts.

---

## 👥 Author

- **GitHub Repository**: [https://github.com/akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Telegram Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)