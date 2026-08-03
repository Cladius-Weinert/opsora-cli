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
                parts.append(f"[{role}] called {fn.get('name', '?')}({fn.get('arguments', '')[:150]}) id={tc.get('id', '?')}")
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
    """Simple truncation fallback when LLM summarization fails.

    Preserves tool-call traceability: assistant tool_calls are rendered with
    function name/args/id, and tool results are tagged with their
    tool_call_id, so the summary keeps the call→result linkage.
    """
    parts = []
    for m in messages:
        role = m.get("role", "?")
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                args = (fn.get("arguments") or "")[:100]
                parts.append(f"[{role}] called {fn.get('name', '?')}({args}) id={tc.get('id', '?')}")
        content = (m.get("content") or "")[:200]
        if content:
            if role == "tool" and m.get("tool_call_id"):
                parts.append(f"[{role}] (tool_call_id={m.get('tool_call_id')}) {content}")
            else:
                parts.append(f"[{role}] {content}")
    text = "\n".join(parts)
    return text[:600] + "… (truncated)" if len(text) > 600 else text

def _tool_call_groups(messages: list[dict]) -> list[list[int]]:
    """Identify atomic tool-call groups in the message list.

    A group is an assistant message carrying ``tool_calls`` plus the run of
    ``tool`` result messages immediately following it. A group must be kept
    or compressed as a unit: compressing the assistant message while keeping
    its tool results (or vice versa) orphans the ``tool_call_id`` and breaks
    the chat-completions contract that every tool message must directly
    follow the assistant tool_calls message it responds to.
    """
    groups: list[list[int]] = []
    current: list[int] | None = None
    for i, m in enumerate(messages):
        role = m.get("role", "")
        if role == "assistant" and m.get("tool_calls"):
            current = [i]
            groups.append(current)
        elif role == "tool" and current is not None:
            current.append(i)
        else:
            current = None
    return groups

def compress(messages: list[dict], token_budget: int = 24000) -> list[dict]:
    """Compress conversation history to fit within token budget.

    Strategy:
    1. Keep system messages intact
    2. Keep last 6 messages intact (most recent context)
    3. Keep all user messages (important context)
    4. Keep tool-call groups atomic: an assistant message with tool_calls and
       its tool results are kept or summarized together, never split, so a
       kept tool result never loses the assistant call that produced it
    5. Summarize old assistant+tool messages via fast LLM
    6. Fallback to truncation if LLM fails
    """
    if not messages:
        return messages
    if _messages_tokens(messages) <= int(token_budget * 0.7):
        return messages

    # Atomic tool-call groups (assistant tool_calls + their tool results)
    groups = _tool_call_groups(messages)
    group_of: dict[int, int] = {}
    for gid, idxs in enumerate(groups):
        for i in idxs:
            group_of[i] = gid

    recent_start = max(0, len(messages) - 6)

    def _keep_single(i: int, m: dict) -> bool:
        role = m.get("role", "")
        return i >= recent_start or role == "user"

    # A tool-call group stays intact if ANY member would be kept (e.g. its
    # result falls inside the recent window); otherwise the whole group is
    # summarized together so no tool_call_id is orphaned.
    group_keep: dict[int, bool] = {
        gid: any(_keep_single(i, messages[i]) for i in idxs)
        for gid, idxs in enumerate(groups)
    }

    # Split into categories
    system_msgs, keep_msgs, compress_msgs = [], [], []
    for i, m in enumerate(messages):
        role = m.get("role", "")
        if role == "system":
            system_msgs.append(m)
        elif i in group_of:
            (keep_msgs if group_keep[group_of[i]] else compress_msgs).append(m)
        elif _keep_single(i, m):
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
