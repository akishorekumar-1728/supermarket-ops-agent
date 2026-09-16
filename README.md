# 🛒 Supermarket Ops Agent — Nebula Bot

An autonomous AI operations assistant for Indian kirana stores and supermarkets. Through natural language in Telegram, the agent handles product cataloging, stock intake, multi-item billing with automated GST calculation, customer credit ledgers (khata), daily analytics, and professional PDF/PPTX document generation — powered by **Google Gemini 2.0 Flash** and deployed on **Render**.

[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/akishorekumar-1728/supermarket-ops-agent)
[![Telegram Bot](https://img.shields.io/badge/Telegram-@supermarket__ops__nebula__bot-2CA5E0?logo=telegram)](https://t.me/supermarket_ops_nebula_bot)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-brightgreen?logo=python)](https://python.org)
[![Gemini AI](https://img.shields.io/badge/Google-Gemini%202.0%20Flash-4285F4?logo=google)](https://aistudio.google.com)
[![Render](https://img.shields.io/badge/Deployed%20on-Render-46E3B7?logo=render)](https://render.com)
[![Database](https://img.shields.io/badge/SQLite-WAL%20Mode-lightgrey?logo=sqlite)](https://sqlite.org)

---

## 🆕 Recent Changes (Sep 2026)

| # | Change | Detail |
|---|---|---|
| 1 | **Switched LLM: Ollama → Gemini** | Replaced local Ollama with Google Gemini 2.0 Flash API — now works on Render cloud |
| 2 | **Multi-Key Rotation** | `GEMINI_API_KEYS` supports 10+ comma-separated keys; auto-rotates on quota exhaustion |
| 3 | **Speed Optimization** | `drop_pending_updates=True`, reduced `max_output_tokens` to 300, added connection timeouts |
| 4 | **Bot Description Fixed** | Cleared spam description; set proper kirana store description via Telegram API |
| 5 | **Bot Commands Set** | `/start`, `/help`, `/reset`, `/new` commands registered in BotFather |
| 6 | **Render Cloud Deploy** | Health check HTTP server added; bot runs 24/7 on Render free tier |

---

## 📋 Owner Capabilities & Example Messages

The agent understands natural language — type like you're texting a helper:

| Intent | Example Message | What the Agent Does | Speed |
|---|---|---|---|
| **Receive stock** | `50 packets of Maggi came in, cost ₹12, MRP ₹14` | Adds 50 pkts to stock; updates cost & MRP | ~15 ms |
| **Add new product** | `new item: Amul Butter 100g, GST 12%, MRP ₹62` | Registers in catalog with HSN, GST slab | ~2 ms |
| **Cut a bill** | `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI` | Draft bill with CGST + SGST split | ~6 ms |
| **Edit bill mid-way** | `drop the butter, make it 6 Maggi` | Removes item, updates quantity, recalculates | ~2 ms |
| **Stock query** | `how much sugar is left?` | Instant stock check with low-stock alert | ~1 ms |
| **Low-stock / reorder** | `what's running out?` | Lists products at or below reorder level | ~0.2 ms |
| **Khata credit** | `put ₹500 on Ramesh's credit` · `Ramesh paid ₹300` · `Ramesh's balance?` | Auto-registers customer, tracks debt/payment | ~0.5 ms |
| **Daily close** | `today's sales?` or `close the day` | Total sales, GST collected, cash vs UPI | ~0.8 ms |
| **Invoice PDF** | `send me that bill as a PDF` | GST-compliant PDF invoice sent to Telegram | ~44 ms |
| **Analysis deck** | `make this week's sales analysis deck` | PowerPoint `.pptx` with charts sent to Telegram | ~300 ms |
| **Set preference** | `always assume UPI unless I say cash` | Persists across sessions; resolves aliases | ~0.4 ms |

> **Tip:** Ambiguous queries (e.g. `add atta` when 2 brands exist) trigger a clarifying question — the bot never guesses.

---

## ⚡ Architecture & Performance

### Speed: Two-Layer Design

```text
You (Telegram)
      │
      ▼
┌─────────────────────────────────────────┐
│   Zero-Latency Fast Path Engine          │  ← Handles 80% of operations
│   (agent/fast_path.py)                   │    in 0.1 – 50 ms (no LLM!)
└───────────────┬─────────────────────────┘
                │ Fallback: complex / ambiguous messages
                ▼
┌─────────────────────────────────────────┐
│   Intent Router + Gemini 2.0 Flash       │  ← Handles remaining 20%
│   Multi-Key Rotation (10 keys)           │    in 2 – 4 seconds
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SQLite Database (WAL Mode, Atomic Transactions, Foreign Keys)        │
│  Products · Inventory · Billing · GST · Khata · Preferences · Docs  │
└─────────────────────────────────────────────────────────────────────┘
```

### AI: Google Gemini Multi-Key Rotation
- **`GEMINI_API_KEYS`** — comma-separated list of API keys
- When one key hits quota, auto-rotates to the next key instantly
- Supports unlimited keys — add as many free keys as you want
- Fallback → fallback → fallback, zero downtime

### Fast Path (No LLM needed)
The `agent/fast_path.py` handles most common kirana operations directly with regex + SQL:
- Stock queries, khata balance checks, low-stock alerts
- Simple stock intake (standard phrases)
- Daily summary, preference lookups

---

## 🛡️ Business Safeguards

| Safeguard | How it works |
|---|---|
| **GST Engine** | Pure Python: 0/5/12/18/28% slabs, 50/50 CGST+SGST, never hallucinated |
| **Atomic Finalization** | `BEGIN IMMEDIATE` SQLite transactions in WAL mode |
| **Oversell Guard** | Aborts bill if stock < requested quantity |
| **Below-Cost Guard** | Rejects sale where `price < cost_price` |
| **Idempotency** | Unique key prevents double stock deduction on retry |
| **Multi-Key Failover** | Auto-rotates Gemini API key on quota error |

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

### 2. Get Free Gemini API Keys
1. Go to **[aistudio.google.com](https://aistudio.google.com/)**
2. Sign in → **Get API Key** → **Create API Key**
3. Create multiple keys for rotation (all free)

### 3. Configure `.env`
```bash
cp .env.example .env
```
Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=<your_telegram_bot_token>

# Multiple keys comma-separated — auto-rotates on quota exhaustion
GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3

GEMINI_MODEL=gemini-2.0-flash
```
> ⚠️ `.env` is gitignored — your keys are **never** pushed to GitHub.

### 4. Seed Database & Run Tests
```bash
python database/import_dataset.py   # Seeds 51 products + 5 customers
python -m pytest tests/ -v          # Run all automated tests
```

### 5. Start the Bot
```bash
python main.py
```
Then open Telegram → **[@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)** → `/start`

---

## ☁️ Deploy to Render (Free)

1. Push repo to GitHub
2. **[render.com](https://render.com)** → **New Web Service** → connect your repo
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `python main.py`
5. Add **Environment Variables**:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `GEMINI_API_KEYS` | `key1,key2,key3,...` (all comma-separated) |
| `GEMINI_MODEL` | `gemini-2.0-flash` |

6. Click **Deploy** → bot runs 24/7 ✅

---

## 📁 Project Structure

```text
supermarket-ops-agent/
├── agent/
│   ├── agent.py            # Gemini function-calling loop + multi-key rotation
│   ├── fast_path.py        # Zero-latency deterministic execution (no LLM)
│   ├── intent_router.py    # Routes only relevant tool schemas → faster Gemini
│   ├── system_prompt.py    # Kirana business rules & assistant personality
│   └── tools_registry.py  # Function schemas for Gemini tool calling
├── tools/
│   ├── products.py         # Product catalog CRUD
│   ├── inventory.py        # Stock intake & low-stock alerts
│   ├── gst.py              # GST slab calculator (0/5/12/18/28%)
│   ├── billing.py          # Draft billing, edits & atomic finalization
│   ├── khata.py            # Customer credit & payment ledger
│   ├── analytics.py        # Daily/weekly sales summaries
│   └── preferences.py      # Persistent key-value memory
├── documents/
│   ├── invoice.py          # ReportLab GST Tax Invoice PDF generator
│   └── sales_deck.py       # python-pptx sales presentation deck
├── database/               # SQLite schema, seed data, connection utilities
├── data/                   # SQLite database + 51-item supermarket catalog
├── tests/                  # pytest automated test suite
├── .env.example            # Environment variable template (no secrets)
├── requirements.txt        # Python dependencies
├── demo_runner.py          # Interactive CLI demo
└── main.py                 # Telegram Bot daemon (Render-ready)
```

---

## 🤖 Telegram Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message + full capabilities list |
| `/help` | Quick reference for all features |
| `/reset` | Clear conversation memory, keep preferences |
| `/new` | Start a fresh chat session |

---

## 👤 Author & Links

- **GitHub**: [akishorekumar-1728/supermarket-ops-agent](https://github.com/akishorekumar-1728/supermarket-ops-agent)
- **Live Bot**: [@supermarket_ops_nebula_bot](https://t.me/supermarket_ops_nebula_bot)