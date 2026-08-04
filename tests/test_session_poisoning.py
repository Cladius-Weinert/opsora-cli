"""Session-poisoning regression tests.

The conversation history must NEVER end with orphaned tool_calls — an
assistant message carrying tool_calls where some id has no matching
role:"tool" result. Such a history is rejected (or worse, silently
corrupted) by the next provider request, poisoning the whole session.

Every failure path (malformed argument JSON, tool execution raising,
error-recovery crashing) must therefore still append a placeholder tool
result for every tool_call id.

TDD: written against the target contract while the production fixes land
concurrently — red results for not-yet-fixed behaviour are expected.
No network: provider calls, tools and rendering are all patched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_v2


@pytest.fixture(autouse=True)
def _reset_opsora_globals():
    """Clear todos, health cache, lazy clients and the cost tracker so the
    auto-continue heuristics stay quiet and no state leaks between tests."""
    opsora_v2.reset_globals()
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_no_orphaned_tool_calls(history):
    """Every assistant tool_call id must have a role:'tool' answer after it."""
    for i, m in enumerate(history):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            rest = history[i + 1:]
            answered = {t.get("tool_call_id") for t in rest if t.get("role") == "tool"}
            for tc in m["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                assert tc_id in answered, f"orphaned tool_call {tc_id}"


def make_response(content=None, tool_calls=None):
    """Build an OpenAI-shaped response as plain SimpleNamespaces.

    Deliberately has NO ``usage`` attribute so ``extract_usage`` returns {}
    (a MagicMock response would leak a MagicMock usage and break formatting).
    Tool-call entries are plain dicts — the agent loop supports them via
    ``tc.get("function")`` / ``fn.get("name")`` etc.
    """
    dump = {"role": "assistant"}
    if content is not None:
        dump["content"] = content
    if tool_calls:
        dump["tool_calls"] = tool_calls
    msg = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda exclude_none=True: dump,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _selection():
    return opsora_v2.Selection("nvidia", "meta/llama-3.1-8b-instruct")


def _tool_messages(history):
    return [m for m in history if m.get("role") == "tool"]


# ---------------------------------------------------------------------------
# run_agent_turn
# ---------------------------------------------------------------------------

class TestRunAgentTurnPoisoning:
    """The classic (Rich console) agent loop must never orphan tool_calls."""

    def test_malformed_args_json_gets_error_placeholder(self):
        """Invalid argument JSON must produce a tool error placeholder,
        not a crash that leaves the tool_call unanswered."""
        sel = _selection()
        resp_tool = make_response(tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": "{not valid json"},
        }])
        resp_done = make_response(content="Selesai.")
        history = [{"role": "user", "content": "baca file a.py"}]

        with patch("opsora_v2.call_with_fallback",
                   side_effect=[(resp_tool, sel), (resp_done, sel)]), \
             patch("opsora_v2.stream_markdown"), \
             patch("opsora_v2.render_tool_call"), \
             patch("opsora_v2.execute_tool") as mock_exec:
            result_history, _ = opsora_v2.run_agent_turn(history, sel, MagicMock())

        # The broken tool call is answered with an error placeholder…
        call1 = [m for m in _tool_messages(result_history)
                 if m.get("tool_call_id") == "call_1"]
        assert call1, "expected an error placeholder tool result for call_1"
        assert call1[0].get("content")  # non-empty explanation
        # …and the tool itself is never executed with unparseable args.
        mock_exec.assert_not_called()
        assert_no_orphaned_tool_calls(result_history)

    def test_tool_execution_raises_gets_interrupted_placeholders(self):
        """When execute_tool raises, EVERY pending tool_call id still gets a
        '[interrupted]' placeholder result in the same provider round."""
        sel = _selection()
        resp_tool = make_response(tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "call_2", "type": "function",
             "function": {"name": "read_file", "arguments": "{}"}},
        ])
        resp_done = make_response(content="Selesai.")
        history = [{"role": "user", "content": "baca dua file"}]

        with patch("opsora_v2.call_with_fallback",
                   side_effect=[(resp_tool, sel), (resp_done, sel)]), \
             patch("opsora_v2.stream_markdown"), \
             patch("opsora_v2.render_tool_call"), \
             patch("opsora_v2.execute_tool", side_effect=RuntimeError("boom")):
            result_history, _ = opsora_v2.run_agent_turn(history, sel, MagicMock())

        by_id = {m.get("tool_call_id"): m for m in _tool_messages(result_history)}
        assert by_id.get("call_1") is not None, "missing placeholder for call_1"
        assert by_id.get("call_2") is not None, "missing placeholder for call_2"
        assert by_id["call_1"]["content"] == "[interrupted]"
        assert by_id["call_2"]["content"] == "[interrupted]"
        assert_no_orphaned_tool_calls(result_history)

    def test_recovery_crash_does_not_escape_nor_orphan(self):
        """If _try_error_recovery itself crashes (e.g. subprocess timeout),
        the exception must not escape run_agent_turn and the tool_call id
        must still receive a result."""
        sel = _selection()
        resp_tool = make_response(tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"filepath": "a.py"}'},
        }])
        resp_done = make_response(content="Selesai.")
        history = [{"role": "user", "content": "baca file a.py"}]

        with patch("opsora_v2.call_with_fallback",
                   side_effect=[(resp_tool, sel), (resp_done, sel)]), \
             patch("opsora_v2.stream_markdown"), \
             patch("opsora_v2.render_tool_call"), \
             patch("opsora_v2.execute_tool", return_value="Error: command failed"), \
             patch("opsora_v2._try_error_recovery",
                   side_effect=subprocess.TimeoutExpired("cmd", 120)) as mock_recovery:
            # No exception may escape.
            result_history, _ = opsora_v2.run_agent_turn(history, sel, MagicMock())

        mock_recovery.assert_called()
        call1 = [m for m in _tool_messages(result_history)
                 if m.get("tool_call_id") == "call_1"]
        assert call1, "expected a tool result for call_1 despite recovery crash"
        assert_no_orphaned_tool_calls(result_history)


# ---------------------------------------------------------------------------
# run_turn_tui
# ---------------------------------------------------------------------------

class TestRunTurnTuiPoisoning:
    """The TUI agent loop has the same no-orphan guarantee."""

    def test_malformed_args_json_no_orphans(self):
        """Streaming is tried first and fails → falls back to the patched
        call_with_fallback; malformed args must still be answered."""
        sel = _selection()
        resp_tool = make_response(tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {"name": "read_file", "arguments": "{not valid json"},
        }])
        resp_done = make_response(content="Selesai.")
        history = [{"role": "user", "content": "baca file a.py"}]

        with patch("opsora_v2.call_streaming", side_effect=RuntimeError("no streaming")), \
             patch("opsora_v2.call_with_fallback",
                   side_effect=[(resp_tool, sel), (resp_done, sel)]), \
             patch("opsora_v2.execute_tool") as mock_exec:
            result_history, _ = opsora_v2.run_turn_tui(
                history, sel, MagicMock(),
                emit=lambda r: None, status=lambda s: None, think=None)

        call1 = [m for m in _tool_messages(result_history)
                 if m.get("tool_call_id") == "call_1"]
        assert call1, "expected an error placeholder tool result for call_1"
        mock_exec.assert_not_called()
        assert_no_orphaned_tool_calls(result_history)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
