"""Tests for opsora_streaming — SSE parsing, event joining, tool-call
accumulation, chunked UTF-8 streaming HTTP, and render_stream partial-result
handling.

These tests target the *contract* of each function. opsora_streaming is being
fixed concurrently, so some may be RED until the fix lands — that is expected
TDD behaviour. No network: ``urlopen`` is patched everywhere.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_streaming


def _config() -> dict:
    return {
        "api_key": "test-key",
        "base_url": "https://fake.example.com/v1",
        "model": "test-model",
        "timeout": 5,
    }


def _console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)


# ============================================================================
# parse_sse_line
# ============================================================================

class TestParseSseLine:
    """parse_sse_line: single-line SSE parsing."""

    def test_data_json(self):
        assert opsora_streaming.parse_sse_line('data: {"a": 1}') == {"a": 1}

    def test_data_done(self):
        assert opsora_streaming.parse_sse_line("data: [DONE]") == {"done": True}

    def test_blank_line(self):
        assert opsora_streaming.parse_sse_line("") is None

    def test_comment_line(self):
        assert opsora_streaming.parse_sse_line(": heartbeat") is None

    def test_non_data_line(self):
        assert opsora_streaming.parse_sse_line("event: message") is None

    def test_invalid_json(self):
        assert opsora_streaming.parse_sse_line("data: {invalid") is None


# ============================================================================
# iter_sse_events
# ============================================================================

class TestIterSseEvents:
    """iter_sse_events: consecutive data: lines are joined before parsing."""

    def test_single_line_events(self):
        lines = ['data: {"a": 1}', "", "data: [DONE]", ""]
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"a": 1}, {"done": True}]

    def test_multi_line_joined_with_newline(self):
        # Contract example: split JSON is reassembled across data: lines.
        lines = ['data: {"a":', 'data: 1}', "", "data: [DONE]", ""]
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"a": 1}, {"done": True}]

    def test_multi_line_three_parts(self):
        lines = [
            'data: {"hello":',
            'data: "world",',
            'data: "ok": 1}',
            "",
        ]
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"hello": "world", "ok": 1}]

    def test_invalid_json_skipped_without_stopping(self):
        lines = ["data: {invalid", "", 'data: {"b": 2}', "", "data: [DONE]", ""]
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"b": 2}, {"done": True}]

    def test_pending_event_flushed_at_eof(self):
        # No trailing blank line — the pending event must still flush.
        lines = ['data: {"a":', 'data: 1}']
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"a": 1}]

    def test_comment_lines_ignored(self):
        lines = [": heartbeat", 'data: {"a": 1}', "", ": keepalive", "data: [DONE]", ""]
        assert list(opsora_streaming.iter_sse_events(lines)) == [{"a": 1}, {"done": True}]

    def test_empty_input(self):
        assert list(opsora_streaming.iter_sse_events([])) == []


# ============================================================================
# accumulate_tool_call
# ============================================================================

class TestAccumulateToolCall:
    """accumulate_tool_call: merge streaming tool_call deltas."""

    def test_same_index_merged(self):
        deltas = [
            {"index": 0, "id": "c1", "function": {"name": "read_", "arguments": '{"file_'}},
            {"index": 0, "function": {"arguments": 'path":"a.py"}'}},
        ]
        result = opsora_streaming.accumulate_tool_call(deltas)
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        assert result[0]["function"]["name"] == "read_"
        assert result[0]["function"]["arguments"] == '{"file_path":"a.py"}'

    def test_two_indices_become_two_calls_in_index_order(self):
        deltas = [
            {"index": 0, "id": "c1", "function": {"name": "a", "arguments": '{"x":'}},
            {"index": 1, "id": "c2", "function": {"name": "b", "arguments": '{"y":'}},
            {"index": 0, "function": {"arguments": '1}'}},
            {"index": 1, "function": {"arguments": '2}'}},
        ]
        result = opsora_streaming.accumulate_tool_call(deltas)
        assert len(result) == 2
        assert result[0]["id"] == "c1"
        assert result[0]["function"]["name"] == "a"
        assert result[0]["function"]["arguments"] == '{"x":1}'
        assert result[1]["id"] == "c2"
        assert result[1]["function"]["name"] == "b"
        assert result[1]["function"]["arguments"] == '{"y":2}'

    def test_no_index_distinct_ids_must_not_merge(self):
        deltas = [
            {"id": "c1", "function": {"name": "a", "arguments": '{"x":'}},
            {"id": "c2", "function": {"name": "b", "arguments": '{"y":'}},
        ]
        result = opsora_streaming.accumulate_tool_call(deltas)
        assert len(result) == 2
        assert result[0]["id"] == "c1"
        assert result[0]["function"]["name"] == "a"
        assert result[0]["function"]["arguments"] == '{"x":'
        assert result[1]["id"] == "c2"
        assert result[1]["function"]["name"] == "b"
        assert result[1]["function"]["arguments"] == '{"y":'

    def test_no_index_no_id_fragment_merges_into_most_recent(self):
        deltas = [
            {"id": "c1", "function": {"name": "a", "arguments": '{"x":'}},
            {"function": {"arguments": '1}'}},
        ]
        result = opsora_streaming.accumulate_tool_call(deltas)
        assert len(result) == 1
        assert result[0]["id"] == "c1"
        assert result[0]["function"]["name"] == "a"
        assert result[0]["function"]["arguments"] == '{"x":1}'

    def test_empty_deltas(self):
        assert opsora_streaming.accumulate_tool_call([]) == []


# ============================================================================
# stream_chat_completion
# ============================================================================

class TestStreamChatCompletion:
    """stream_chat_completion: SSE over chunked reads, multi-byte safe."""

    def test_multi_byte_utf8_content_preserved_exactly(self):
        """Real multi-byte UTF-8 bytes (ensure_ascii=False) must survive."""
        original = "Halo dunia 🌍 — selamat pagi"
        chunk_obj = {"choices": [{"delta": {"content": original}}]}
        sse_bytes = (
            f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n"
            "\n"
            "data: [DONE]\n"
            "\n"
        ).encode("utf-8")

        with patch("opsora_streaming.urlopen", return_value=io.BytesIO(sse_bytes)):
            chunks = list(opsora_streaming.stream_chat_completion(
                _config(), [{"role": "user", "content": "hi"}]))

        content_chunks = [c for c in chunks if "choices" in c]
        assert len(content_chunks) == 1
        got = content_chunks[0]["choices"][0]["delta"]["content"]
        assert got == original
        assert "\ufffd" not in got
        # Stream terminates with the DONE event.
        assert any(c.get("done") for c in chunks)

    def test_large_multi_byte_payload_survives_chunked_reads(self):
        """> 4096 bytes of multi-byte chars forces several read(4096) calls,
        with chunk boundaries landing inside multi-byte sequences."""
        original = "Halo dunia 🌍 — selamat pagi " + "🌍" * 1500
        chunk_obj = {"choices": [{"delta": {"content": original}}]}
        sse_bytes = (
            f"data: {json.dumps(chunk_obj, ensure_ascii=False)}\n"
            "\n"
            "data: [DONE]\n"
            "\n"
        ).encode("utf-8")
        assert len(sse_bytes) > 4096  # sanity: really spans multiple reads

        with patch("opsora_streaming.urlopen", return_value=io.BytesIO(sse_bytes)):
            chunks = list(opsora_streaming.stream_chat_completion(
                _config(), [{"role": "user", "content": "hi"}]))

        content_chunks = [c for c in chunks if "choices" in c]
        assert len(content_chunks) == 1
        got = content_chunks[0]["choices"][0]["delta"]["content"]
        assert "\ufffd" not in got
        assert got == original

    def test_urlopen_urlerror_yields_error(self):
        with patch("opsora_streaming.urlopen", side_effect=URLError("dns fail")):
            chunks = list(opsora_streaming.stream_chat_completion(
                _config(), [{"role": "user", "content": "hi"}]))

        assert chunks
        assert "error" in chunks[0]
        assert "dns fail" in chunks[0]["error"]

    def test_urlopen_httperror_yields_error(self):
        err = HTTPError(
            "https://fake.example.com/v1/chat/completions",
            429, "Too Many Requests", {}, io.BytesIO(b"rate limited"),
        )
        with patch("opsora_streaming.urlopen", side_effect=err):
            chunks = list(opsora_streaming.stream_chat_completion(
                _config(), [{"role": "user", "content": "hi"}]))

        assert len(chunks) == 1
        assert "error" in chunks[0]
        assert "429" in chunks[0]["error"]

    def test_tools_forwarded_into_request_payload(self):
        sse_bytes = b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n'
        with patch("opsora_streaming.urlopen", return_value=io.BytesIO(sse_bytes)) as mock_urlopen:
            list(opsora_streaming.stream_chat_completion(
                _config(), [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "x"}}],
                tool_choice="auto",
            ))

        req: Request = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body.get("stream") is True
        assert "tools" in body
        assert body["tool_choice"] == "auto"


# ============================================================================
# render_stream
# ============================================================================

class TestRenderStream:
    """render_stream: accumulated partial text/tool_calls survive errors."""

    def test_error_returns_accumulated_partial_text(self):
        def gen():
            yield {"choices": [{"delta": {"content": "Halo "}}]}
            yield {"choices": [{"delta": {"content": "dunia"}}]}
            yield {"error": "boom"}

        text, tool_calls = opsora_streaming.render_stream(gen(), _console())
        assert text == "Halo dunia"
        assert tool_calls == []

    def test_error_after_tool_call_delta_returns_that_call(self):
        def gen():
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1",
                 "function": {"name": "read_", "arguments": '{"file_'}}
            ]}}]}
            yield {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": 'path":"a.py"}'}}
            ]}}]}
            yield {"error": "boom"}

        text, tool_calls = opsora_streaming.render_stream(gen(), _console())
        assert text == ""
        assert len(tool_calls) == 1
        assert tool_calls[0]["id"] == "c1"
        assert tool_calls[0]["function"]["name"] == "read_"
        assert tool_calls[0]["function"]["arguments"] == '{"file_path":"a.py"}'

    def test_clean_done_stream_returns_full_text(self):
        def gen():
            yield {"choices": [{"delta": {"content": "Halo "}}]}
            yield {"choices": [{"delta": {"content": "dunia"}}]}
            yield {"done": True}

        text, tool_calls = opsora_streaming.render_stream(gen(), _console())
        assert text == "Halo dunia"
        assert tool_calls == []

    def test_empty_stream_returns_empty(self):
        def gen():
            yield {"done": True}

        text, tool_calls = opsora_streaming.render_stream(gen(), _console())
        assert text == ""
        assert tool_calls == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
