"""Opsora Streaming Engine — Real SSE token-by-token display.

Parses Server-Sent Events from OpenAI-compatible chat completion endpoints
and renders tokens in real-time using Rich Live display.
"""

from __future__ import annotations

import codecs
import json
from typing import Any, Generator, Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console
from rich.live import Live
from rich.text import Text


def parse_sse_line(line: str) -> Optional[dict]:
    """Parse a single SSE line → dict or None. Handles data:/[DONE]/comments."""
    s = line.strip()
    if not s or s.startswith(":"):
        return None
    if s.startswith("data:"):
        payload = s[5:].strip()
        if payload == "[DONE]":
            return {"done": True}
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
    return None


def iter_sse_events(lines: Iterator[str]) -> Generator[dict, None, None]:
    """Parse an iterable of SSE lines into complete events.

    Consecutive ``data:`` lines are joined with ``\\n`` before JSON parsing, per
    the SSE spec. A blank line terminates the current event. Comment lines
    (``:...``) and non-data lines are ignored. A pending event is flushed at
    EOF even without a trailing blank line. ``[DONE]`` yields ``{"done": True}``
    and stops. Invalid JSON events are skipped.
    """
    data_lines: list[str] = []

    def _flush() -> Generator[dict, None, None]:
        nonlocal data_lines
        if not data_lines:
            return
        joined = "\n".join(data_lines)
        data_lines = []
        if joined == "[DONE]":
            yield {"done": True}
            return
        try:
            yield json.loads(joined)
        except json.JSONDecodeError:
            pass

    for line in lines:
        s = line.strip()
        if not s:
            # blank line — flush pending event
            yield from _flush()
            continue
        if s.startswith(":"):
            # comment line — ignore
            continue
        if s.startswith("data:"):
            payload = s[5:].strip()
            data_lines.append(payload)
            continue
        # non-data, non-blank, non-comment line — ignore (do NOT flush)

    # EOF flush
    yield from _flush()


def accumulate_tool_call(deltas: list[dict]) -> list[dict]:
    """Merge streaming tool_call deltas into complete tool calls.

    Rules:
    - Delta HAS ``index`` (not None) → merge into bucket keyed by that index.
    - Delta has NO index but has a non-empty ``id`` → merge into bucket keyed
      by that id (distinct ids ⇒ distinct calls; a new bucket per new id).
    - Delta has NEITHER index NOR id → merge into the most recently used
      bucket; if no bucket exists yet, create one with a unique key.
    - Return buckets in creation/insertion order.
    """
    calls: dict[str, dict] = {}
    insertion_order: list[str] = []
    last_key: str | None = None
    _counter = 0

    def _next_key() -> str:
        nonlocal _counter
        _counter += 1
        return f"_auto_{_counter}"

    for d in deltas:
        idx = d.get("index")
        tid = d.get("id")

        if idx is not None:
            key = str(idx)
        elif tid:
            key = tid
        elif last_key is not None:
            key = last_key
        else:
            key = _next_key()

        if key not in calls:
            calls[key] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
            insertion_order.append(key)

        e = calls[key]
        if d.get("id"):
            e["id"] = d["id"]
        fn = d.get("function", {})
        if fn.get("name"):
            e["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            e["function"]["arguments"] += fn["arguments"]

        last_key = key

    return [calls[k] for k in insertion_order]


def stream_chat_completion(
    client_config: dict[str, Any],
    messages: list[dict],
    **kwargs,
) -> Generator[dict, None, None]:
    """Make a streaming chat completion request, yielding SSE chunks.

    client_config: {api_key, base_url, model, timeout}
    """
    api_key = client_config.get("api_key", "")
    base_url = client_config.get("base_url", "https://api.openai.com/v1").rstrip("/")
    model = client_config.get("model", "")
    timeout = client_config.get("timeout", 120)

    payload: dict[str, Any] = {
        "model": model, "messages": messages, "stream": True,
        "temperature": kwargs.get("temperature", 0.2),
        "max_tokens": kwargs.get("max_tokens", 4096),
    }
    if kwargs.get("tools"):
        payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]
    payload.update(kwargs.get("extra_body", {}))

    url = f"{base_url}/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "text/event-stream")

    try:
        resp = urlopen(req, timeout=timeout)
    except HTTPError as e:
        yield {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
        return
    except URLError as e:
        yield {"error": f"Koneksi gagal: {e.reason}"}
        return
    except Exception as e:
        yield {"error": f"Error: {e}"}
        return

    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        buf = b""

        def _line_iter() -> Generator[str, None, None]:
            nonlocal buf
            while True:
                raw = resp.read(4096)
                if not raw:
                    break
                buf += raw
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    yield decoder.decode(line_bytes)
            # EOF: flush remaining bytes
            if buf:
                yield decoder.decode(buf, True)

        yield from iter_sse_events(_line_iter())
    finally:
        resp.close()


def render_stream(
    chunks: Generator[dict, None, None],
    console: Console,
) -> tuple[str, list[dict]]:
    """Display streaming tokens via Rich Live. Returns (text, tool_calls)."""
    full_text = ""
    thinking_text = ""
    tool_deltas: list[dict] = []
    is_thinking = False
    cursor = "▌"

    with Live(console=console, refresh_per_second=15, transient=False) as live:
        try:
            for chunk in chunks:
                if "error" in chunk:
                    live.update(Text(f"⚠ {chunk['error']}", style="red"))
                    return full_text, accumulate_tool_call(tool_deltas) if tool_deltas else []
                if chunk.get("done"):
                    break

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})

                # Thinking / reasoning tokens (DashScope: reasoning_content)
                thinking = delta.get("reasoning_content") or delta.get("thinking", "")
                if thinking:
                    thinking_text += thinking
                    is_thinking = True

                content = delta.get("content", "")
                if content:
                    is_thinking = False
                    full_text += content

                tc = delta.get("tool_calls", [])
                if tc:
                    tool_deltas.extend(tc)

                # Build live display
                display = Text()
                if thinking_text and not full_text:
                    display.append("💭 ", style="dim cyan")
                    tlines = thinking_text.split("\n")
                    display.append("\n".join(tlines[-5:]), style="dim italic")
                    display.append(f"\n{cursor}", style="dim")
                elif full_text:
                    if thinking_text:
                        display.append("💭 thinking selesai\n", style="dim cyan")
                    display.append(full_text)
                    display.append(cursor, style="dim")
                else:
                    display.append(cursor, style="dim")
                live.update(display)

        except KeyboardInterrupt:
            pass  # Return partial result on Ctrl+C

    if full_text:
        console.print(full_text, end="\n")
    elif thinking_text:
        console.print(Text(thinking_text, style="dim italic"))

    tool_calls = accumulate_tool_call(tool_deltas) if tool_deltas else []
    return full_text, tool_calls