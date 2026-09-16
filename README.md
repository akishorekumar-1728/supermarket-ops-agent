# 🛒 Supermarket Ops Agent — Nebula Bot

An autonomous AI operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram, the agent handles product cataloging, stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation — powered by **Google Gemini 3.6 Flash** and deployed on **Render**.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Submission Report](https://img.shields.io/badge/Submission-Official%20Report-orange?logo=readme)](submission/SUBMISSION_REPORT.md)
[![Python Version](https://img.shields.io/badge/Python-3.11-brightgreen?logo=python)](https://python.org)
[![Gemini AI](https://img.shields.io/badge/Google-Gemini%203.6%20Flash-4285F4?logo=google)](https://aistudio.google.com)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render)](https://render.com)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-lightgrey?logo=sqlite)](https://sqlite.org)

> 📌 **Official Submission Package**:  
> For full technical grading criteria, harness rationale, capability surface, hard problem solutions, and sample PDF/PPTX outputs, read the [**Project Submission Report (`submission/SUBMISSION_REPORT.md`)**](submission/SUBMISSION_REPORT.md).

---

## 🆕 Recent Updates & Enhancements

| # | Feature / Fix | Detail |
|---|---|---|
| 1 | **Upgraded LLM: Gemini 3.6 Flash** | Migrated to Google's latest active model `gemini-3.6-flash` with automatic fallback |
| 2 | **Automatic 10-Key Rotation** | `GEMINI_API_KEYS` rotates across 10 API keys instantly when quota/token limits hit |
| 3 | **Stateful Chat Transfer** | Conversation context (`chat.history`) preserved across key switches with zero data loss |
| 4 | **Render Cloud Deployment** | Lightweight HTTP server on `$PORT` with `do_HEAD` & self-pinger to prevent free-tier sleep |
| 5 | **Smart Unit Normalization** | Intelligently resolves spacing variations (`5 kg` vs `5kg`, `70 g` vs `70g`, `1 l` vs `1l`) |
| 6 | **Bot Integrity Guard** | Automatically enforces clean business descriptions and registered commands on startup |
| 7 | **Speed Optimization** | Sub-10ms deterministic fast-path for common kirana operations (< 5ms response time) |

---

## 📋 Kirana Operations & Example Messages

The agent understands natural kirana store language — no rigid commands required:

| Intent | Example Message | What the Agent Does | Response Time |
|---|---|---|---|
| **Receive stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Adds 50 pkts to stock; updates cost & MRP | ~15 ms |
| **Add new product** | `new item: Amul Butter 100g, GST 12%, MRP ₹62` | Registers in catalog with HSN, GST slab | ~2 ms |
| **Cut a bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | Opens draft bill with CGST + SGST split | ~6 ms |
| **Edit bill mid-way** | `drop the butter, make it 6 Maggi` | Removes item, updates quantity, recalculates | ~2 ms |
| **Stock query** | `how much sugar is left?` | Instant stock check with low-stock alert | ~1 ms |
| **Low-stock / reorder** | `what's running out?` | Lists products at or below reorder level | ~0.2 ms |
| **Khata credit** | `put ₹500 on Ramesh's credit` · `Ramesh paid ₹300` · `Ramesh's balance?` | Auto-registers customer, tracks debt/payment | ~0.5 ms |
| **Daily close** | `today's sales?` or `close the day` | Total sales, GST collected, cash vs UPI | ~0.8 ms |
| **Invoice PDF** | `send me that bill as a PDF` | GST-compliant PDF invoice sent to Telegram | ~44 ms |
| **Analysis deck** | `make this week's sales analysis deck` | PowerPoint `.pptx` with charts sent to Telegram | ~300 ms |
| **Set preference** | `always assume UPI unless I say cash` | Persists across sessions; resolves aliases | ~0.4 ms |

> **Ambiguity Guard**: When a query is ambiguous (e.g. `add atta` when multiple brands exist), the agent asks a clarifying question rather than guessing.

---

## ⚡ Architecture & Latency Engine

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

### Automatic 10-Key Rotation System
- **`GEMINI_API_KEYS`** accepts a comma-separated list of Gemini API keys.
- When any key exhausts request limits (`429`, `ResourceExhausted`, daily/minute token caps), the agent **catches the error in milliseconds**, switches to the next active key, and transparently retries the turn.
- Active message history (`chat.history`) is transferred directly to the new session to prevent state loss.

---

## 🛡️ Enterprise Safeguards

| Safeguard | Implementation |
|---|---|
| **Statutory GST Calculator** | Pure Python: 0%, 5%, 12%, 18%, 28% slabs with 50/50 CGST+SGST split |
| **Atomic Finalization** | Serialized `BEGIN IMMEDIATE` SQLite transactions in WAL mode |
| **Oversell Guard** | Aborts checkout and rolls back if requested quantity exceeds stock |
| **Below-Cost Guard** | Rejects any sale where selling price is lower than cost price |
| **Idempotency** | Unique idempotency key prevents double inventory deduction on retries |
| **Multi-Key Failover** | Auto-rotates Gemini API keys on token or rate limit errors |

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
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Configure your credentials:
```env
TELEGRAM_BOT_TOKEN=<YOUR_TELEGRAM_BOT_TOKEN>

# Comma-separated list of Gemini API keys for automatic quota rotation
GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3,...

GEMINI_MODEL=gemini-3.6-flash
```

### 3. Seed Database & Run Tests
```bash
python database/import_dataset.py   # Seeds products & initial customer khata
python -m pytest tests/ -v          # Runs automated test suite
```

### 4. Run the Bot
```bash
python main.py
```
Open Telegram and message **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)**!

---

## ☁️ Deploy to Render

1. Push your repository to GitHub.
2. Log in to [render.com](https://render.com) $\rightarrow$ **New Web Service** $\rightarrow$ Connect your repository.
3. Configure service parameters:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
4. Add **Environment Variables** in Render settings:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token from @BotFather |
| `GEMINI_API_KEYS` | `key1,key2,key3,...` (comma-separated keys) |
| `GEMINI_MODEL` | `gemini-3.6-flash` |

5. Click **Deploy Web Service** ✅.

---

## 📁 Project Structure

```text
supermarket-ops-agent/
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

- **GitHub Repository**: [akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Live Telegram Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)