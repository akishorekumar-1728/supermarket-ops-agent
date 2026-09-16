"""
agent/agent.py
==============
Local Ollama Agent with tool-calling control loop.

Features:
- Connects to Ollama via HTTP (/api/chat).
- Sends user messages along with conversation history, system prompt, and tools.
- Parses tool calls requested by the model.
- Executes tool calls against TOOL_FUNCTIONS passing DB connection.
- Passes tool responses back to the model with role='tool'.
- Loops until the model produces a final assistant text response (or max iterations).
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
import urllib.error
import urllib.request
from typing import Any, Callable

from agent.system_prompt import SYSTEM_PROMPT
from agent.tools_registry import TOOL_FUNCTIONS, TOOL_SCHEMAS

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# Default model: qwen3:4b (or fallback to llama3.2:3b / configured model)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")


class OllamaConnectionError(RuntimeError):
    """Raised when communication with Ollama fails."""


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
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_kw:
            args = {k: v for k, v in args.items() if k in sig.parameters}

        if "conn" in sig.parameters or has_var_kw:
            res = func(**args, conn=conn)
        else:
            res = func(**args)
        return {"status": "success", "result": res}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}


def chat_turn(
    user_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    *,
    conn: sqlite3.Connection,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
    max_iterations: int = 10,
    temperature: float = 0.1,
    timeout: float = 300,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Execute a single user turn in the conversation loop:
    1. Append user_message to conversation_history.
    2. Call Ollama /api/chat with tools enabled.
    3. If tool calls are requested, execute them, record tool results, and repeat.
    4. Return (final_assistant_text, updated_conversation_history, executed_tool_calls).

    Parameters:
        user_message: New input message from user.
        conversation_history: Running list of OpenAI/Ollama format message dicts.
        conn: Open sqlite3.Connection for tool execution.
        model: Ollama model name.
        host: Ollama server base URL.
        max_iterations: Maximum tool call roundtrips to prevent infinite loops.
        temperature: Sampling temperature.
        timeout: HTTP request timeout in seconds.

    Returns:
        tuple of (assistant_response_text, new_conversation_history, list_of_executed_tool_calls)
    """
    if conversation_history is None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    else:
        messages = list(conversation_history)
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

    messages.append({"role": "user", "content": user_message})

    user_clean = user_message.strip().lower().rstrip("!.,?")
    GREETINGS = {
        "hi", "hello", "hey", "namaste", "vanakkam", "halo",
        "good morning", "good afternoon", "good evening",
        "who are you", "what can you do", "help", "start", "/start", "/help", "/new"
    }
    if user_clean in GREETINGS:
        greeting_reply = (
            "Namaste! 🙏 I am your Supermarket Operations Assistant.\n\n"
            "Here are some things you can ask me to do:\n"
            "• 📦 Stock Arrivals: '50 packets of Maggi came in, cost ₹12, MRP ₹14'\n"
            "• 🔍 Check Inventory: 'how much sugar is left?' or 'what is low on stock?'\n"
            "• 🧾 Create Bills: 'make a bill: 2kg sugar, 1 atta 5kg, 4 Maggi, UPI'\n"
            "• 📖 Khata Ledger: 'put ₹500 on Ramesh's credit' or 'Ramesh's balance?'\n"
            "• 📄 PDF Invoices: 'send me that bill as a PDF'\n"
            "• 📊 PPTX Sales Reports: 'make this week's sales analysis deck'\n\n"
            "How can I help your store right now?"
        )
        messages.append({"role": "assistant", "content": greeting_reply})
        return greeting_reply, messages, []

    executed_tools: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        payload = {
            "model": model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "stream": False,
            "options": {
                "temperature": temperature,
                "think": False,      # disable qwen3 extended thinking (speeds up tool calls)
            },
        }

        req = urllib.request.Request(
            f"{host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaConnectionError(
                f"Failed to connect to Ollama at {host}: {exc}. "
                f"Please ensure Ollama is running (`ollama serve`)."
            ) from exc

        msg = resp_data.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        # Append assistant message to context
        messages.append(msg)

        if not tool_calls:
            # Final text response received
            content = msg.get("content", "")
            if "didn't specify a function" in content or (content.strip().startswith("{") and '"name":' in content):
                content = (
                    "How can I help you with your supermarket? You can ask me to record new stock, "
                    "prepare a bill, check customer khata balance, or generate sales reports and invoices."
                )
            return content, messages, executed_tools

        # Process all tool calls in this turn
        for tc in tool_calls:
            fn_info = tc.get("function", {})
            fn_name = fn_info.get("name", "")
            fn_args = fn_info.get("arguments", {})

            if isinstance(fn_args, str):
                try:
                    fn_args = json.loads(fn_args)
                except Exception:
                    fn_args = {}

            tool_result = _execute_tool_call(fn_name, fn_args, conn)
            executed_tools.append({
                "tool": fn_name,
                "arguments": fn_args,
                "result": tool_result,
            })

            # Feed tool response back into conversation history
            messages.append({
                "role": "tool",
                "content": json.dumps(tool_result),
            })

    # If max iterations reached, return whatever assistant content was last generated
    last_content = messages[-1].get("content", "") if messages else ""
    return last_content, messages, executed_tools
