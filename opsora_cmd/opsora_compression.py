"""Opsora Context Compression — Smart summarization of old messages."""
from __future__ import annotations
import json, os
from typing import Any

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4

def _messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across all messages."""
    total = 0
    for m in messages:
        total += _estimate_tokens(m.get("content") or "") + 4
        for tc in m.get("tool_calls", []):
            total += _estimate_tokens(tc.get("function", {}).get("arguments", "")) + 10
    return total

def _get_fast_client():
    """Return (OpenAI client, model_name) using the fastest/cheapest provider."""
    from openai_lite import OpenAI
    dash_key = os.environ.get("DASHSCOPE_API_KEY", "")
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    if dash_key:
        return OpenAI(api_key=dash_key, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", timeout=10), "qwen-turbo"
    if nvidia_key:
        return OpenAI(api_key=nvidia_key, base_url="https://integrate.api.nvidia.com/v1", timeout=10), "meta/llama-3.1-8b-instruct"
    return None, None

_SUMMARIZE_PROMPT = (
    "Summarize these tool calls and results in 2-3 sentences. "
    "Focus on what was done and the key results. "
    "Be concise but preserve important file paths, command outputs, and errors."
)

def _summarize_with_llm(messages: list[dict]) -> str | None:
    """Use a fast LLM to summarize a batch of messages. Returns None on failure."""
    client, model = _get_fast_client()
    if client is None:
        return None
    parts = []
    for m in messages:
        role = m.get("role", "?")
        content = (m.get("content") or "")[:300]
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                parts.append(f"[{role}] called {fn.get('name', '?')}({fn.get('arguments', '')[:150]})")
        if content:
            parts.append(f"[{role}] {content}")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SUMMARIZE_PROMPT},
                      {"role": "user", "content": "\n".join(parts)[:2000]}],
            temperature=0.1, max_tokens=150,
        )
        summary = (resp.choices[0].message.content or "").strip()
        return summary if summary else None
    except Exception:
        return None

def _truncate_fallback(messages: list[dict]) -> str:
    """Simple truncation fallback when LLM summarization fails."""
    parts = []
    for m in messages:
        content = (m.get("content") or "")[:200]
        if content:
            parts.append(f"[{m.get('role', '?')}] {content}")
    text = "\n".join(parts)
    return text[:600] + "… (truncated)" if len(text) > 600 else text

def compress(messages: list[dict], token_budget: int = 24000) -> list[dict]:
    """Compress conversation history to fit within token budget.

    Strategy:
    1. Keep system messages intact
    2. Keep last 6 messages intact (most recent context)
    3. Keep all user messages (important context)
    4. Summarize old assistant+tool messages via fast LLM
    5. Fallback to truncation if LLM fails
    """
    if not messages:
        return messages
    if _messages_tokens(messages) <= int(token_budget * 0.7):
        return messages
    # Split into categories
    system_msgs, keep_msgs, compress_msgs = [], [], []
    recent_start = max(0, len(messages) - 6)
    for i, m in enumerate(messages):
        role = m.get("role", "")
        if role == "system":
            system_msgs.append(m)
        elif i >= recent_start or role == "user":
            keep_msgs.append(m)
        else:
            compress_msgs.append(m)
    if not compress_msgs:
        return messages
    # Try LLM summarization, fallback to truncation
    summary = _summarize_with_llm(compress_msgs) or _truncate_fallback(compress_msgs)
    result: list[dict] = list(system_msgs)
    result.append({"role": "system", "content": f"[Ringkasan konteks sebelumnya]\n{summary}"})
    result.extend(keep_msgs)
    return result
