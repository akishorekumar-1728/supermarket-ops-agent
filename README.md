# 🛒 Supermarket Ops Agent

An autonomous, local-first AI operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram or CLI, the agent handles product cataloging, stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![Local LLM](https://img.shields.io/badge/Ollama-Local--First-orange?logo=ollama)](https://ollama.com)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-lightgrey?logo=sqlite)](https://sqlite.org)

---

## 📋 Owner Capabilities & Example Messages

The agent is driven by natural language capabilities rather than rigid syntax. The shopkeeper can speak or text naturally:

| Intent | Example Message | What the Agent Does | Latency |
|---|---|---|---|
| **Receive stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Atomically adds 50 pkts to stock; updates landed cost & MRP in database | ~15 ms |
| **Add a new product** | `new item: Amul Butter 100g, GST 12%, MRP ₹62` | Verifies or registers product in catalog with HSN, GST slab, and prices | ~2 ms |
| **Cut a bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, 1 Amul butter, UPI` | Opens draft bill, calculates 50/50 CGST & SGST splits, and displays summary | ~6 ms |
| **Edit a bill mid-build** | `drop the butter, make it 6 Maggi` | Performs **both actions in one turn**: removes butter, updates Maggi to 6, and updates totals | ~2 ms |
| **Stock query** | `how much sugar is left?` | Instant stock check showing quantity, unit, and low-stock alerts | ~1 ms |
| **Low-stock / reorder** | `what's running out?` | Scans products where `quantity <= reorder_level`, ranked by shortfall urgency | ~0.2 ms |
| **Credit (khata)** | `put ₹500 on Ramesh's credit`<br>`Ramesh paid ₹300`<br>`Ramesh's balance?` | Auto-registers customer, logs credit, prevents overpayments, and displays balance | ~0.5 ms |
| **Daily close** | `today's sales?` or `close the day` | Generates day close summary: total sales, GST collected, **cash vs UPI split**, and top items | ~0.8 ms |
| **Invoice as PDF** | `send me that bill as a PDF` or `give a pdf` | Compiles and delivers a GST-compliant **ReportLab PDF invoice** directly into Telegram | ~44 ms |
| **Analysis deck** | `make this week's sales analysis deck` | Builds a **PowerPoint (.pptx) deck** with embedded Matplotlib pie & bar charts | ~300 ms |
| **Set a preference** | `always assume UPI unless I say cash`<br>`default atta = Aashirvaad 5kg` | Persists store defaults across reboots; automatically resolves shorthand aliases | ~0.4 ms |

> **Ambiguity Handling**: When a query is genuinely ambiguous (e.g., `add atta` when multiple brands exist), the agent asks a clarifying question rather than guessing.

---

## ⚡ Architecture & Performance

### 1. Zero-Budget Local Agent Harness
- **100% Free & Open**: Powered by local Ollama (`llama3.2:3b` / `qwen3:4b`). No paid Claude or OpenAI APIs used anywhere.
- **Privacy First**: All sales, catalog data, prices, customer khata debts, and invoices stay strictly on-device.

### 2. Sub-10ms Latency Engine
- **Zero-Latency Fast Path (`agent/fast_path.py`)**: Direct deterministic execution for standard store operations, bypassing LLM prompt token evaluation entirely. Common operations execute in **0.1 to 50 milliseconds**.
- **Smart Product Resolution (`resolve_product_name`)**: Fuzzy mapping from informal shorthand (`"maggi"`, `"atta"`, `"butter"`) to exact SKUs.
- **Intent-Based Tool Router (`agent/intent_router.py`)**: For complex conversational queries, routes only the 3–5 relevant tools (~300 tokens) instead of all 19 tools (2,667 tokens), dropping LLM response time from 60s to 1.5–2.5s.

```text
Shopkeeper (Telegram / CLI)
           │
           ▼
┌───────────────────────────────────────┐
│     Zero-Latency Fast Path Engine     │ ─── [Matches?] ──► Instant Response (< 10ms)
└──────────────────┬────────────────────┘
                   │ Fallback (Complex / Ambiguous)
                   ▼
┌───────────────────────────────────────┐
│  Intent Router + Local Ollama Agent   │ ───► Tool Execution (1.5 - 2.5s)
└──────────────────┬────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SQLite Database Layer (WAL Mode, Foreign Keys, Atomic Transactions)         │
│  • Products & Inventory   • GST & Billing Engine   • Customer Khata Ledger  │
│  • Store Preferences      • PDF Invoice Generator  • PPTX Sales Deck Engine │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Enterprise Safeguards

- **Deterministic GST Engine (`tools/gst.py`)**: Statutory Indian slabs (`0%`, `5%`, `12%`, `18%`, `28%`) with 50/50 CGST + SGST intra-state split computed in pure Python, never hallucinated by an LLM.
- **Atomic Finalization (`tools/billing.py`)**: Serialized `BEGIN IMMEDIATE` SQLite transactions in WAL mode.
- **Oversell Guard**: Aborts checkout and rolls back if requested quantity exceeds available stock.
- **Below-Cost Protection**: Rejects sales where `unit_price < cost_price` to prevent store losses.
- **Idempotency Guard**: Unique `idempotency_key` ensures retries never double-deduct inventory.

---

## 🚀 Quickstart & Setup

### 1. Clone & Install
```bash
git clone https://github.com/akishorekumar-1728/supermarket-ops-agent.git
cd supermarket-ops-agent

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Pull Ollama Model
```bash
ollama pull llama3.2:3b
```

### 3. Configure Environment (`.env`)
```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
```

### 4. Seed Database & Run Tests
```bash
# Seed 51 products and 5 customer accounts:
python database/import_dataset.py

# Run all 180+ automated tests:
python -m pytest tests/ -v
```

### 5. Start the Telegram Bot
```bash
python main.py
```
Open Telegram and message **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)**!

---

## 📁 Project Structure

```text
supermarket-ops-agent/
├── agent/                  # Agent core loop, intent router, fast path & schemas
│   ├── agent.py            # Ollama control loop & execution handler
│   ├── fast_path.py        # Zero-latency sub-10ms deterministic execution
│   ├── intent_router.py    # Schema token-reduction router
│   ├── system_prompt.py    # Kirana business rules & prompts
│   └── tools_registry.py   # Function schemas for tool calling
├── database/               # SQLite connection, schema, seed, and importer
├── tools/                  # Deterministic business tools
│   ├── products.py         # Product catalog management
│   ├── inventory.py        # Stock intake & low-stock alerts
│   ├── gst.py              # GST tax slab & split calculator
│   ├── billing.py          # Draft billing, edits & atomic finalization
│   ├── khata.py            # Customer credit & payment ledger
│   └── preferences.py      # Persistent key-value store memory
├── documents/              # Document generation engines
│   ├── invoice.py          # ReportLab GST Tax Invoice PDF
│   └── sales_deck.py       # python-pptx sales presentation deck
├── data/                   # SQLite database & 51-item supermarket catalog
├── tests/                  # 180+ pytest automated test suite
├── demo_runner.py          # Interactive CLI demo runner
└── main.py                 # Telegram Bot daemon
```

---

## 👤 Author & Links

- **GitHub Repository**: [https://github.com/akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Live Telegram Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)