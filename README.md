# 🛒 Supermarket Ops Agent — Nebula Bot

An autonomous AI operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram, the agent handles product cataloging, stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation — powered by **Google Gemini 3.6 Flash** and deployed on **Render**.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Submission Report](https://img.shields.io/badge/Submission-Official%20Report-orange?logo=readme)](submission/SUBMISSION_REPORT.md)
[![Python Version](https://img.shields.io/badge/Python-3.11-brightgreen?logo=python)](https://python.org)
[![Gemini AI](https://img.shields.io/badge/Google-Gemini%203.6%20Flash-4285F4?logo=google)](https://aistudio.google.com)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render)](https://render.com)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-lightgrey?logo=sqlite)](https://sqlite.org)

---

## 📦 Official Project Submission Deliverables

| Deliverable | Location | Description |
|---|---|---|
| 🤖 **Live Telegram Bot** | [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot) | Active 24/7 on Render cloud for reviewer interactive testing |
| 📑 **Submission Report** | [`submission/SUBMISSION_REPORT.md`](submission/SUBMISSION_REPORT.md) | Exhaustive ~1-page report detailing architecture, tools, and hard problems |
| 📄 **Project Document** | [`submission/Nebula.doc.docx`](submission/Nebula.doc.docx) | Word document submission file |
| 🧾 **Sample GST Invoice** | [`submission/SAMPLE_GST_INVOICE.pdf`](submission/SAMPLE_GST_INVOICE.pdf) | Generated ReportLab PDF tax invoice with itemized CGST/SGST splits |
| 📊 **Sample Sales Deck** | [`submission/SAMPLE_SALES_ANALYSIS_DECK.pptx`](submission/SAMPLE_SALES_ANALYSIS_DECK.pptx) | Generated PowerPoint sales presentation with embedded charts |

---

## 🧪 5-Minute Scenario Walkthrough for Reviewers

Reviewers can drive the live bot through the complete operational lifecycle in Telegram:

| Step | Action | Type in Telegram | What the Agent Does |
|---|---|---|---|
| 1 | **Start** | `/start` | Welcomes user & displays operational capability overview |
| 2 | **Receive Stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Atomically increments stock by 50, updates landed cost & MRP |
| 3 | **Receive Stock (Fuzzy)** | `20 packets of Aashirvaad Atta 5kg arrived, cost ₹280, MRP ₹320` | Resolves spacing variant (`5 kg` $\rightarrow$ `5kg`), updates inventory |
| 4 | **Multi-Item Bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | Draft bill created with statutory 50/50 CGST + SGST tax split |
| 5 | **Mid-Build Edit** | `drop the sugar, make it 6 Maggi` | Modifies draft in one turn: removes sugar, sets Maggi to 6 |
| 6 | **Finalize Bill** | `finalize the bill` | Atomically deducts inventory, locks bill, assigns `INV-XXXXX` |
| 7 | **Oversell Guard** | `make a bill: 500 Maggi, cash` | **Rejected by Oversell Guard**: requested quantity exceeds stock |
| 8 | **Khata Credit** | `put ₹750 on Ramesh's credit` | Registers customer automatically, logs credit debt to ledger |
| 9 | **Khata Payment** | `Ramesh paid ₹300` | Records partial payment, returns remaining balance (₹450) |
| 10 | **Invoice PDF** | `send me that bill as a PDF` | Delivers high-res GST Tax Invoice PDF directly in chat |
| 11 | **Sales Deck** | `make this week's sales analysis deck` | Delivers 6-slide PowerPoint `.pptx` deck with charts |
| 12 | **Store Preference** | `always assume UPI unless I say cash` | Saves preference permanently in SQLite memory |
| 13 | **Session Memory** | `/new` then `make a bill: 2 Maggi, 1kg sugar` | Fresh chat created; auto-applies stored UPI preference |

---

## ⚡ Architecture & Control Loop

### Two-Tier Execution Engine
```text
Shopkeeper (Telegram)
        │
        ▼
┌───────────────────────────────────────────┐
│     Zero-Latency Fast Path Engine         │  ← Handles 80% of store operations
│     (agent/fast_path.py)                  │    in 0.1 – 50 ms (pure Python / SQL)
└─────────────────┬─────────────────────────┘
                  │ Fallback for complex conversational turns
                  ▼
┌───────────────────────────────────────────┐
│     Intent Router + Gemini 3.6 Flash      │  ← Multi-key rotation across 10 keys
│     (agent/agent.py)                      │    Auto-switches key on quota limit
└─────────────────┬─────────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│  SQLite Database Layer (WAL Mode, Atomic Transactions, Foreign Keys)  │
│  • Catalog Master        • Inventory & Stock Alerts                   │
│  • GST Statutory Slabs   • Customer Khata Ledger                      │
│  • Store Preferences     • PDF Invoice & PPTX Sales Deck Generators   │
└───────────────────────────────────────────────────────────────────────┘
```

### 1. Harness Rationale
* **Zero-Latency Fast Path**: Supermarket counters cannot wait 3–5 seconds for simple stock lookups or intake. The deterministic engine matches common operational intents via regex and executes in **0.1 to 15 milliseconds**.
* **Google Gemini 3.6 Flash**: Fast, cloud-native reasoning with clean function-calling schemas for multi-item billing and complex conversational edits.
* **Automatic 10-Key Failover**: Free-tier API keys hit RPM/TPM caps during peak testing. The agent rotates across 10 keys in `< 500ms`, transparently migrating `chat.history` so no conversation context is lost.

---

## 🛠️ Capability Surface: Skills & Tools

| Module | Core Tool Functions | Capability Description |
|---|---|---|
| **Products** | `add_product`, `get_product` | HSN code validation, statutory GST slabs (0%, 5%, 12%, 18%, 28%), fuzzy SKU search |
| **Inventory** | `receive_stock`, `get_stock`, `get_low_stock` | Atomic stock intake, reorder alerts ranked by shortfall urgency |
| **Billing** | `create_bill`, `add_bill_item`, `remove_bill_item`, `update_bill_item`, `finalize_bill` | Draft billing, item modification, atomic stock deduction, invoice numbering |
| **Khata** | `create_credit`, `record_credit_payment`, `get_credit_balance` | Customer debt tracking, partial repayment, overpayment rejection |
| **Analytics** | `daily_summary` | Revenue aggregates, GST split (CGST vs SGST), payment breakdown, top items |
| **Preferences** | `set_preference`, `get_preference` | Key-value store memory for payment defaults and shorthand product aliases |
| **Documents** | `generate_invoice_pdf`, `generate_sales_deck` | ReportLab GST PDF invoices and python-pptx sales analysis decks with charts |

---

## 🛡️ Engineering Solutions for Core Hard Problems

| Hard Problem | Challenge | How We Solved It |
|---|---|---|
| **GST Calculation** | LLMs hallucinate tax percentages and rounding math | Computed in deterministic pure Python ([`tools/gst.py`](tools/gst.py)) with exact 50/50 CGST + SGST splits |
| **Oversell Prevention** | Preventing inventory over-allocation during busy hours | Draft bills **never deduct stock**. Finalization executes atomically inside a `BEGIN IMMEDIATE` transaction; aborts if stock < requested |
| **Below-Cost Protection** | Accidental price entry selling below store cost | Checkout validates `selling_price >= cost_price` for every line item before commit |
| **Idempotency** | Duplicate clicks/network retries double-deducting stock | `finalize_bill` requires a unique `idempotency_key`; repeats return existing invoice without touching stock |
| **Anti-Spam & Channel Security** | Compromised/scraped bot tokens and channel ad spam | Multi-layer shield: background daemon auto-enforces clean metadata, channel post interceptor auto-deletes spam & leaves unauthorized channels, Cyrillic/OSINT regex filter |
| **Sub-2s Fast Response** | LLM latency causing slow checkout at store counters | Deterministic fast-path regex engine resolves common operations in <15ms; polling interval set to 1.0s with instant typing indicator |
| **API Quota Caps** | Free-tier Gemini keys hitting token/rate limits | Multi-key failover manager automatically rotates across 10 API keys in under 500ms with state preservation |
| **Render Cloud Sleep** | Render free tier spinning down after 15 min inactivity | Background daemon in [`main.py`](main.py) periodically self-pings the application URL every 10 min |
| **Unit Normalization** | Mismatches between `5 kg` and `5kg` | Regex normalizer collapses unit spacing in search queries before database lookup |

---

## 🚀 Quickstart & Setup

### 1. Clone & Install
```bash
git clone https://github.com/akishorekumar-1728/supermarket-ops-agent.git
cd supermarket-ops-agent

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
```bash
cp .env.example .env
```
Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=<your_telegram_bot_token>

# Comma-separated list of Gemini API keys for automatic quota rotation
GEMINI_API_KEYS=key1,key2,key3,...

GEMINI_MODEL=gemini-3.6-flash
```

### 3. Seed Database & Run Tests
```bash
python database/import_dataset.py   # Seeds products & initial customer khata
python -m pytest tests/ -v          # Runs all 80+ automated unit tests
```

### 4. Start the Bot
```bash
python main.py
```
Open Telegram and message **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)**!

---

## ☁️ Deploy to Render

1. Push your repository to GitHub.
2. In [render.com](https://render.com) $\rightarrow$ **New Web Service** $\rightarrow$ Connect repository.
3. Configure settings:
   - **Environment**: `Python 3` (Render uses `.python-version` pinned to `3.11.9`)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
4. Set Environment Variables:
   - `TELEGRAM_BOT_TOKEN` = your bot token from @BotFather
   - `GEMINI_API_KEYS` = comma-separated Gemini API keys
   - `GEMINI_MODEL` = `gemini-3.6-flash`
5. Click **Deploy Web Service** ✅.

---

## 📁 Project Structure

```text
supermarket-ops-agent/
├── submission/             # Official submission folder
│   ├── SUBMISSION_REPORT.md# Exhaustive ~1-page submission report
│   ├── Nebula.doc.docx     # Project document
│   ├── SAMPLE_GST_INVOICE.pdf
│   └── SAMPLE_SALES_ANALYSIS_DECK.pptx
├── agent/
│   ├── agent.py            # Gemini 3.6 function-calling loop & 10-key rotation
│   ├── fast_path.py        # Zero-latency sub-10ms deterministic execution
│   ├── intent_router.py    # Intent router for token reduction
│   ├── system_prompt.py    # Indian kirana business persona & constraints
│   └── tools_registry.py  # JSON schemas for tool function-calling
├── tools/
│   ├── products.py         # Product master management & fuzzy search
│   ├── inventory.py        # Stock intake & low-stock alerts
│   ├── gst.py              # Statutory Indian GST slab calculator
│   ├── billing.py          # Draft billing, item edits & atomic finalization
│   ├── khata.py            # Customer credit ledger & payment tracking
│   ├── analytics.py        # Daily & period sales performance summaries
│   └── preferences.py      # Persistent key-value store memory
├── documents/
│   ├── invoice.py          # ReportLab GST Tax Invoice PDF generator
│   └── sales_deck.py       # python-pptx sales presentation deck generator
├── database/               # SQLite schema, connection utilities, and seed data
├── data/                   # SQLite database file
├── tests/                  # Automated pytest test suite
├── .python-version         # Pinned to Python 3.11.9 for stable Render builds
├── .env.example            # Environment template without secrets
├── requirements.txt        # Python package dependencies
└── main.py                 # Telegram Bot daemon & Render health check server
```

---

## 🤖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Displays welcome banner and full capability overview |
| `/help` | Detailed guide with example natural language queries |
| `/reset` | Clears conversation memory while preserving database state |
| `/new` | Starts a fresh session |

---

## 👤 Author & Links
- A KISHORE KUMAR
- **GitHub Repository**: [akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Live Telegram Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)
- **Official Submission Report**: [`submission/SUBMISSION_REPORT.md`](submission/SUBMISSION_REPORT.md)
