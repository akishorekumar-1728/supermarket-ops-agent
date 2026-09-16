# Supermarket Ops Agent

An autonomous, local-first operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram or CLI, the agent handles product cataloging, inventory stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation. All state is persisted locally in SQLite with strict transactional consistency, oversell prevention, below-cost protections, and idempotency guarantees.

---

## 1. Zero-Budget Local Agent Harness

This project intentionally uses **local Ollama** running open-weights models (`qwen3:8b`, `qwen3:4b`, or `llama3.2:3b`) as its core reasoning and tool-calling harness.

- **Zero API Costs:** Built as a 100% zero-budget local-first equivalent to commercial proprietary agent frameworks (such as Claude Agent SDK, Deep Agent, or Vercel AI SDK).
- **Zero Proprietary Cloud APIs:** No paid Claude API or OpenAI API tokens were used anywhere in development or runtime.
- **Privacy & Offline Resilience:** Kirana store records, prices, invoices, and customer credit ledgers remain strictly on-device without cloud leakage.
- **Direct Control Loop:** Built directly on Python's standard library (`urllib.request`) and SQLite without heavy third-party framework abstraction.

---

## 2. System Architecture

```text
               User (Shopkeeper via Telegram / CLI)
                               │
                               ▼
        ┌─────────────────────────────────────────────┐
        │        Telegram Bot / CLI Interface         │
        └──────────────────────┬──────────────────────┘
                               │ User message + history
                               ▼
        ┌─────────────────────────────────────────────┐
        │       Agent Control Loop (agent/agent.py)   │
        └──────────────────────┬──────────────────────┘
                               │ /api/chat (Messages + Tool Schemas)
                               ▼
        ┌─────────────────────────────────────────────┐
        │         Local Ollama Model Server           │
        │       (qwen3:4b / qwen3:8b / llama3.2:3b)   │
        └──────────────────────┬──────────────────────┘
                               │ Tool call requests (name + arguments)
                               ▼
        ┌─────────────────────────────────────────────┐
        │    Tool Registry (agent/tools_registry.py)  │
        └──────────────────────┬──────────────────────┘
                               │ Dispatches verified calls
                               ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │                       Execution Layer                            │
 │  • SQLite Database (WAL mode, FKs, transactions)                 │
 │  • Product Catalog & Stock Intake (tools/products, inventory)    │
 │  • Billing & GST Engine (tools/gst.py, tools/billing.py)         │
 │  • Customer Khata Credit Ledger (tools/khata.py)                 │
 │  • Persistent Preferences Store (tools/preferences.py)           │
 │  • Document Engines (documents/invoice.py, sales_deck.py)        │
 └─────────────────────────────┬────────────────────────────────────┘
                               │ Structured tool result / file path
                               ▼
        ┌─────────────────────────────────────────────┐
        │        Agent Context Synthesis Turn         │
        └──────────────────────┬──────────────────────┘
                               │ Formatted response / Media upload
                               ▼
                      Shopkeeper Output
                 (Text, PDF Invoice, PPTX Deck)
```

---

## 3. How the Control Loop Works

The agent implements a cyclic **Observe → Reason → Act → Observe Result → Re-Reason → Respond** state machine in `agent/agent.py`:

1. **Observe:** The control loop receives the user prompt, appends it to conversation history, and prepends the system prompt enforcing kirana operations rules.
2. **Reason:** The loop posts conversation history and Ollama-compatible function definitions (`TOOL_SCHEMAS`) to the local Ollama `/api/chat` endpoint.
3. **Act:** If the LLM generates `tool_calls`, the agent extracts the function name and arguments. It validates function parameters via `inspect.signature` (filtering out hallucinated parameters from small models) and dispatches execution to the corresponding Python callable with the active SQLite connection.
4. **Observe Result:** The tool execution result is packaged as a JSON payload and appended to conversation history with role `tool`.
5. **Re-Reason:** The loop feeds the updated context back to Ollama. If additional tool calls are needed (e.g. multi-item billing sequence), it repeats the loop.
6. **Respond:** Once the model completes all tool interactions and emits a natural text response, the final text, updated history, and executed tools log are returned to the user.

---

## 4. Tool & Skill Surface

Every tool is registered in `agent/tools_registry.py` with strict type signatures:

| Tool | Purpose | Shape & Design Rationale |
|---|---|---|
| `add_product` | Adds a new SKU to the catalog | Requires SKU, name, unit, cost price, selling price, MRP, GST rate, HSN, and reorder level. Strict required fields prevent incomplete records. |
| `get_product` | Product catalog lookup | Accepts exact SKU or fuzzy name substring; returns all matching products so the agent can request clarification rather than guessing. |
| `receive_stock` | Records stock intake | Accepts product query and quantity, with optional cost price / MRP updates. Atomically increments inventory stock on hand. |
| `get_stock` | Single product inventory check | Takes product query; returns current quantity, reorder level, and a `is_low_stock` boolean flag for quick status checks. |
| `get_low_stock` | Storewide replenishment alert | Takes no arguments; queries all inventory rows where `quantity <= reorder_level`, sorted descending by shortfall urgency. |
| `create_bill` | Starts a new draft bill | Returns `bill_id`. Accepts optional `payment_mode` or automatically binds the stored `default_payment_mode` preference. |
| `add_bill_item` | Appends item to draft bill | Takes `bill_id`, product query, and quantity. Computes item taxable amount and GST; does not deduct stock until finalization. |
| `remove_bill_item` | Drops item from draft bill | Takes `bill_id` and product query string. Removes line item and recalculates subtotal, GST totals, and grand total. |
| `update_bill_item` | Modifies item quantity | Takes `bill_id`, product query, and `new_quantity`. Updates quantity and recalculates line-item and bill-level totals. |
| `get_bill` | Inspects full bill | Takes `bill_id`; returns bill header, line items, itemized GST breakdown, and grand total for user verification before sale. |
| `finalize_bill` | Commits sale & deducts stock | Takes `bill_id` and `idempotency_key`. Validates inventory, checks margins, decrements stock atomically, and assigns sequential invoice number. |
| `create_credit` | Adds debt (udhar) to customer | Takes customer name and amount. Automatically provisions customer record if new, logs credit entry, and updates running balance. |
| `record_credit_payment` | Records customer payment | Takes customer name and amount. Validates customer existence and guards against overpayment before updating balance. |
| `get_credit_balance` | Queries customer balance | Takes customer name; returns net outstanding credit balance (credits minus payments). Returns 0 for unknown customers. |
| `daily_summary` | Sales and revenue analytics | Accepts optional `date` (defaults to today). Returns total sales, bill count, CGST/SGST split, payment breakdown, and top products. |
| `set_preference` | Saves persistent shop setting | Takes `key` and `value` strings. Immediately persists store settings, defaults, or product aliases across app restarts. |
| `get_preference` | Reads persistent setting | Takes `key` and optional `default`. Fetches stored configurations without hardcoding assumptions. |
| `generate_invoice_pdf` | Generates printable PDF invoice | Takes `bill_id` or invoice string; compiles a GST-compliant ReportLab PDF in `generated/` and returns the file path. |
| `generate_sales_deck` | Builds sales presentation | Takes `period` ('day', 'week', 'month', 'all'); builds a PowerPoint presentation with embedded matplotlib charts in `generated/`. |

---

## 5. Database Schema & Architecture

SQLite with Write-Ahead Logging (`PRAGMA journal_mode = WAL`) and enforced foreign keys (`PRAGMA foreign_keys = ON`):

- **`products`**: Master product catalog (`id`, `sku` UNIQUE, `name`, `unit`, `cost_price`, `selling_price`, `mrp`, `gst_rate`, `hsn_code`, `reorder_level`, timestamps).
- **`inventory`**: Stock ledger (`id`, `product_id` UNIQUE FK, `quantity`, `last_restocked_at`, `updated_at`).
- **`bills`**: Sale transactions (`id`, `invoice_number` UNIQUE, `status`, `payment_mode`, `payment_reference`, `subtotal`, `cgst_total`, `sgst_total`, `gst_total`, `grand_total`, `idempotency_key` UNIQUE, timestamps).
- **`bill_items`**: Line items (`id`, `bill_id` FK, `product_id` FK, `quantity`, `unit_price`, `cost_price`, `taxable_amount`, `gst_rate`, `hsn_code`, `cgst_amount`, `sgst_amount`, `total`).
- **`customers`**: Khata directory (`id`, `name` UNIQUE COLLATE NOCASE, `phone`, `created_at`).
- **`khata_entries`**: Double-entry ledger (`id`, `customer_id` FK, `type`, `amount`, `balance_after`, `reference`, `created_at`).
- **`preferences`**: Key-value persistent memory (`key` PRIMARY KEY, `value`, `updated_at`).

---

## 6. Deterministic GST Engine

GST is computed strictly in deterministic Python (`tools/gst.py`), **never by the LLM**.

- **Approved Indian Slabs:** Validates against statutory slabs: `0%`, `5%`, `12%`, `18%`, and `28%`.
- **Intra-State Split:** Splits total tax equally between CGST (Central GST) and SGST (State GST):
  - Taxable Amount = Quantity × Unit Price
  - CGST = round((Taxable Amount × (GST Rate / 2)) / 100, 2)
  - SGST = round((Taxable Amount × (GST Rate / 2)) / 100, 2)
  - Line Total = Taxable Amount + CGST + SGST
- **Bill Aggregation:** Bill headers aggregate subtotals and taxes directly from line items, preventing floating-point drift.

---

## 7. Hardened Transaction Protections

### Oversell Guard
Before deducting any stock, `finalize_bill` opens an immediate exclusive transaction (`BEGIN IMMEDIATE`) and inspects stock availability for every line item. If any item's requested quantity exceeds available stock, the entire transaction is aborted via `ROLLBACK`, raising `InsufficientStockError` specifying requested quantity, available inventory, and shortfall. Stock levels remain completely unmodified.

### Below-Cost Guard
To protect kirana store profit margins from clerical or agent error, every line item in `finalize_bill` is verified against its landed cost (`unit_price >= cost_price`). If any item is sold below cost, `BelowCostSaleError` is raised and the transaction rolls back, preventing loss sales.

### Idempotent Finalization
Every `finalize_bill` call requires an `idempotency_key`. The `bills` table enforces a unique constraint on `idempotency_key`. If a retry or duplicate request arrives with a key that was already finalized, `finalize_bill` catches the collision, skips stock deduction, and returns the existing finalized bill data without double-decrementing inventory.

### Concurrency Protection
SQLite in WAL mode combined with `BEGIN IMMEDIATE` transaction locking guarantees serializable execution across multiple checkout threads or sessions. If two sales compete for the same inventory, one transaction commits while the second encounters updated stock levels, cleanly rejecting with `InsufficientStockError` rather than driving stock negative.

---

## 8. Customer Khata (Credit Ledger)

The khata module (`tools/khata.py`) implements a digital udhar ledger:
- **Instant Credit:** `create_credit("Ramesh", 500)` checks if customer "Ramesh" exists; if not, it automatically registers them, logs a `credit` transaction, and sets their balance to ₹500.
- **Strict Repayment Validation:** `record_credit_payment("Ramesh", 300)` validates that the customer exists and checks that payment does not exceed the outstanding debt (`amount <= balance`). Overpayments are rejected with `ValidationError`.
- **Audit History:** Every entry records `balance_after`, timestamps, and optional reference notes for transparent customer statements.

---

## 9. Persistent Memory & Preferences

Preferences (`tools/preferences.py`) survive complete application restarts and cleared conversation histories:
- Stored directly in the `preferences` table in SQLite.
- **Default Payment Mode:** Storing `set_preference("default_payment_mode", "upi")` ensures that subsequent billing requests omitting payment mode automatically inherit "upi" rather than defaulting to arbitrary values.
- **Store Metadata:** Stores shop name (`store_name`), GSTIN, and state code for invoice headers.
- **Product Aliases:** Stores custom aliases (`product_alias:atta` → `AASH-ATTA-5KG`) for natural language resolution.

---

## 10. Document Generation

### PDF Invoices (`documents/invoice.py`)
- Built using **ReportLab** (`SimpleDocTemplate`, `Table`, `Paragraph`, `colors`).
- Automatically pulls store name, address, and GSTIN from preferences.
- Generates professional, GST-compliant invoices featuring sequential invoice numbering (`INV-00001`), customer details, itemized tables with HSN codes, tax rates, CGST/SGST breakdowns, subtotals, grand totals, and payment modes.
- Output saved directly to `generated/invoice_<INVOICE_NUMBER>.pdf`.

### PowerPoint Sales Decks (`documents/sales_deck.py`)
- Built using **python-pptx**, **pandas**, and **matplotlib** (`Agg` headless backend).
- Aggregates real transaction data from SQLite over a specified period (`day`, `week`, `month`, `all`).
- Generates a multi-slide presentation:
  1. Title slide with reporting window and timestamp.
  2. Executive sales summary (total revenue, bill count, average bill value).
  3. GST tax collection summary (CGST, SGST, total GST).
  4. Payment method distribution with embedded **matplotlib pie chart**.
  5. Top-selling products by quantity with embedded **matplotlib bar chart**.
  6. Inventory stock health slide highlighting items below reorder level.
  7. Automated business insights computed from real data patterns.
- Output saved directly to `generated/sales_deck_<PERIOD>_<DATE>.pptx`.

---

## 11. Local Installation & Setup

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- [Ollama](https://ollama.com/) installed and running locally

### Setup Instructions

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
   # Primary recommended model:
   ollama pull qwen3:4b
   # Or lightweight fast model:
   ollama pull llama3.2:3b
   ```

5. **Configure environment:**
   Create a `.env` file in the root directory:
   ```env
   OLLAMA_HOST=http://localhost:11434
   OLLAMA_MODEL=qwen3:4b
   OLLAMA_TEST_MODEL=llama3.2:3b
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   ```

6. **Run full verification test suite:**
   ```bash
   python -m pytest tests/ -v
   ```

7. **Run the interactive demo runner:**
   ```bash
   python demo_runner.py
   ```

---

## 12. End-to-End Demo Walkthrough

The mandatory scenario tests the complete agent flow end-to-end:

| Step | Shopkeeper Message | Agent Action & Tool Call | Result |
|---|---|---|---|
| 1 | `"50 packets of Maggi came in, cost ₹12, MRP ₹14"` | `receive_stock(product_query='Maggi', quantity=50, cost_price=12, mrp=14)` | Maggi stock increased by 50 to 75; cost/MRP updated. |
| 2 | `"new item: Amul Butter 100g, GST 12%, MRP ₹62"` | Validates catalog entry / `add_product` | Product verified in catalog or prompts for missing required fields. |
| 3 | `"make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, 1 Amul butter, UPI"` | `create_bill(payment_mode='upi')` + `add_bill_item` × 4 | Draft bill created with 4 line items; taxes calculated. |
| 4 | `"drop the butter"` | `remove_bill_item(bill_id, 'Amul Butter')` | Butter removed; subtotal and GST recalculated. |
| 5 | `"make it 6 Maggi"` | `update_bill_item(bill_id, 'Maggi', 6)` | Maggi quantity updated to 6; bill totals recalculated. |
| 6 | `"finalize"` | `finalize_bill(bill_id, idempotency_key)` | Bill finalized as `INV-00001`; inventory stock deducted. |
| 7 | *Attempt to sell more Maggi than in stock* | `finalize_bill` triggers oversell check | Cleanly rejected with `InsufficientStockError`; stock unchanged. |
| 8 | `"put ₹500 on Ramesh's credit"` | `create_credit('Ramesh', 500)` | Customer ledger created; Ramesh balance = ₹500. |
| 9 | `"Ramesh's balance?"` | `get_credit_balance('Ramesh')` | Agent replies: Ramesh's balance is ₹500. |
| 10 | `"Ramesh paid ₹300"` | `record_credit_payment('Ramesh', 300)` | Payment recorded; balance updated to ₹200. |
| 11 | `"Ramesh's balance?"` | `get_credit_balance('Ramesh')` | Agent replies: Ramesh's balance is ₹200. |
| 12 | `"send me that bill as a PDF"` | `generate_invoice_pdf('INV-00001')` | Real ReportLab PDF generated in `generated/`. |
| 13 | `"make this week's sales analysis deck"` | `generate_sales_deck('week')` | Real PowerPoint deck generated with matplotlib charts. |
| 14 | `"always assume UPI unless I say cash"` → restart bot → `"make a bill for 2 Maggi"` | `set_preference('default_payment_mode', 'upi')` → restart session | Preference persists in SQLite; new bill finalized with UPI. |

---

## 13. Known Limitations & Deferred Features

The following features were intentionally left out to focus on transactional correctness, low latency, and zero-cost local execution:

1. **Voice Notes / Audio Transcription:** Audio speech-to-text models (such as Whisper) were omitted to preserve CPU/RAM bandwidth for local LLM inference on standard hardware.
2. **Multi-Language (Hinglish / Regional Languages):** Tokenization overhead and model drift on smaller local LLMs were deferred to prioritize 100% deterministic tool-calling reliability in English.
3. **Barcode / Photo Recognition:** Real-time computer vision OCR models were excluded to keep the deployment lightweight without requiring GPU acceleration.
4. **Expiry Date & FEFO Inventory Tracking:** Batch-level First-Expiry-First-Out logic requires warehouse-scale lot management that adds unnecessary friction to daily kirana counter sales.
5. **Scheduled / Proactive Decks:** Background cron scheduler daemons were omitted to keep the agent architecture completely reactive to incoming user requests.
6. **Reorder Velocity Forecasting:** Time-series sales forecasting algorithms were deferred until a store accumulates sufficient months of historical baseline transactions.