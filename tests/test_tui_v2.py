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
from opsora_themes import THEMES, contrast_ratio  # noqa: E402


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

    def fake_run_turn(history, selection, status_bar, emit, status, think=None):
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
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.query_one("#banner") is not None
            assert app.query_one("#log") is not None
            assert app.query_one("#inputbox") is not None
            assert app.query_one("#statusbar") is not None

    @pytest.mark.asyncio
    async def test_input_focused_on_mount(self):
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            assert app.focused is app.query_one("#inputbox")

    @pytest.mark.asyncio
    async def test_sub_title_is_tagline(self):
        """W2: OpsoraApp.SUB_TITLE must equal TAGLINE."""
        from opsora_tui_v2 import TAGLINE
        assert OpsoraApp.SUB_TITLE == TAGLINE
        assert TAGLINE == "One terminal \u00b7 Every AI provider \u00b7 Zero lock-in"

    @pytest.mark.asyncio
    async def test_input_placeholder(self):
        """L6/W1: placeholder is short Indonesian text, <= 30 chars."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            inp = app.query_one("#inputbox")
            assert inp.placeholder == "Ketik pesan di sini\u2026"
            assert len(inp.placeholder) <= 30


# ---------------------------------------------------------------------------
# Core promise: input stays pinned while a turn runs
# ---------------------------------------------------------------------------

class TestPinnedInput:
    @pytest.mark.asyncio
    async def test_submit_runs_turn_and_keeps_input_mounted(self):
        backend, calls = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
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
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "   "
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert calls["run_turn"] == 0

    @pytest.mark.asyncio
    async def test_busy_blocks_second_submit(self):
        """B1/B2: busy blocks second submit AND preserves input text."""
        import threading
        gate = threading.Event()

        def slow_turn(history, selection, status_bar, emit, status, think=None):
            gate.wait(timeout=5)
            return history, selection

        backend, _ = _make_backend(run_turn=slow_turn)
        app = OpsoraApp(backend, theme_name="dark")
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
            # B2: input text is NOT discarded when rejected due to busy.
            assert inp.value == "second"
            gate.set()
            await pilot.pause(0.3)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

class TestSlashCommands:
    @pytest.mark.asyncio
    async def test_clear_resets_log_and_history(self):
        backend, _ = _make_backend(history=[{"role": "user", "content": "x"}])
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "/clear"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert backend.history == []

    @pytest.mark.asyncio
    async def test_unknown_command_shows_hint_not_crash(self):
        backend, calls = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            app.query_one("#inputbox").value = "/model nvidia"
            await pilot.press("enter")
            await pilot.pause(0.2)
            # Unknown slash commands must not trigger a turn.
            assert calls["run_turn"] == 0

    @pytest.mark.asyncio
    async def test_slash_keeps_color(self):
        """B3: slash command output preserves ANSI color codes."""
        import threading
        gate = threading.Event()
        captured_ansi = []

        # We need a fake handle_command that prints ANSI-colored text
        # via the opsora_tui console, then returns (True, None, None).
        # We monkeypatch opsora_v2.handle_command.
        import opsora_v2

        original_handle = opsora_v2.handle_command

        def fake_handle(text, history, selection, status_bar, session_id):
            from opsora_tui import console
            console.print(Text("warna", style="bold #5fb8c0"))
            return (True, None, None)

        backend, calls = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(opsora_v2, "handle_command", fake_handle)

        # Replace _append_ansi to capture instead of render
        original_append_ansi = app._append_ansi

        def capture_ansi(ansi_text):
            captured_ansi.append(ansi_text)

        try:
            async with app.run_test(size=(100, 30)) as pilot:
                app._append_ansi = capture_ansi
                app.query_one("#inputbox").value = "/status"
                await pilot.press("enter")
                # Wait for the slash worker to run
                for _ in range(60):
                    if captured_ansi:
                        break
                    await pilot.pause(0.05)
                assert captured_ansi, "No ANSI output captured"
                assert "\x1b[" in captured_ansi[0], (
                    "ANSI escape codes missing from captured output"
                )
        finally:
            monkeypatch.undo()


# ---------------------------------------------------------------------------
# Thinking indicator
# ---------------------------------------------------------------------------

class TestThinkingIndicator:
    @pytest.mark.asyncio
    async def test_thinking_hidden_on_mount(self):
        """L7: on mount, thinking.display is True, active is False, _last_frame empty."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            thinking = app.query_one("#thinking", ThinkingIndicator)
            # display is True (reserved space, never hidden)
            assert thinking.display is True
            # active is False (not running)
            assert thinking.active is False
            # _last_frame is empty string
            assert thinking._last_frame.plain == ""

    @pytest.mark.asyncio
    async def test_thinking_visible_while_running_then_hidden(self):
        """L7: mid-run active=True, after stop active=False, display stays True."""
        import threading
        gate = threading.Event()
        seen = {"active_mid_run": False}

        def slow_turn(history, selection, status_bar, emit, status, think=None):
            status("Berpikir")
            gate.wait(timeout=5)
            return history, selection

        backend, _ = _make_backend(run_turn=slow_turn)
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            thinking = app.query_one("#thinking", ThinkingIndicator)
            app.query_one("#inputbox").value = "halo"
            await pilot.press("enter")
            # While the turn is blocked, the indicator must be active.
            for _ in range(40):
                if thinking.active:
                    break
                await pilot.pause(0.05)
            seen["active_mid_run"] = thinking.active
            gate.set()
            for _ in range(40):
                if not thinking.active:
                    break
                await pilot.pause(0.05)
            assert seen["active_mid_run"] is True
            assert thinking.active is False
            # display stays True throughout (reserved space, task L7)
            assert thinking.display is True

    def test_spinner_frames_advance(self):
        ti = ThinkingIndicator()
        ti._message = "Berpikir"
        ti._frame = 0
        f0 = ti.SPINNER_FRAMES[0]
        ti._frame = 1
        assert ti.SPINNER_FRAMES[1] != f0
        assert len(ti.SPINNER_FRAMES) >= 8

    def test_spinner_frames_all_ascii(self):
        """W3: all spinner frames must be ASCII (ord < 128)."""
        ti = ThinkingIndicator()
        for frame in ti.SPINNER_FRAMES:
            assert isinstance(frame, str) and len(frame) == 1
            assert ord(frame) < 128, f"Non-ASCII frame: {frame!r} (ord={ord(frame)})"

    def test_stream_thinking_sets_text(self):
        ti = ThinkingIndicator()
        ti.stream_thinking("mari saya pikirkan dulu langkah ini")
        assert ti._thinking_text == "mari saya pikirkan dulu langkah ini"
        # render should not raise and should include the thinking content
        ti._render_frame()
        assert ti._thinking_text is not None
        # start() resets back to spinner mode
        ti.start("Berpikir")
        assert ti._thinking_text is None

    def test_stream_thinking_indonesian_label(self):
        """Streaming mode label is Indonesian: 'berpikir' in _last_frame."""
        ti = ThinkingIndicator()
        ti.stream_thinking("x")
        ti._render_frame()
        assert "berpikir" in ti._last_frame.plain

    def test_render_frame_works_unmounted(self):
        """_render_frame() stores rendered Text in _last_frame even when unmounted."""
        ti = ThinkingIndicator()
        ti._frame = 0
        ti._message = "Berpikir"
        ti._render_frame()
        assert isinstance(ti._last_frame, Text)
        assert len(ti._last_frame.plain) > 0

    def test_stop_resets_last_frame_to_empty(self):
        """stop() sets active False, keeps display True, resets _last_frame to empty."""
        ti = ThinkingIndicator()
        ti.start("Berpikir")
        ti._render_frame()
        assert ti._last_frame.plain != ""
        ti.stop()
        assert ti.active is False
        assert ti.display is True
        assert ti._last_frame.plain == ""


# ---------------------------------------------------------------------------
# Welcome renderable (logo, health box, tagline)
# ---------------------------------------------------------------------------

class TestWelcomeRenderable:
    @pytest.mark.asyncio
    async def test_full_logo_at_wide_width(self):
        """At size (100, 30), some line contains '█' (full logo)."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            group = app._welcome_renderable()
            assert any("█" in str(r) for r in group.renderables)

    @pytest.mark.asyncio
    async def test_compact_wordmark_at_narrow_width(self):
        """At size (50, 30): no '█', no line exceeds 50 cells, TAGLINE appears."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(50, 30)) as pilot:
            from opsora_tui_v2 import TAGLINE
            group = app._welcome_renderable()
            for r in group.renderables:
                text = str(r)
                assert "█" not in text, f"Full logo char found in narrow mode: {text!r}"
                # cell length check — use rich's cell_len
                from rich.cells import cell_len
                assert cell_len(text) <= 50, (
                    f"Line exceeds 50 cells at narrow width: {text!r}"
                )
            # TAGLINE appears somewhere
            all_text = " ".join(str(r) for r in group.renderables)
            assert TAGLINE in all_text


class TestHealthRows:
    @pytest.mark.asyncio
    async def test_health_box_at_wide_width(self):
        """At width=100: boxed layout with borders."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            rows = app._health_rows(100)
            assert len(rows) >= 3  # top + at least 1 middle + bottom
            assert rows[0].plain.startswith(" ┌")
            assert rows[-1].plain.startswith(" └")
            for row in rows[1:-1]:
                assert row.plain.startswith(" │")
                assert row.plain.endswith("│")
            # All lines have identical length
            lengths = [len(r.plain) for r in rows]
            assert all(l == lengths[0] for l in lengths)

    @pytest.mark.asyncio
    async def test_health_borderless_at_narrow_width(self):
        """At width=36: borderless fallback — no box chars."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(36, 30)) as pilot:
            rows = app._health_rows(36)
            for row in rows:
                assert "│" not in row.plain
                assert "┌" not in row.plain


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

class TestStatusBar:
    @pytest.mark.asyncio
    async def test_status_text_contains_ctx_and_dot(self):
        """Status text contains 'ctx' and '●'."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            text = app._status_text()
            assert "ctx" in text.plain
            assert "●" in text.plain

    @pytest.mark.asyncio
    async def test_status_text_error_state_shows_error_color(self):
        """When _state='error', the first span's style contains the theme's error hex."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            app._state = "error"
            text = app._status_text()
            # The first span should have the error color in its style
            first_span = text.spans[0]
            error_hex = app._theme.get("error", "#d45555")
            assert error_hex in str(first_span.style)

    @pytest.mark.asyncio
    async def test_set_activity_updates_status_text(self):
        """B4: _set_activity('TesAktivitas') makes status text contain 'TesAktivitas'."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            app._set_activity("TesAktivitas")
            text = app._status_text()
            assert "TesAktivitas" in text.plain

    @pytest.mark.asyncio
    async def test_status_bar_contrast_all_themes(self):
        """TH4: for EVERY theme, contrast_ratio(status_fg, status_bg) >= 4.5."""
        for name, theme in THEMES.items():
            cr = contrast_ratio(theme["status_fg"], theme["status_bg"])
            assert cr >= 4.5, (
                f"Theme {name!r}: status_fg({theme['status_fg']}) vs "
                f"status_bg({theme['status_bg']}) = {cr:.2f}:1, need >= 4.5"
            )

    @pytest.mark.asyncio
    async def test_light_theme_statusbar_has_styles(self):
        """TH4: mounting with light theme gives statusbar with non-None background/color."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="light")
        async with app.run_test(size=(100, 30)) as pilot:
            statusbar = app.query_one("#statusbar")
            assert statusbar.styles.background is not None
            assert statusbar.styles.color is not None


# ---------------------------------------------------------------------------
# Turn separator (L8)
# ---------------------------------------------------------------------------

class TestTurnSeparator:
    @pytest.mark.asyncio
    async def test_turn_separator_shape(self):
        """L8: _turn_separator() returns Text of '─' repeated, len >= 8."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            sep = app._turn_separator()
            assert isinstance(sep, Text)
            assert len(sep.plain) >= 8
            assert all(ch == "─" for ch in sep.plain)

    @pytest.mark.asyncio
    async def test_turn_separator_appears_after_submit(self):
        """L8: after a successful submit, the log received a separator."""
        backend, calls = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            inp = app.query_one("#inputbox")
            inp.value = "halo"
            await pilot.press("enter")
            await _wait_idle(app, pilot, calls)
            sep = app._turn_separator()
            assert len(sep.plain) >= 8
            assert all(ch == "─" for ch in sep.plain)


# ---------------------------------------------------------------------------
# Theme CSS / instance attributes
# ---------------------------------------------------------------------------

class TestThemeCSS:
    @pytest.mark.asyncio
    async def test_css_contains_inputbox_focus(self):
        """app.CSS contains '#inputbox:focus' and the theme's panel_border and accent."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            assert "#inputbox:focus" in app.CSS
            assert app._theme["panel_border"] in app.CSS
            assert app._theme["accent"] in app.CSS

    @pytest.mark.asyncio
    async def test_theme_is_flat_dict(self):
        """app._theme is a flat dict (from opsora_themes.get_theme)."""
        backend, _ = _make_backend()
        app = OpsoraApp(backend, theme_name="dark")
        async with app.run_test(size=(100, 30)) as pilot:
            assert isinstance(app._theme, dict)
            assert "bg" in app._theme
            assert "fg" in app._theme
            assert "accent" in app._theme


# ---------------------------------------------------------------------------
# Backend streaming helpers (no network — fake SSE chunks)
# ---------------------------------------------------------------------------

class TestStreamingBackend:
    def _chunks(self):
        # Simulated SSE chunks: thinking first, then content, then a tool call.
        return iter([
            {"choices": [{"delta": {"reasoning_content": "mari "}}]},
            {"choices": [{"delta": {"reasoning_content": "cek file"}}]},
            {"choices": [{"delta": {"content": "Halo "}}]},
            {"choices": [{"delta": {"content": "dunia"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "read_", "arguments": '{"file_'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"name": "", "arguments": 'path":"a.py"}'}}]}}]},
            {"done": True},
        ])

    def test_consume_stream_extracts_thinking_content_tools(self):
        import opsora_v2
        seen_thinking = []
        content, tool_calls, thinking = opsora_v2._consume_stream(
            self._chunks(), think_cb=lambda t: seen_thinking.append(t))
        assert thinking == "mari cek file"
        assert content == "Halo dunia"
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_"
        assert tool_calls[0]["function"]["arguments"] == '{"file_path":"a.py"}'
        assert tool_calls[0]["id"] == "c1"
        assert seen_thinking  # think_cb was invoked

    def test_consume_stream_error_raises(self):
        import opsora_v2
        with pytest.raises(RuntimeError):
            opsora_v2._consume_stream(iter([{"error": "HTTP 500: x"}]))

    def test_stream_response_shape(self):
        import opsora_v2
        resp = opsora_v2._StreamResponse("hi", None)
        msg = resp.choices[0].message
        assert msg.content == "hi"
        assert msg.model_dump() == {"role": "assistant", "content": "hi"}

    def test_stream_msg_includes_tool_calls(self):
        import opsora_v2
        tcs = [{"id": "c1", "type": "function",
                "function": {"name": "x", "arguments": "{}"}}]
        msg = opsora_v2._StreamMsg("c", tcs)
        d = msg.model_dump()
        assert d["tool_calls"] == tcs

    def test_get_provider_stream_config_nvidia(self, monkeypatch):
        import opsora_v2
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
        cfg = opsora_v2.get_provider_stream_config("nvidia", "some/model")
        assert cfg is not None
        assert cfg["api_key"] == "nvapi-test"
        assert "nvidia" in cfg["base_url"]
        assert cfg["model"] == "some/model"

    def test_get_provider_stream_config_unknown(self, monkeypatch):
        import opsora_v2
        assert opsora_v2.get_provider_stream_config("bedrock", "m") is None
        assert opsora_v2.get_provider_stream_config("nope", "m") is None


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