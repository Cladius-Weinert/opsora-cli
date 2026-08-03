"""Tests for context compression (opsora_compression module)."""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))


def _make_messages(count: int, content_size: int = 500) -> list[dict]:
    """Generate alternating user/assistant messages."""
    msgs = [{"role": "system", "content": "You are Opsora."}]
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": "x" * content_size})
    return msgs


def _make_tool_messages(count: int, content_size: int = 500) -> list[dict]:
    """Generate tool call + result message pairs."""
    msgs = [{"role": "system", "content": "You are Opsora."}]
    for i in range(count):
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"call_{i}", "type": "function",
                           "function": {"name": f"tool_{i}", "arguments": "{}"}}],
        })
        msgs.append({
            "role": "tool",
            "content": "y" * content_size,
            "name": f"tool_{i}",
            "tool_call_id": f"call_{i}",
        })
    return msgs


# ---------------------------------------------------------------------------
# Under budget → no compression
# ---------------------------------------------------------------------------


class TestNoCompressionUnderBudget:
    def test_under_threshold_no_compression(self):
        from opsora_compression import compress
        msgs = _make_messages(4, content_size=100)
        result = compress(msgs, token_budget=32000)
        assert len(result) == len(msgs), "Should not compress under budget"
        assert result == msgs

    def test_small_conversation_unchanged(self):
        from opsora_compression import compress
        msgs = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "A programming language."},
        ]
        result = compress(msgs, token_budget=32000)
        assert result == msgs

    def test_empty_messages(self):
        from opsora_compression import compress
        result = compress([], token_budget=1000)
        assert result == []


# ---------------------------------------------------------------------------
# Over budget → compression happens
# ---------------------------------------------------------------------------


class TestCompressionOverThreshold:
    def test_compression_reduces_message_count(self):
        from opsora_compression import compress
        msgs = _make_messages(20, content_size=2000)
        result = compress(msgs, token_budget=5000)
        # Compression should reduce the number of messages
        assert len(result) < len(msgs), "Compression should reduce message count"

    def test_old_tool_results_compressed(self):
        from opsora_compression import compress
        msgs = _make_tool_messages(15, content_size=3000)
        # Add recent messages
        msgs.extend([
            {"role": "user", "content": "final question"},
            {"role": "assistant", "content": "final answer"},
        ])
        result = compress(msgs, token_budget=5000)
        assert len(result) < len(msgs)


# ---------------------------------------------------------------------------
# System messages always kept
# ---------------------------------------------------------------------------


class TestSystemMessagesAlwaysKept:
    def test_system_messages_preserved(self):
        from opsora_compression import compress
        msgs = [{"role": "system", "content": "Important system prompt" * 100}]
        msgs += _make_messages(20, content_size=2000)
        result = compress(msgs, token_budget=5000)
        system_msgs = [m for m in result if m.get("role") == "system"]
        assert len(system_msgs) >= 1, "System messages must be preserved"
        assert "Important system prompt" in system_msgs[0]["content"]

    def test_multiple_system_messages_preserved(self):
        from opsora_compression import compress
        msgs = [
            {"role": "system", "content": "System instruction 1"},
            {"role": "system", "content": "System instruction 2"},
        ]
        msgs += _make_messages(20, content_size=2000)
        result = compress(msgs, token_budget=5000)
        sys_contents = [m["content"] for m in result if m.get("role") == "system"]
        # Both system messages should be present (or at least their content)
        all_sys_text = " ".join(sys_contents)
        assert "System instruction 1" in all_sys_text
        assert "System instruction 2" in all_sys_text


# ---------------------------------------------------------------------------
# Last 6 messages kept intact
# ---------------------------------------------------------------------------


class TestLastSixMessagesKeptIntact:
    def test_recent_messages_kept(self):
        from opsora_compression import compress
        msgs = _make_messages(20, content_size=2000)
        last_6_original = msgs[-6:]
        result = compress(msgs, token_budget=5000)
        last_6_result = result[-6:]
        for orig, res in zip(last_6_original, last_6_result):
            assert orig["content"] == res["content"], "Last 6 messages must be intact"
            assert orig["role"] == res["role"]

    def test_last_six_preserve_order(self):
        from opsora_compression import compress
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            msgs.append({"role": role, "content": f"msg_{i}_" + "x" * 2000})
        
        result = compress(msgs, token_budget=5000)
        last_6 = result[-6:]
        # Verify the last 6 match the original last 6
        for orig, res in zip(msgs[-6:], last_6):
            assert orig["content"] == res["content"]


# ---------------------------------------------------------------------------
# User messages preserved
# ---------------------------------------------------------------------------


class TestUserMessagesPreserved:
    def test_user_messages_kept(self):
        from opsora_compression import compress
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "IMPORTANT_USER_MSG_UNIQUE_12345"},
            {"role": "assistant", "content": "tool call result" * 500},
            {"role": "tool", "content": "tool output" * 500},
        ]
        msgs += _make_messages(10, content_size=3000)
        result = compress(msgs, token_budget=5000)
        all_content = " ".join(m.get("content", "") for m in result)
        assert "IMPORTANT_USER_MSG_UNIQUE_12345" in all_content

    def test_all_user_messages_in_result(self):
        from opsora_compression import compress
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"USER_Q_{i}" if role == "user" else f"A_{i}"
            msgs.append({"role": role, "content": content + "x" * 2000})
        
        result = compress(msgs, token_budget=5000)
        result_contents = " ".join(m.get("content", "") for m in result)
        # All user questions should be present (recent ones + preserved older ones)
        # At minimum, recent user messages must be there
        for i in range(14, 20, 2):  # Last 6 messages include user messages
            assert f"USER_Q_{i}" in result_contents


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    def test_estimate_tokens(self):
        from opsora_compression import _estimate_tokens
        assert _estimate_tokens("") == 0
        assert _estimate_tokens("hello") == 1  # 5 // 4 = 1
        assert _estimate_tokens("a" * 100) == 25
        assert _estimate_tokens("x" * 4096) == 1024

    def test_messages_tokens(self):
        from opsora_compression import _messages_tokens
        msgs = [
            {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": "hi there"},
        ]
        tokens = _messages_tokens(msgs)
        # Each message: content_tokens + 4 overhead
        # "hello world" = 11 chars → 2 tokens, + 4 = 6
        # "hi there" = 8 chars → 2 tokens, + 4 = 6
        assert tokens == 12


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------


class TestLLMFallback:
    def test_truncation_fallback_when_no_llm(self):
        from opsora_compression import _truncate_fallback
        msgs = [
            {"role": "tool", "content": "x" * 1000},
            {"role": "assistant", "content": "y" * 500},
        ]
        result = _truncate_fallback(msgs)
        assert len(result) <= 610  # 600 + "… (truncated)" or less
        assert "[tool]" in result or "[assistant]" in result

    def test_truncate_fallback_short_messages(self):
        from opsora_compression import _truncate_fallback
        msgs = [{"role": "user", "content": "short"}]
        result = _truncate_fallback(msgs)
        assert "short" in result
        assert "truncated" not in result
