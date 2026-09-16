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
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

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
            model=OLLAMA_MODEL,
            host=OLLAMA_HOST,
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
        logger.error(f"Ollama connection error: {e}")
        await update.message.reply_text(
            f"⚠️ Could not reach local Ollama server at `{OLLAMA_HOST}`.\n\n"
            f"Please ensure Ollama is running (`ollama serve`) and model `{OLLAMA_MODEL}` is pulled.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Error processing message")
        await update.message.reply_text(f"⚠️ An error occurred: {str(e)}")
    finally:
        conn.close()


def main() -> None:
    """Run the Telegram Bot application."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN environment variable not set!\n"
            "Please configure TELEGRAM_BOT_TOKEN in your .env file or environment."
        )
        sys.exit(1)

    init_database()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("clear", reset_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"Starting Supermarket Ops Telegram Bot (@supermarket_ops_nebula_bot)...")
    print(f"Model: {OLLAMA_MODEL} | Host: {OLLAMA_HOST} | DB: {DB_PATH}")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
