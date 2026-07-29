#!/usr/bin/env python3
"""Anthropic Messages API → NVIDIA Integrate proxy for Termux (stdlib only).

Verified against NVIDIA Integrate API 2026-07-27.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PORT = int(os.environ.get("OPSORA_PROXY_PORT", "4000"))
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-opsora-local")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MAX_TOKENS_CAP = int(os.environ.get("OPSORA_MAX_TOKENS", "4096"))

# Live-audited model map (latency on Integrate API, 2026-07-27)
MODEL_MAP = {
    "opsora-fast": "meta/llama-3.2-3b-instruct",           # ~0.4s
    "opsora-balanced": "meta/llama-3.1-70b-instruct",      # ~0.5s
    "opsora-power": "meta/llama-3.2-90b-vision-instruct",  # ~0.6s (replaces broken llama-3.3-70b)
    "opsora-coder": "nvidia/nemotron-3-nano-30b-a3b",      # ~0.3s
    "opsora-nemotron": "nvidia/nemotron-3-nano-30b-a3b",   # ~0.3s
    "opsora-mini": "nvidia/nemotron-mini-4b-instruct",     # ~0.2s fastest
    "opsora-mixtral": "meta/llama-3.2-11b-vision-instruct",  # ~0.3s (mixtral EOL)
}

CLAUDE_ALIASES = {
    "claude-sonnet-4-6": "opsora-balanced",
    "claude-sonnet-4-20250514": "opsora-balanced",
    "claude-3-5-sonnet-20241022": "opsora-balanced",
    "claude-haiku-4-5-20251001": "opsora-fast",
    "claude-3-5-haiku-20241022": "opsora-fast",
    "claude-opus-4-20250514": "opsora-power",
    "claude-opus-4-6": "opsora-power",
}

DISCOVERY_MODELS = [
    {"id": "claude-haiku-4-5-20251001", "display_name": "Opsora Fast (Llama 3.2 3B)"},
    {"id": "claude-sonnet-4-6", "display_name": "Opsora Balanced (Llama 3.1 70B)"},
    {"id": "claude-opus-4-20250514", "display_name": "Opsora Power (Llama 3.2 90B)"},
    {"id": "opsora-fast", "display_name": "Fast — Llama 3.2 3B"},
    {"id": "opsora-balanced", "display_name": "Balanced — Llama 3.1 70B"},
    {"id": "opsora-power", "display_name": "Power — Llama 3.2 90B"},
    {"id": "opsora-coder", "display_name": "Coder — Nemotron Nano 30B"},
    {"id": "opsora-mini", "display_name": "Mini — Nemotron 4B (tercepat)"},
]


def resolve_model(name: str) -> str:
    if not name:
        return MODEL_MAP["opsora-fast"]
    if name in MODEL_MAP:
        return MODEL_MAP[name]
    if name in CLAUDE_ALIASES:
        return MODEL_MAP[CLAUDE_ALIASES[name]]
    if name.startswith("opsora-"):
        return MODEL_MAP.get(name, MODEL_MAP["opsora-balanced"])
    if name.startswith("claude-"):
        return MODEL_MAP.get(CLAUDE_ALIASES.get(name, "opsora-balanced"), MODEL_MAP["opsora-balanced"])
    return name


def extract_text(content) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content) if content else ""


def to_openai(body: dict, stream: bool) -> tuple[dict, str]:
    requested = body.get("model", "opsora-fast")
    nvidia_model = resolve_model(requested)
    messages = []
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        if role not in ("user", "assistant", "system"):
            continue
        text = extract_text(msg.get("content", ""))
        if role == "system":
            messages.append({"role": "user", "content": f"[system]\n{text}"})
        else:
            messages.append({"role": role, "content": text})
    max_tokens = min(int(body.get("max_tokens", 1024)), MAX_TOKENS_CAP)
    payload = {
        "model": nvidia_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
        "temperature": 0.7,
    }
    return payload, requested


def to_anthropic(nvidia_resp: dict, model: str) -> dict:
    choice = (nvidia_resp.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content", "")
    usage = nvidia_resp.get("usage") or {}
    return {
        "id": nvidia_resp.get("id", f"msg_{uuid.uuid4().hex[:12]}"),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def sse_event(event_type: str, data: dict) -> bytes:
    return f"event: {event_type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[opsora-proxy] {fmt % args}\n")

    def _auth_ok(self) -> bool:
        auth = self.headers.get("authorization", "")
        bearer = auth.removeprefix("Bearer ").strip() if auth else ""
        key = self.headers.get("x-api-key") or bearer
        return key == MASTER_KEY

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _nvidia_request(self, payload: dict) -> Request:
        return Request(
            NVIDIA_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            method="POST",
        )

    def _stream_nvidia_to_anthropic(self, payload: dict, requested_model: str) -> None:
        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(chunk: bytes) -> None:
            self.wfile.write(chunk)
            self.wfile.flush()

        emit(
            sse_event(
                "message_start",
                {
                    "type": "message_start",
                    "message": {"id": msg_id, "type": "message", "role": "assistant", "model": requested_model, "content": []},
                },
            )
        )
        emit(
            sse_event(
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            )
        )

        output_tokens = 0
        try:
            with urlopen(self._nvidia_request(payload), timeout=180) as resp:
                for raw_line in resp:
                    line = raw_line.decode(errors="replace").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        output_tokens += 1
                        emit(
                            sse_event(
                                "content_block_delta",
                                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": delta}},
                            )
                        )
        except (HTTPError, URLError) as e:
            err = str(e)
            if isinstance(e, HTTPError):
                err = e.read().decode(errors="replace")[:200]
            emit(
                sse_event(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": f"[proxy error] {err}"}},
                )
            )

        emit(sse_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
        emit(
            sse_event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": max(output_tokens, 1)},
                },
            )
        )
        emit(sse_event("message_stop", {"type": "message_stop"}))

    def do_HEAD(self) -> None:
        if self.path.split("?", 1)[0] in ("/", "/health", "/health/liveliness"):
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/health/liveliness", "/health"):
            self._json(200, {"status": "ok", "models": list(MODEL_MAP.keys())})
            return
        if path == "/v1/models":
            if not self._auth_ok():
                self._json(401, {"error": "unauthorized"})
                return
            models = [{"object": "model", **m} for m in DISCOVERY_MODELS]
            self._json(200, {"object": "list", "data": models})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        path = self.path.split("?", 1)[0]
        if path == "/v1/messages/count_tokens":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = json.dumps(body.get("messages", []))
            self._json(200, {"input_tokens": max(1, len(text) // 4)})
            return
        if path != "/v1/messages":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        stream = bool(body.get("stream", False))
        payload, requested_model = to_openai(body, stream=stream)

        if stream:
            self._stream_nvidia_to_anthropic(payload, requested_model)
            return

        try:
            with urlopen(self._nvidia_request(payload), timeout=180) as resp:
                nvidia = json.loads(resp.read())
        except HTTPError as e:
            err = e.read().decode(errors="replace")
            self._json(e.code, {"type": "error", "error": {"type": "api_error", "message": err[:500]}})
            return
        except URLError as e:
            self._json(502, {"type": "error", "error": {"type": "api_error", "message": str(e)}})
            return

        self._json(200, to_anthropic(nvidia, requested_model))


def main() -> None:
    if not NVIDIA_KEY:
        print("❌ Set NVIDIA_API_KEY", file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"✅ Opsora proxy → NVIDIA on http://127.0.0.1:{PORT}", flush=True)
    print(f"   Models: {', '.join(MODEL_MAP.keys())}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
