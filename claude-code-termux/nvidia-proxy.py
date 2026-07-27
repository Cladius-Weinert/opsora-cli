#!/usr/bin/env python3
"""Minimal Anthropic Messages API → NVIDIA Integrate proxy for Termux.
No LiteLLM required. Uses only Python stdlib."""
from __future__ import annotations

import json
import os
import sys
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


def to_openai(body: dict) -> dict:
    model = MODEL_MAP.get(body.get("model", ""), body.get("model", "meta/llama-3.1-70b-instruct"))
    if model.startswith("opsora-"):
        model = MODEL_MAP.get(model, "meta/llama-3.1-70b-instruct")
    messages = []
    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            text = str(content)
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": text})
    return {
        "model": model,
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
        "stream": False,
    }


def to_anthropic(nvidia_resp: dict, model: str) -> dict:
    choice = (nvidia_resp.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content", "")
    usage = nvidia_resp.get("usage") or {}
    return {
        "id": nvidia_resp.get("id", "msg_opsora"),
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[opsora-proxy] {fmt % args}\n")

    def _auth_ok(self) -> bool:
        key = self.headers.get("x-api-key") or self.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return key == MASTER_KEY

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in ("/health/liveliness", "/health"):
            self._json(200, {"status": "ok"})
            return
        if self.path == "/v1/models":
            if not self._auth_ok():
                self._json(401, {"error": "unauthorized"})
                return
            models = [{"id": k, "object": "model"} for k in MODEL_MAP]
            self._json(200, {"object": "list", "data": models})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path != "/v1/messages":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        payload = to_openai(body)
        req = Request(
            NVIDIA_URL,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=120) as resp:
                nvidia = json.loads(resp.read())
        except HTTPError as e:
            err = e.read().decode()
            self._json(e.code, {"error": {"message": err[:500]}})
            return
        except URLError as e:
            self._json(502, {"error": {"message": str(e)}})
            return
        self._json(200, to_anthropic(nvidia, body.get("model", "opsora-balanced")))


def main() -> None:
    if not NVIDIA_KEY:
        print("❌ Set NVIDIA_API_KEY", file=sys.stderr)
        sys.exit(1)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"✅ Opsora proxy → NVIDIA on http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
