# 🛒 Supermarket Ops Agent

An autonomous AI operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram, the agent handles product cataloging, stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation — powered by **Google Gemini AI** and deployed on Render.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![Gemini AI](https://img.shields.io/badge/Google-Gemini%202.0%20Flash-4285F4?logo=google)](https://aistudio.google.com)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-lightgrey?logo=sqlite)](https://sqlite.org)

---

## 📋 Owner Capabilities & Example Messages

The agent is driven by natural language — the shopkeeper can speak or text naturally:

| Intent | Example Message | What the Agent Does | Latency |
|---|---|---|---|
| **Receive stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Atomically adds 50 pkts to stock; updates landed cost & MRP in database | ~15 ms |
| **Add a new product** | `new item: Amul Butter 100g, GST 12%, MRP ₹62` | Registers product in catalog with HSN, GST slab, and prices | ~2 ms |
| **Cut a bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | Opens draft bill, calculates 50/50 CGST & SGST splits, displays summary | ~6 ms |
| **Edit a bill mid-build** | `drop the butter, make it 6 Maggi` | Removes butter, updates Maggi to 6, and recalculates totals | ~2 ms |
| **Stock query** | `how much sugar is left?` | Instant stock check showing quantity, unit, and low-stock alerts | ~1 ms |
| **Low-stock / reorder** | `what's running out?` | Scans products where `quantity <= reorder_level`, ranked by urgency | ~0.2 ms |
| **Credit (khata)** | `put ₹500 on Ramesh's credit`<br>`Ramesh paid ₹300`<br>`Ramesh's balance?` | Auto-registers customer, logs credit, prevents overpayments | ~0.5 ms |
| **Daily close** | `today's sales?` or `close the day` | Total sales, GST collected, cash vs UPI split, top items | ~0.8 ms |
| **Invoice as PDF** | `send me that bill as a PDF` | Delivers a GST-compliant **ReportLab PDF invoice** into Telegram | ~44 ms |
| **Analysis deck** | `make this week's sales analysis deck` | Builds a **PowerPoint (.pptx) deck** with embedded charts | ~300 ms |
| **Set a preference** | `always assume UPI unless I say cash` | Persists store defaults across sessions; resolves shorthand aliases | ~0.4 ms |

> **Ambiguity Handling**: When a query is ambiguous, the agent asks a clarifying question rather than guessing.

---

## ⚡ Architecture & Performance

### 1. Cloud-Native AI Agent
- **Google Gemini 2.0 Flash**: Fast, free-tier API — no local GPU or Ollama required.
- **Render Deployment**: Fully hosted; bot runs 24/7 in the cloud.

### 2. Sub-10ms Latency Engine
- **Zero-Latency Fast Path (`agent/fast_path.py`)**: Direct deterministic execution for standard store operations, bypassing the LLM entirely. Common operations execute in **0.1 to 50 milliseconds**.
- **Smart Product Resolution**: Fuzzy mapping from informal shorthand (`"maggi"`, `"atta"`) to exact SKUs.
- **Intent-Based Tool Router (`agent/intent_router.py`)**: Routes only the 3–5 relevant tools instead of all 19, reducing Gemini API token usage significantly.

```text
Shopkeeper (Telegram)
           │
           ▼
┌───────────────────────────────────────┐
│     Zero-Latency Fast Path Engine     │ ─── [Matches?] ──► Instant Response (< 10ms)
└──────────────────┬────────────────────┘
                   │ Fallback (Complex / Ambiguous)
                   ▼
┌───────────────────────────────────────┐
│  Intent Router + Gemini Agent Loop    │ ───► Tool Execution (1–3s)
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

- **Deterministic GST Engine (`tools/gst.py`)**: Indian slabs (0%, 5%, 12%, 18%, 28%) with 50/50 CGST + SGST split, computed in pure Python — never hallucinated.
- **Atomic Finalization**: Serialized `BEGIN IMMEDIATE` SQLite transactions in WAL mode.
- **Oversell Guard**: Aborts checkout if requested quantity exceeds available stock.
- **Below-Cost Protection**: Rejects sales where `unit_price < cost_price`.
- **Idempotency Guard**: Unique key ensures retries never double-deduct inventory.

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

### 2. Get a Free Gemini API Key
1. Go to [https://aistudio.google.com/](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **"Get API Key"** → **"Create API Key"**
4. Copy the key

### 3. Configure Environment (`.env`)
Create `.env` (or copy from `.env.example`):
```bash
cp .env.example .env
```
```env
TELEGRAM_BOT_TOKEN=<YOUR_TELEGRAM_BOT_TOKEN>

# Add multiple Gemini API keys (comma-separated) for automatic rotation
# when one key's quota is exhausted. Single key also works fine.
GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3,...

GEMINI_MODEL=gemini-2.0-flash
```

> **💡 Multi-Key Rotation**: The bot automatically rotates to the next API key when it detects a quota/rate-limit error. Add as many free keys as you want from [aistudio.google.com](https://aistudio.google.com/).

### 4. Seed Database & Run Tests
```bash
# Seed 51 products and 5 customer accounts:
python database/import_dataset.py

# Run all automated tests:
python -m pytest tests/ -v
```

### 5. Start the Telegram Bot
```bash
python main.py
```
Open Telegram and message **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)**!

---

## ☁️ Deploy to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New Web Service** → connect your repo
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `python main.py`
5. Add **Environment Variables** in the Render dashboard:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `GEMINI_API_KEYS` = `key1,key2,key3,...` (all your keys, comma-separated)
   - `GEMINI_MODEL` = `gemini-2.0-flash`
6. Click **Deploy** ✅

---

## 📁 Project Structure

```text
supermarket-ops-agent/
├── agent/                  # Agent core loop, intent router, fast path & schemas
│   ├── agent.py            # Gemini function-calling control loop
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
├── tests/                  # pytest automated test suite
├── demo_runner.py          # Interactive CLI demo runner
└── main.py                 # Telegram Bot daemon
```

---

## 👤 Author & Links

- **GitHub Repository**: [https://github.com/akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Live Telegram Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)