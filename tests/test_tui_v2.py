"""Tests for the Textual TUI (opsora_tui_v2) — the persistent, pinned-input UI.

These run headless via Textual's ``run_test`` pilot, so no real terminal or
network is needed. They verify the core promise of the new UI: the input box
stays mounted (pinned at the bottom) while a turn runs and output is appended
to the scrolling log above it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

from rich.text import Text  # noqa: E402

from opsora_tui_v2 import OpsoraApp, TuiBackend  # noqa: E402
from opsora_tui_v2 import ThinkingIndicator  # noqa: E402
from opsora_tui import get_provider_health, _gradient_steps  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeSelection:
    provider = "nvidia"
    model = "meta/llama-3.1-8b-instruct"


class _FakeStatusBar:
    provider = "nvidia"
    model = "meta/llama-3.1-8b-instruct"
    context_pct = 5
    session_tokens = 100


def _make_backend(run_turn=None, history=None):
    calls = {"run_turn": 0}

    def fake_run_turn(history, selection, status_bar, emit, status):
        calls["run_turn"] += 1
        status("Berpikir…")
        emit(Text("Halo dari Opsora."))
        status("")
        return history, selection

    return TuiBackend(
        run_turn=run_turn or fake_run_turn,
        history=history if history is not None else [],
        selection=_FakeSelection(),
        status_bar=_FakeStatusBar(),
        health=get_provider_health(),
        tools_count=25,
        provider="nvidia",
        model="meta/llama-3.1-8b-instruct",
        approval="full-auto",
    ), calls


async def _wait_idle(app, pilot, calls, timeout_loops=60):
    for _ in range(timeout_loops):
        if calls["run_turn"] > 0 and not app._busy:
            return
        await pilot.pause(0.05)


# ---------------------------------------------------------------------------
# Layout / mount
# ---------------------------------------------------------------------------

class TestMount:
    @pytest.mark.asyncio
    async def test_all_widgets_mounted(self):
        backend, _ = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.query_one("#banner") is not None
            assert app.query_one("#log") is not None
            assert app.query_one("#inputbox") is not None
            assert app.query_one("#statusbar") is not None

    @pytest.mark.asyncio
    async def test_input_focused_on_mount(self):
        backend, _ = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.focused is app.query_one("#inputbox")


# ---------------------------------------------------------------------------
# Core promise: input stays pinned while a turn runs
# ---------------------------------------------------------------------------

class TestPinnedInput:
    @pytest.mark.asyncio
    async def test_submit_runs_turn_and_keeps_input_mounted(self):
        backend, calls = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            inp = app.query_one("#inputbox")
            inp.value = "halo"
            await pilot.press("enter")
            await _wait_idle(app, pilot, calls)

            assert calls["run_turn"] == 1
            # User message captured in history.
            assert backend.history[0]["content"] == "halo"
            # Input is cleared but STILL mounted (pinned) and refocused.
            inp2 = app.query_one("#inputbox")
            assert inp2.value == ""
            assert app.focused is inp2

    @pytest.mark.asyncio
    async def test_empty_submit_ignored(self):
        backend, calls = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "   "
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert calls["run_turn"] == 0

    @pytest.mark.asyncio
    async def test_busy_blocks_second_submit(self):
        # A run_turn that never returns until we release it.
        import threading
        gate = threading.Event()

        def slow_turn(history, selection, status_bar, emit, status):
            gate.wait(timeout=5)
            return history, selection

        backend, _ = _make_backend(run_turn=slow_turn)
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            inp = app.query_one("#inputbox")
            inp.value = "first"
            await pilot.press("enter")
            await pilot.pause(0.2)
            # While busy, a second submit should be rejected (history unchanged).
            inp.value = "second"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert len([m for m in backend.history if m.get("role") == "user"]) == 1
            gate.set()
            await pilot.pause(0.3)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

class TestSlashCommands:
    @pytest.mark.asyncio
    async def test_clear_resets_log_and_history(self):
        backend, _ = _make_backend(history=[{"role": "user", "content": "x"}])
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "/clear"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert backend.history == []

    @pytest.mark.asyncio
    async def test_unknown_command_shows_hint_not_crash(self):
        backend, calls = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "/model nvidia"
            await pilot.press("enter")
            await pilot.pause(0.2)
            # Unknown slash commands must not trigger a turn.
            assert calls["run_turn"] == 0


# ---------------------------------------------------------------------------
# Thinking indicator
# ---------------------------------------------------------------------------

class TestThinkingIndicator:
    @pytest.mark.asyncio
    async def test_thinking_hidden_on_mount(self):
        backend, _ = _make_backend()
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            thinking = app.query_one("#thinking", ThinkingIndicator)
            assert thinking.display is False

    @pytest.mark.asyncio
    async def test_thinking_visible_while_running_then_hidden(self):
        import threading
        gate = threading.Event()
        seen = {"visible_mid_run": False}

        def slow_turn(history, selection, status_bar, emit, status):
            status("Berpikir")
            gate.wait(timeout=5)
            return history, selection

        backend, _ = _make_backend(run_turn=slow_turn)
        app = OpsoraApp(backend)
        async with app.run_test(size=(100, 30)) as pilot:
            thinking = app.query_one("#thinking", ThinkingIndicator)
            app.query_one("#inputbox").value = "halo"
            await pilot.press("enter")
            # While the turn is blocked, the indicator must be visible.
            for _ in range(40):
                if thinking.display:
                    break
                await pilot.pause(0.05)
            seen["visible_mid_run"] = thinking.display
            gate.set()
            for _ in range(40):
                if not thinking.display:
                    break
                await pilot.pause(0.05)
            assert seen["visible_mid_run"] is True
            assert thinking.display is False

    def test_spinner_frames_advance(self):
        ti = ThinkingIndicator()
        ti._message = "Berpikir"
        ti._frame = 0
        f0 = ti.SPINNER_FRAMES[0]
        ti._frame = 1
        assert ti.SPINNER_FRAMES[1] != f0
        assert len(ti.SPINNER_FRAMES) >= 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_gradient_steps_count_and_format(self):
        steps = _gradient_steps("#00ffff", 6)
        assert len(steps) == 6
        assert all(s.startswith("#") and len(s) == 7 for s in steps)

    def test_gradient_steps_invalid_input(self):
        assert _gradient_steps("nothex", 3) == ["nothex"] * 3

    def test_provider_health_shape(self):
        health = get_provider_health()
        assert len(health) >= 4
        for h in health:
            assert set(h.keys()) >= {"name", "key", "models", "available"}
            assert isinstance(h["available"], bool)

    def test_darken(self):
        assert OpsoraApp._darken("#ffffff", 0.5) == "#7f7f7f"
        assert OpsoraApp._darken("bad", 0.5) == "#101020"
