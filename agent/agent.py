"""
agent/agent.py
==============
Google Gemini Agent with function-calling control loop and multi-key rotation.

Features:
- Connects to Google Gemini API (gemini-2.0-flash, free tier).
- Supports multiple API keys via GEMINI_API_KEYS (comma-separated).
  Automatically rotates to the next key on quota/rate-limit errors.
- Sends user messages along with conversation history, system prompt, and tools.
- Parses function calls requested by the model.
- Executes function calls against TOOL_FUNCTIONS passing DB connection.
- Passes function responses back to the model with role='tool'.
- Loops until the model produces a final assistant text response (or max iterations).
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
import threading
import time
from typing import Any, Callable

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

from agent.system_prompt import SYSTEM_PROMPT
from agent.tools_registry import TOOL_FUNCTIONS, TOOL_SCHEMAS
from agent.fast_path import try_fast_path

COMPACT_SYSTEM_PROMPT = """You are an Indian kirana supermarket Ops Assistant.
Call appropriate tools for real data, billing, stock, and khata.
Never invent data. Use ₹ for rupees. Reply concisely like a practical assistant."""

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
# Auto-migrate deprecated 2.0-flash or 2.5-flash to working 3.6-flash
if GEMINI_MODEL in ("gemini-2.0-flash", "gemini-2.5-flash"):
    GEMINI_MODEL = "gemini-3.6-flash"

# Backward-compatibility alias for test suites
OLLAMA_MODEL = GEMINI_MODEL
OLLAMA_HOST = ""

# ── Multi-key rotation support ────────────────────────────────────────────────
def _load_api_keys() -> list[str]:
    """
    Load Gemini API keys from environment.
    Supports two formats:
      - GEMINI_API_KEYS=key1,key2,key3,...   (multiple keys, comma-separated)
      - GEMINI_API_KEY=key1                  (single key fallback)
    """
    multi = os.environ.get("GEMINI_API_KEYS", "").strip()
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = os.environ.get("GEMINI_API_KEY", "").strip()
    if single:
        return [single]
    return []

_API_KEYS: list[str] = _load_api_keys()
_key_index: int = 0
_key_lock = threading.Lock()


def _get_current_key() -> str:
    """Return the currently active API key."""
    with _key_lock:
        if not _API_KEYS:
            return ""
        return _API_KEYS[_key_index % len(_API_KEYS)]


def _rotate_key() -> str:
    """Rotate to the next API key and return it."""
    global _key_index
    with _key_lock:
        if not _API_KEYS:
            return ""
        _key_index = (_key_index + 1) % len(_API_KEYS)
        new_key = _API_KEYS[_key_index]
    import logging
    logging.getLogger("supermarket_ops_bot").warning(
        f"Gemini quota hit — rotated to key #{_key_index + 1}/{len(_API_KEYS)}"
    )
    return new_key


def _is_quota_error(exc: Exception) -> bool:
    """Check if the exception is a quota/rate-limit error."""
    msg = str(exc).lower()
    return any(kw in msg for kw in [
        "quota", "rate limit", "resource_exhausted", "429",
        "too many requests", "ratelimitexceeded",
    ])


# ── Tool schema builder ───────────────────────────────────────────────────────
class OllamaConnectionError(RuntimeError):
    """Raised when communication with Gemini API fails (kept for backward compat)."""


def _build_gemini_tools() -> list[Tool]:
    """Convert Ollama-style tool schemas into Gemini FunctionDeclaration objects."""
    declarations = []
    for schema in TOOL_SCHEMAS:
        fn = schema.get("function", {})
        params_raw = fn.get("parameters", {})

        properties = {}
        for prop_name, prop_info in params_raw.get("properties", {}).items():
            prop_type = prop_info.get("type", "string").upper()
            type_map = {
                "STRING": "STRING", "NUMBER": "NUMBER", "INTEGER": "INTEGER",
                "BOOLEAN": "BOOLEAN", "ARRAY": "ARRAY", "OBJECT": "OBJECT",
            }
            gemini_type = type_map.get(prop_type, "STRING")
            properties[prop_name] = {
                "type": gemini_type,
                "description": prop_info.get("description", ""),
            }

        gemini_params: dict[str, Any] = {"type": "OBJECT", "properties": properties}
        if params_raw.get("required"):
            gemini_params["required"] = params_raw["required"]

        declarations.append(
            FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=gemini_params,
            )
        )

    return [Tool(function_declarations=declarations)]


# Build tools once at module load
_GEMINI_TOOLS = _build_gemini_tools()


# ── Tool execution ────────────────────────────────────────────────────────────
def _execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Execute a single tool function by name, passing the DB connection."""
    func: Callable[..., Any] | None = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return {"error": f"Unknown tool: {tool_name}"}

    args = dict(arguments)
    try:
        sig = inspect.signature(func)
        has_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if not has_var_kw:
            args = {k: v for k, v in args.items() if k in sig.parameters}
        if "conn" in sig.parameters or has_var_kw:
            res = func(**args, conn=conn)
        else:
            res = func(**args)
        return {"status": "success", "result": res}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}


# ── History conversion ────────────────────────────────────────────────────────
def _history_to_gemini(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal OpenAI-style message list to Gemini conversation history format."""
    gemini_history = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "system":
            i += 1
            continue

        if role == "user":
            gemini_history.append({
                "role": "user",
                "parts": [{"text": msg.get("content", "")}],
            })
            i += 1

        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                parts = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    parts.append({
                        "function_call": {
                            "name": fn.get("name", ""),
                            "args": args,
                        }
                    })
                gemini_history.append({"role": "model", "parts": parts})
            else:
                content = msg.get("content", "")
                if content:
                    gemini_history.append({
                        "role": "model",
                        "parts": [{"text": content}],
                    })
            i += 1

        elif role == "tool":
            content = msg.get("content", "")
            try:
                result_data = json.loads(content)
            except Exception:
                result_data = {"result": content}

            fn_name = "unknown_tool"
            if gemini_history and gemini_history[-1].get("role") == "model":
                for p in gemini_history[-1].get("parts", []):
                    if "function_call" in p:
                        fn_name = p["function_call"].get("name", fn_name)
                        break

            gemini_history.append({
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": fn_name,
                        "response": result_data,
                    }
                }],
            })
            i += 1
        else:
            i += 1

    return gemini_history


# ── Main chat turn ────────────────────────────────────────────────────────────
def chat_turn(
    user_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    *,
    conn: sqlite3.Connection,
    model: str = GEMINI_MODEL,
    host: str = "",          # unused, kept for API compatibility
    max_iterations: int = 10,
    temperature: float = 0.1,
    timeout: float = 300,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Execute a single user turn in the conversation loop using Gemini API.
    Automatically rotates to the next API key on quota errors.

    Returns: (final_assistant_text, updated_conversation_history, executed_tool_calls)
    """
    if not _API_KEYS:
        raise OllamaConnectionError(
            "No Gemini API key found. Set GEMINI_API_KEYS (comma-separated) or "
            "GEMINI_API_KEY in your environment. "
            "Get free keys at https://aistudio.google.com/"
        )

    if conversation_history is None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT}
        ]
    else:
        messages = list(conversation_history)
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": COMPACT_SYSTEM_PROMPT})

    messages.append({"role": "user", "content": user_message})

    # Fast path: greetings — no LLM needed
    user_clean = user_message.strip().lower().rstrip("!.,?")
    GREETINGS = {
        "hi", "hello", "hey", "namaste", "vanakkam", "halo",
        "good morning", "good afternoon", "good evening",
        "who are you", "what can you do", "help", "start", "/start", "/help", "/new"
    }
    if user_clean in GREETINGS:
        greeting_reply = (
            "Namaste! 🙏 I am your Supermarket Operations Assistant.\n\n"
            "Here is what you can ask me to do:\n"
            "• 📦 *Receive stock:* '50 packets of Maggi came in, cost ₹12, MRP ₹14'\n"
            "• 🏷️ *Add product:* 'new item: Amul Butter 100g, GST 12%, MRP ₹62'\n"
            "• 🧾 *Cut a bill:* 'make a bill: 2kg sugar, 1 Aashirvaad atta 5kg, 4 Maggi, UPI'\n"
            "• ✏️ *Edit bill:* 'drop the butter, make it 6 Maggi'\n"
            "• 🔍 *Stock query:* 'how much sugar is left?'\n"
            "• ⚠️ *Low-stock:* 'what\\'s running out?'\n"
            "• 📖 *Khata credit:* 'put ₹500 on Ramesh\\'s credit' • 'Ramesh paid ₹300'\n"
            "• 📊 *Daily close:* 'today\\'s sales?' or 'close the day'\n"
            "• 📄 *Invoice PDF:* 'send me that bill as a PDF'\n"
            "• 📈 *Analysis deck:* 'make this week\\'s sales analysis deck'\n"
            "• ⚙️ *Set preference:* 'always assume UPI unless I say cash'\n\n"
            "How can I help your store right now?"
        )
        messages.append({"role": "assistant", "content": greeting_reply})
        return greeting_reply, messages, []

    # Zero-latency fast path for common kirana operations (< 5ms)
    fast_res = try_fast_path(user_message, conn=conn)
    if fast_res is not None:
        reply_text, tools_called = fast_res
        messages.append({"role": "assistant", "content": reply_text})
        return reply_text, messages, tools_called

    # Convert history for Gemini (exclude last user message — sent fresh below)
    history_for_gemini = _history_to_gemini(messages[:-1])
    executed_tools: list[dict[str, Any]] = []

    # Try with key rotation on quota errors
    max_key_attempts = len(_API_KEYS)
    for attempt in range(max_key_attempts):
        api_key = _get_current_key()
        genai.configure(api_key=api_key)

        gemini_model_obj = genai.GenerativeModel(
            model_name=model,
            system_instruction=COMPACT_SYSTEM_PROMPT,
            tools=_GEMINI_TOOLS,
        )
        chat = gemini_model_obj.start_chat(history=history_for_gemini)

        try:
            response = chat.send_message(
                user_message,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.0,
                    max_output_tokens=300,
                ),
            )
            break  # success — exit key rotation loop
        except Exception as exc:
            if _is_quota_error(exc) and attempt < max_key_attempts - 1:
                _rotate_key()
                time.sleep(0.5)
                continue
            raise OllamaConnectionError(
                f"Gemini API error after trying {attempt + 1} key(s): {exc}"
            ) from exc

    # Agentic tool-call loop
    for _ in range(max_iterations):
        fn_calls = []
        for part in response.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                fn_calls.append(part.function_call)

        if not fn_calls:
            final_text = response.text.strip() if response.text else ""
            if not final_text:
                final_text = (
                    "How can I help you with your supermarket? You can ask me to record "
                    "new stock, prepare a bill, check customer khata balance, or generate "
                    "sales reports and invoices."
                )
            messages.append({"role": "assistant", "content": final_text})
            return final_text, messages, executed_tools

        # Execute all function calls
        function_responses = []
        for fn_call in fn_calls:
            fn_name = fn_call.name
            fn_args = dict(fn_call.args) if fn_call.args else {}

            tool_result = _execute_tool_call(fn_name, fn_args, conn)
            executed_tools.append({
                "tool": fn_name,
                "arguments": fn_args,
                "result": tool_result,
            })

            function_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fn_name,
                        response=tool_result,
                    )
                )
            )

        # Send tool results back to Gemini (with key rotation on quota)
        for attempt in range(max_key_attempts):
            try:
                response = chat.send_message(function_responses)
                break
            except Exception as exc:
                if _is_quota_error(exc) and attempt < max_key_attempts - 1:
                    # Rebuild chat session with new key
                    new_key = _rotate_key()
                    genai.configure(api_key=new_key)
                    gemini_model_obj = genai.GenerativeModel(
                        model_name=model,
                        system_instruction=COMPACT_SYSTEM_PROMPT,
                        tools=_GEMINI_TOOLS,
                    )
                    chat = gemini_model_obj.start_chat(history=history_for_gemini)
                    time.sleep(0.5)
                    continue
                raise OllamaConnectionError(
                    f"Gemini API error during tool result: {exc}"
                ) from exc

    last_text = response.text.strip() if response.text else ""
    messages.append({"role": "assistant", "content": last_text})
    return last_text, messages, executed_tools
