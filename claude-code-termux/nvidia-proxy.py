#!/usr/bin/env python3
"""Anthropic Messages API → NVIDIA Integrate proxy for Termux (stdlib only)."""
from __future__ import annotations

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PORT = int(os.environ.get("OPSORA_PROXY_PORT", "4000"))
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY", "")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "sk-opsora-local")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

MODEL_MAP = {
    "opsora-balanced": "meta/llama-3.1-70b-instruct",
    "opsora-fast": "meta/llama-3.1-8b-instruct",
    "opsora-power": "meta/llama-3.3-70b-instruct",
    "opsora-coder": "meta/llama-3.1-70b-instruct",
    "opsora-mixtral": "mistralai/mixtral-8x22b-v0.1",
    "opsora-nemotron": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
}

# Claude Code built-in aliases → opsora profiles
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
    {"id": "claude-sonnet-4-6", "display_name": "Opsora Balanced (Llama 3.1 70B)"},
    {"id": "claude-haiku-4-5-20251001", "display_name": "Opsora Fast (Llama 3.1 8B)"},
    {"id": "claude-opus-4-20250514", "display_name": "Opsora Power (Llama 3.3 70B)"},
    {"id": "opsora-balanced", "display_name": "Opsora Balanced"},
    {"id": "opsora-fast", "display_name": "Opsora Fast"},
    {"id": "opsora-power", "display_name": "Opsora Power"},
    {"id": "opsora-coder", "display_name": "Opsora Coder"},
]


def resolve_model(name: str) -> str:
    if not name:
        return MODEL_MAP["opsora-balanced"]
    if name in MODEL_MAP:
        return MODEL_MAP[name]
    if name in CLAUDE_ALIASES:
        return MODEL_MAP[CLAUDE_ALIASES[name]]
    if name.startswith("opsora-"):
        return MODEL_MAP.get(name, MODEL_MAP["opsora-balanced"])
    if name.startswith("claude-"):
        return MODEL_MAP.get(CLAUDE_ALIASES.get(name, "opsora-balanced"), MODEL_MAP["opsora-balanced"])
    return name


def to_openai(body: dict) -> tuple[dict, str]:
    requested = body.get("model", "opsora-balanced")
    nvidia_model = resolve_model(requested)
    messages = []
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            text = str(content)
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": text})
    payload = {
        "model": nvidia_model,
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
        "stream": bool(body.get("stream", False)),
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


def stream_anthropic(model: str, text: str, input_tokens: int = 0, output_tokens: int = 0) -> list[bytes]:
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    chunks: list[bytes] = []
    chunks.append(
        sse_event(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                },
            },
        )
    )
    chunks.append(
        sse_event(
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        )
    )
    if text:
        chunks.append(
            sse_event(
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            )
        )
    chunks.append(sse_event("content_block_stop", {"type": "content_block_stop", "index": 0}))
    chunks.append(
        sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": output_tokens or max(1, len(text.split()))},
            },
        )
    )
    chunks.append(sse_event("message_stop", {"type": "message_stop"}))
    return chunks


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

    def _stream(self, chunks: list[bytes]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(chunk)
            self.wfile.flush()

    def do_HEAD(self) -> None:
        if self.path in ("/", "/health", "/health/liveliness"):
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/health/liveliness", "/health"):
            self._json(200, {"status": "ok"})
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
        payload, requested_model = to_openai(body)
        stream = bool(body.get("stream", False))
        # Always call NVIDIA non-stream; convert to Anthropic SSE locally.
        payload["stream"] = False

        req = Request(
            NVIDIA_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=180) as resp:
                nvidia = json.loads(resp.read())
        except HTTPError as e:
            err = e.read().decode()
            if stream:
                self._stream(
                    stream_anthropic(
                        requested_model,
                        f"[Opsora proxy error {e.code}] {err[:300]}",
                    )
                )
                return
            self._json(e.code, {"type": "error", "error": {"type": "api_error", "message": err[:500]}})
            return
        except URLError as e:
            if stream:
                self._stream(stream_anthropic(requested_model, f"[Opsora proxy error] {e}"))
                return
            self._json(502, {"type": "error", "error": {"type": "api_error", "message": str(e)}})
            return

        result = to_anthropic(nvidia, requested_model)
        if stream:
            text = result["content"][0]["text"]
            out_tok = result["usage"]["output_tokens"]
            self._stream(stream_anthropic(requested_model, text, output_tokens=out_tok))
            return
        self._json(200, result)


def main() -> None:
    if not NVIDIA_KEY:
        print("❌ Set NVIDIA_API_KEY", file=sys.stderr)
        sys.exit(1)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"✅ Opsora proxy → NVIDIA on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
