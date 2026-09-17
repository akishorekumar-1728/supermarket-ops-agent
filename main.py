"""
main.py
=======
Telegram Bot Interface for Supermarket Ops Agent (@supermarket_ops_nebula_bot).

Bridges Telegram chat messages to the local Ollama LLM agent control loop,
dispatching business tools, managing SQLite state, and delivering generated
PDF invoices and PowerPoint sales analysis decks directly to the chat.

Configuration:
    TELEGRAM_BOT_TOKEN  Telegram Bot Token (from @BotFather)
    OLLAMA_HOST         Ollama server URL (default: http://localhost:11434)
    OLLAMA_MODEL        Ollama model (default: qwen3:4b, fallback: llama3.2:3b)
    DB_PATH             Path to SQLite database (default: data/supermarket.db)

Usage:
    python main.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database.connection import get_and_init, get_connection
from database.seed import seed
from agent.agent import chat_turn, OllamaConnectionError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("supermarket_ops_bot")

DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "supermarket.db"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
if GEMINI_MODEL in ("gemini-2.0-flash", "gemini-2.5-flash"):
    GEMINI_MODEL = "gemini-3.6-flash"

# In-memory per-chat conversation history: chat_id -> list of message dicts
CHAT_HISTORIES: dict[int, list[dict]] = {}


def init_database() -> None:
    """Ensure data/ directory exists and initialize SQLite DB schema with seed data."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = get_and_init(DB_PATH)
    # Seed initial items if product catalog is empty
    product_count = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if product_count == 0:
        logger.info("Database is empty; seeding initial products and inventory...")
        seed(c, clear=False)
    c.close()
    logger.info(f"Database initialized at {DB_PATH}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []

    welcome_text = (
        f"Namaste {user.first_name}! 🛒\n\n"
        f"I am your *Supermarket Ops Assistant* for kirana store operations.\n"
        f"These are my core capabilities (you can talk in natural English):\n\n"
        f"📦 *Receive stock:*\n"
        f"`50 packets of Maggi came in, cost ₹12, MRP ₹14`\n\n"
        f"🏷️ *Add a new product:*\n"
        f"`new item: Amul Butter 100g, GST 12%, MRP ₹62`\n\n"
        f"🧾 *Cut a bill:*\n"
        f"`make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, 1 Amul butter, UPI`\n\n"
        f"✏️ *Edit a bill mid-build:*\n"
        f"`drop the butter, make it 6 Maggi`\n\n"
        f"🔍 *Stock query:*\n"
        f"`how much sugar is left?`\n\n"
        f"⚠️ *Low-stock / reorder:*\n"
        f"`what's running out?`\n\n"
        f"📖 *Credit (khata):*\n"
        f"`put ₹500 on Ramesh's credit` • `Ramesh paid ₹300` • `Ramesh's balance?`\n\n"
        f"📊 *Daily close:*\n"
        f"`today's sales?` or `close the day`\n\n"
        f"📄 *Invoice as PDF:*\n"
        f"`send me that bill as a PDF`\n\n"
        f"📈 *Analysis deck:*\n"
        f"`make this week's sales analysis deck`\n\n"
        f"⚙️ *Set a preference:*\n"
        f"`always assume UPI unless I say cash` • `default atta = Aashirvaad 5kg`\n\n"
        f"Type /help for tips, or /reset to start a fresh chat session."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "💡 *Supermarket Ops Capabilities Guide:*\n\n"
        "• *Receive Stock:*\n"
        "  `50 packets of Maggi came in, cost ₹12, MRP ₹14`\n\n"
        "• *Add New Product:*\n"
        "  `new item: Amul Butter 100g, GST 12%, MRP ₹62`\n\n"
        "• *Cut a Bill:*\n"
        "  `make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, 1 Amul butter, UPI`\n\n"
        "• *Edit a Bill Mid-Build:*\n"
        "  `drop the butter, make it 6 Maggi`\n\n"
        "• *Stock Query:*\n"
        "  `how much sugar is left?`\n\n"
        "• *Low-Stock / Reorder:*\n"
        "  `what's running out?`\n\n"
        "• *Credit (Khata Ledger):*\n"
        "  `put ₹500 on Ramesh's credit`\n"
        "  `Ramesh paid ₹300`\n"
        "  `Ramesh's balance?`\n\n"
        "• *Daily Close & Summary:*\n"
        "  `today's sales?` or `close the day`\n\n"
        "• *Invoice as PDF:*\n"
        "  `send me that bill as a PDF` or `give a pdf`\n\n"
        "• *Analysis Deck:*\n"
        "  `make this week's sales analysis deck`\n\n"
        "• *Set a Preference:*\n"
        "  `always assume UPI unless I say cash`\n"
        "  `default atta = Aashirvaad 5kg`\n\n"
        "• *Commands:*\n"
        "  /reset - Clears chat history for a fresh session"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command to clear conversation memory."""
    chat_id = update.effective_chat.id
    CHAT_HISTORIES[chat_id] = []
    await update.message.reply_text(
        "🔄 Conversation history cleared! Persistent settings and preferences in the database remain intact."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process user message through agent control loop."""
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text.strip()
    history = CHAT_HISTORIES.get(chat_id, [])

    # Send typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Open persistent database connection for this turn
    conn = get_connection(DB_PATH)

    try:
        reply_text, updated_history, executed_tools = chat_turn(
            user_text,
            conversation_history=history,
            conn=conn,
            model=GEMINI_MODEL,
            timeout=300,
        )
        CHAT_HISTORIES[chat_id] = updated_history

        # Send text response
        if reply_text:
            await update.message.reply_text(reply_text)

        # Inspect executed tools for generated documents
        for tool in executed_tools:
            tool_name = tool.get("tool", "")
            result_obj = tool.get("result", {})

            # Check if tool produced a file path
            file_path: str | None = None
            if isinstance(result_obj, dict):
                file_path = result_obj.get("result") if isinstance(result_obj.get("result"), str) else None
            elif isinstance(result_obj, str):
                file_path = result_obj

            if file_path and os.path.exists(file_path):
                path_obj = Path(file_path)
                ext = path_obj.suffix.lower()

                if ext == ".pdf":
                    logger.info(f"Sending PDF invoice to chat {chat_id}: {file_path}")
                    with open(file_path, "rb") as doc_file:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=doc_file,
                            filename=path_obj.name,
                            caption="🧾 Here is your GST tax invoice.",
                        )
                elif ext == ".pptx":
                    logger.info(f"Sending PPTX sales deck to chat {chat_id}: {file_path}")
                    with open(file_path, "rb") as doc_file:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=doc_file,
                            filename=path_obj.name,
                            caption="📊 Here is your sales analysis presentation deck.",
                        )

    except OllamaConnectionError as e:
        logger.error(f"Gemini API error: {e}")
        await update.message.reply_text(
            f"⚠️ Could not reach Gemini API.\n\n"
            f"Please ensure `GEMINI_API_KEY` is set correctly in your environment.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Error processing message")
        await update.message.reply_text(f"⚠️ An error occurred: {str(e)}")
    finally:
        conn.close()


from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Supermarket Ops Bot is running OK\n")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress HTTP access logs to keep Telegram bot logs clean


def _keep_alive_pinger() -> None:
    """Periodically ping this service's own URL so Render free tier never goes to sleep."""
    import time
    import urllib.request

    time.sleep(30)
    url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("RENDER_URL")
    if not url:
        return

    logger.info(f"Keep-alive self-pinger active for: {url}")
    while True:
        try:
            time.sleep(600)  # Ping every 10 minutes (Render sleeps at 15 minutes)
            req = urllib.request.Request(f"{url.rstrip('/')}/", headers={"User-Agent": "RenderKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass
        except Exception as exc:
            logger.debug(f"Keep-alive self-ping: {exc}")


def start_health_check_server() -> None:
    """Start a lightweight background HTTP server on $PORT for cloud platforms (e.g. Render)."""
    port_str = os.environ.get("PORT")
    if port_str:
        try:
            port = int(port_str)
            server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            logger.info(f"Render health check HTTP server listening on port {port}")

            # Also start keep-alive thread to keep Render awake
            kp = threading.Thread(target=_keep_alive_pinger, daemon=True)
            kp.start()
        except Exception as exc:
            logger.warning(f"Could not start HTTP health server on port {port_str}: {exc}")


def _anti_spam_guardian(token: str) -> None:
    """Continuously monitor and enforce clean bot description, reverting any spam attempts."""
    import time
    import urllib.request
    import urllib.parse
    import json

    clean_desc = (
        "Supermarket & Kirana Store Ops Assistant. "
        "Manage product inventory, GST billing, customer credit (khata), "
        "and business sales analytics through natural language."
    )
    clean_short = "Supermarket Ops Assistant: billing, stock, khata & GST invoices."
    base = f"https://api.telegram.org/bot{token}"

    while True:
        try:
            time.sleep(120)  # Check every 2 minutes
            req = urllib.request.Request(f"{base}/getMyDescription")
            with urllib.request.urlopen(req, timeout=10) as r:
                curr = json.loads(r.read()).get("result", {}).get("description", "")

            # Detect spam links or keywords
            spam_triggers = ["porn", "sex", "nude", "t.me/", "http", "🔞", "🔥", "nudevista", "genersex", "sexprobot"]
            if any(w in curr.lower() for w in spam_triggers):
                logger.warning(f"Spam description detected in Telegram: {curr!r} — overwriting immediately!")
                data = urllib.parse.urlencode({"description": clean_desc}).encode()
                req_fix = urllib.request.Request(f"{base}/setMyDescription", data=data, method="POST")
                with urllib.request.urlopen(req_fix, timeout=10) as r:
                    pass

                data_short = urllib.parse.urlencode({"short_description": clean_short}).encode()
                req_short = urllib.request.Request(f"{base}/setMyShortDescription", data=data_short, method="POST")
                with urllib.request.urlopen(req_short, timeout=10) as r:
                    pass
                logger.info("Spam wiped and clean kirana description restored.")
        except Exception as exc:
            logger.debug(f"Anti-spam guardian error: {exc}")


async def post_init_setup(application: Application) -> None:
    """Enforce clean kirana assistant description on bot startup."""
    try:
        clean_desc = (
            "Supermarket & Kirana Store Ops Assistant. "
            "Manage product inventory, GST billing, customer credit (khata), "
            "and business sales analytics through natural language."
        )
        await application.bot.set_my_description(description=clean_desc)
        await application.bot.set_my_short_description(
            short_description="Supermarket Ops Assistant: billing, stock, khata & GST invoices."
        )
        logger.info("Enforced clean bot description and short description.")
    except Exception as exc:
        logger.warning(f"Could not enforce bot description on startup: {exc}")


def main() -> None:
    """Run the Telegram Bot application."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN environment variable not set!\n"
            "Please configure TELEGRAM_BOT_TOKEN in your environment."
        )
        sys.exit(1)

    multi_keys = os.environ.get("GEMINI_API_KEYS", "").strip()
    single_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not multi_keys and not single_key:
        print(
            "ERROR: GEMINI_API_KEYS or GEMINI_API_KEY environment variable not set!\n"
            "Get free keys at https://aistudio.google.com/"
        )
        sys.exit(1)

    init_database()
    start_health_check_server()

    # Start automated anti-spam guardian watcher
    guardian_thread = threading.Thread(target=_anti_spam_guardian, args=(token,), daemon=True)
    guardian_thread.start()

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(post_init_setup)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("clear", reset_command))
    app.add_handler(CommandHandler("new", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"Starting Supermarket Ops Telegram Bot (@supermarket_ops_nebula_bot)...")
    print(f"AI Model: {GEMINI_MODEL} (Google Gemini) | DB: {DB_PATH}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
