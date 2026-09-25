"""
llm_provider.py — Unified LLM provider with automatic fallback.

Priority (whichever key is set in .env):
  1. Claude  (ANTHROPIC_API_KEY) — best tool-use quality
  2. Groq    (GROQ_API_KEY)      — free, no credit card, 14,400 req/day
  3. Gemini  (GEMINI_API_KEY)    — free, Google account only

All providers return the same normalised format so chatbot.py doesn't
need to know which one is running. History is always stored in Anthropic
format internally; it's converted on-the-fly for OpenAI-compatible providers.

Free API keys:
  Groq   → https://console.groq.com          (no credit card)
  Gemini → https://aistudio.google.com       (Google account)
  Claude → https://console.anthropic.com     (paid)
"""
from __future__ import annotations

import json
import os
from typing import Any


# ─── Format converters ───────────────────────────────────────────────────────

def _anthropic_tools_to_openai(tools: list) -> list:
    """Convert Anthropic tool schema → OpenAI function-calling schema."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result


def _anthropic_history_to_openai(history: list, system_prompt: str) -> list:
    """
    Convert Anthropic-format message history → OpenAI-format messages.

    Anthropic format (what we store internally):
      {"role": "user",      "content": "text"}
      {"role": "assistant", "content": [{"type":"tool_use","id":"x","name":"...","input":{}}]}
      {"role": "user",      "content": [{"type":"tool_result","tool_use_id":"x","content":"..."}]}
      {"role": "assistant", "content": [{"type":"text","text":"..."}]}

    OpenAI format (what Groq/Gemini expect):
      {"role": "system",    "content": system_prompt}
      {"role": "user",      "content": "text"}
      {"role": "assistant", "content": null, "tool_calls": [...]}
      {"role": "tool",      "tool_call_id": "x", "content": "..."}
      {"role": "assistant", "content": "..."}
    """
    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        role    = msg["role"]
        content = msg["content"]

        # Plain text message
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue

        # List of content blocks
        if role == "assistant":
            text_parts  = [b["text"] for b in content if b.get("type") == "text"]
            tool_blocks = [b for b in content if b.get("type") == "tool_use"]

            out: dict[str, Any] = {"role": "assistant"}
            out["content"] = "\n".join(text_parts) if text_parts else None

            if tool_blocks:
                out["tool_calls"] = [
                    {
                        "id":       b["id"],
                        "type":     "function",
                        "function": {
                            "name":      b["name"],
                            "arguments": json.dumps(b.get("input", {})),
                        },
                    }
                    for b in tool_blocks
                ]
            messages.append(out)

        elif role == "user":
            results = [b for b in content if b.get("type") == "tool_result"]
            texts   = [b for b in content if b.get("type") == "text"]

            if results:
                # Each tool result is a separate "tool" message in OpenAI format
                for r in results:
                    raw = r.get("content", "")
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": r.get("tool_use_id", ""),
                        "content":      raw if isinstance(raw, str) else json.dumps(raw),
                    })
            elif texts:
                messages.append({"role": "user", "content": "\n".join(b["text"] for b in texts)})
            else:
                messages.append({"role": "user", "content": str(content)})

    return messages


# ─── Normalised response ─────────────────────────────────────────────────────

def _norm(stop_reason: str, text: str | None, tool_calls: list, raw=None, is_error: bool = False) -> dict:
    return {
        "stop_reason": stop_reason,   # "end_turn" | "tool_use"
        "text":        text,
        "tool_calls":  tool_calls,    # [{"id":..., "name":..., "input":{...}}]
        "_raw":        raw,           # Anthropic raw content blocks (or None)
        "is_error":    is_error,      # explicit flag — callers should check this,
                                       # not guess from text prefixes (there are
                                       # several different error message shapes
                                       # below, not all of which share a prefix)
    }


# ─── Provider ────────────────────────────────────────────────────────────────

class LLMProvider:
    """
    Auto-selects the best available LLM for tool-use.

    Usage:
        provider = LLMProvider()
        result = provider.create_message(
            messages=history,
            anthropic_tools=ANTHROPIC_TOOLS,
            system=system_prompt,
        )
        # result["stop_reason"]  → "end_turn" | "tool_use"
        # result["text"]         → assistant text (or None)
        # result["tool_calls"]   → [{"id":..., "name":..., "input":{...}}]
    """

    # Models to use per provider
    GROQ_MODEL    = os.getenv("GROQ_MODEL",   "openai/gpt-oss-120b")
    GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    CLAUDE_MODEL  = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    CLAUDE_FALLBACK = os.getenv("CLAUDE_FALLBACK_MODEL", "claude-3-5-haiku-latest")

    def __init__(self):
        self.provider, self.display_name = self._detect()

    def _detect(self) -> tuple[str, str]:
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic", f"Claude ({self.CLAUDE_MODEL})"
        if os.getenv("GROQ_API_KEY"):
            return "groq",      f"GPT-OSS 120B via Groq (free)"
        if os.getenv("GEMINI_API_KEY"):
            return "gemini",    f"Gemini 2.0 Flash via Google (free)"
        return "none", "No provider configured"

    @property
    def is_configured(self) -> bool:
        return self.provider != "none"

    def not_configured_message(self) -> str:
        return (
            "No LLM API key found in .env.\n\n"
            "Free options (no credit card needed):\n"
            "  GROQ_API_KEY   = ...   →  https://console.groq.com\n"
            "                            Free forever, 14,400 req/day, tool-use supported\n\n"
            "  GEMINI_API_KEY = ...   →  https://aistudio.google.com\n"
            "                            Free with Google account, generous limits\n\n"
            "Paid:\n"
            "  ANTHROPIC_API_KEY = ...  →  https://console.anthropic.com"
        )

    # ── Unified entry point ───────────────────────────────────────────────────

    def create_message(
        self,
        *,
        messages: list,
        anthropic_tools: list,
        system: str,
        max_tokens: int = 1024,
    ) -> dict:
        if self.provider == "anthropic":
            return self._call_anthropic(messages, anthropic_tools, system, max_tokens)
        if self.provider == "groq":
            return self._call_openai_compat(
                messages, anthropic_tools, system, max_tokens,
                base_url="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY", ""),
                model=self.GROQ_MODEL,
            )
        if self.provider == "gemini":
            return self._call_openai_compat(
                messages, anthropic_tools, system, max_tokens,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=os.getenv("GEMINI_API_KEY", ""),
                model=self.GEMINI_MODEL,
            )
        return _norm("end_turn", self.not_configured_message(), [], is_error=True)

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def _call_anthropic(self, messages, tools, system, max_tokens) -> dict:
        try:
            import anthropic
        except ImportError:
            return _norm("end_turn", "anthropic package not installed. Run: pip install anthropic", [], is_error=True)

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        model  = self.CLAUDE_MODEL

        for attempt in range(2):
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                break
            except Exception as exc:
                if attempt == 0 and "model" in str(exc).lower() and model != self.CLAUDE_FALLBACK:
                    model = self.CLAUDE_FALLBACK
                    continue
                return _norm("end_turn", f"Claude API error: {exc}", [], is_error=True)

        tool_calls, text = [], None
        for block in resp.content:
            t = getattr(block, "type", "")
            if t == "text":
                text = block.text
            elif t == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "input": dict(block.input or {})})

        stop = getattr(resp, "stop_reason", "end_turn")
        return _norm(stop, text, tool_calls, raw=resp.content)

    # ── OpenAI-compatible (Groq + Gemini) ────────────────────────────────────

    def _call_openai_compat(self, messages, anthropic_tools, system, max_tokens, base_url, api_key, model) -> dict:
        try:
            from openai import OpenAI
        except ImportError:
            return _norm("end_turn", "openai package not installed. Run: pip install openai", [], is_error=True)

        client       = OpenAI(base_url=base_url, api_key=api_key)
        oai_tools    = _anthropic_tools_to_openai(anthropic_tools)
        oai_messages = _anthropic_history_to_openai(messages, system)

        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=oai_messages,
                tools=oai_tools,
                tool_choice="auto",
            )
        except Exception as exc:
            return _norm("end_turn", f"{self.display_name} error: {exc}", [], is_error=True)

        choice  = resp.choices[0]
        message = choice.message
        text    = message.content  # may be None when there are tool calls

        tool_calls = []
        if choice.finish_reason == "tool_calls" and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    inp = json.loads(tc.function.arguments)
                except Exception:
                    inp = {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "input": inp})

        stop = "tool_use" if tool_calls else "end_turn"
        return _norm(stop, text, tool_calls)
