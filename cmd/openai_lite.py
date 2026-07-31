"""Lightweight OpenAI-compatible client using urllib — no pydantic dependency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class _Function:
    name: str = ""
    arguments: str = "{}"


@dataclass
class _ToolCall:
    id: str = ""
    type: str = "function"
    function: _Function = field(default_factory=_Function)


@dataclass
class _Message:
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[list[_ToolCall]] = None

    def model_dump(self, exclude_none: bool = False) -> dict:
        d = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self.tool_calls
            ]
        elif not exclude_none:
            pass
        return d


@dataclass
class _Choice:
    message: _Message = field(default_factory=_Message)
    index: int = 0
    finish_reason: Optional[str] = None


@dataclass
class _CompletionResponse:
    choices: list[_Choice] = field(default_factory=list)
    id: str = ""
    model: str = ""


class OpenAI:
    """Minimal OpenAI-compatible client using stdlib urllib."""

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1", timeout: int = 40):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.chat = _Chat(self)


class _Chat:
    def __init__(self, client: OpenAI):
        self._client = client
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: OpenAI):
        self._client = client

    def create(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[str] = None,
        parallel_tool_calls: bool = True,
        **kwargs,
    ) -> _CompletionResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
            payload["parallel_tool_calls"] = parallel_tool_calls

        url = f"{self._client.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self._client.api_key}")

        try:
            with urlopen(req, timeout=self._client.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
        except URLError as e:
            raise RuntimeError(f"Connection error: {e.reason}") from e

        return _parse_response(body)


def _parse_response(body: dict) -> _CompletionResponse:
    choices = []
    for c in body.get("choices", []):
        msg_data = c.get("message", {})
        tool_calls = None
        if "tool_calls" in msg_data and msg_data["tool_calls"]:
            tool_calls = []
            for tc in msg_data["tool_calls"]:
                fn = tc.get("function", {})
                tool_calls.append(_ToolCall(
                    id=tc.get("id", ""),
                    type=tc.get("type", "function"),
                    function=_Function(
                        name=fn.get("name", ""),
                        arguments=fn.get("arguments", "{}"),
                    ),
                ))
        msg = _Message(
            role=msg_data.get("role", "assistant"),
            content=msg_data.get("content"),
            tool_calls=tool_calls,
        )
        choices.append(_Choice(
            message=msg,
            index=c.get("index", 0),
            finish_reason=c.get("finish_reason"),
        ))

    return _CompletionResponse(
        choices=choices,
        id=body.get("id", ""),
        model=body.get("model", ""),
    )
