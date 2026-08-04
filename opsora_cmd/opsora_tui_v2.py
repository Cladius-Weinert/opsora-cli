"""Opsora TUI v2 — persistent Textual interface (Qwen Code / ink style).

Layout model: ONE full-screen app that never tears down. The input box is a
widget pinned to the bottom; assistant output streams into a scrollable
``RichLog`` above it. Because the input widget stays mounted and focused for
the whole session, the on-screen keyboard on Android/Termux does not disappear
mid-run — the exact behaviour the classic (prompt_toolkit + Rich Live) path
cannot provide.

This module is presentation-only. It does NOT import ``opsora_v2`` at module
level (avoids a circular import); all backend behaviour is injected through
:class:`TuiBackend`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, RichLog, Static

from opsora_themes import get_theme, load_theme_preference


# ---------------------------------------------------------------------------
# Shared wording / layout constants
# ---------------------------------------------------------------------------

# One canonical tagline (task W2): same casing in the banner and welcome box.
TAGLINE = "One terminal · Every AI provider · Zero lock-in"

# Below this width the full 55-char ASCII logo and boxed provider health do
# not fit (Android/Termux phones run ~50-70 cols) — use compact fallbacks.
NARROW_WIDTH = 60

# Full block-art logo (55 chars wide). Rendered with an accent gradient.
LOGO_LINES = [
    " ██████╗ ██╗   ██╗ ██████╗ ██████╗ ███████╗███╗   ██╗",
    " ██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔══██╗██╔════╝████╗  ██║",
    " ██████╔╝ ╚████╔╝ ██║     ██████╔╝█████╗  ██╔██╗ ██║",
    " ██╔═══╝   ╚██╔╝  ██║     ██╔═══╝ ██╔══╝  ██║╚██╗██║",
    " ██║        ██║  ███████╗██║     ███████╗██║ ╚████║",
    " ╚═╝        ╚═╝  ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝",
]


# ---------------------------------------------------------------------------
# Backend contract (filled in by opsora_v2 before App.run)
# ---------------------------------------------------------------------------

@dataclass
class TuiBackend:
    """Everything the TUI needs from the engine, injected by opsora_v2.

    ``run_turn`` signature:
        run_turn(history, selection, status_bar, emit, status) -> (history, selection)
    where ``emit(renderable)`` appends to the output log and
    ``status(text)`` updates the activity line. Both are invoked from the
    worker thread; the app marshals them onto the UI thread.
    """

    run_turn: Callable[..., Any]
    history: list
    selection: Any
    status_bar: Any
    health: List[dict] = field(default_factory=list)
    tools_count: int = 0
    provider: str = ""
    model: str = ""
    approval: str = "full-auto"
    session_id: str = ""
    on_turn_done: Optional[Callable[[list, Any], None]] = None


# ---------------------------------------------------------------------------
# Thinking / loading indicator (Qwen Code style)
# ---------------------------------------------------------------------------

class ThinkingIndicator(Static):
    """Animated spinner shown while a turn is running.

    Stays mounted just above the input box for the whole session. When idle
    it renders a single empty line (reserved space), so showing/hiding the
    spinner content never reflows the scrolling log (task L7). ``active``
    tracks whether a turn is running.

    Spinner frames are plain ASCII (task W3): the braille characters used
    before (U+2800 block) render as tofu boxes on many Android monospace
    fonts. The message updates live (e.g. "Berpikir" → "Menjalankan
    read_file") so the user always sees what Opsora is doing.
    """

    # ASCII-safe line spinner (duplicated to 8 frames for smooth timing).
    SPINNER_FRAMES = ["|", "/", "-", "\\", "|", "/", "-", "\\"]

    def __init__(self, accent: str = "#5fb8c0", dim: str = "#8b93a7",
                 fg: str = "#e6e6f0", **kwargs: Any):
        super().__init__("", **kwargs)
        self._accent = accent
        self._dim = dim
        self._fg = fg
        self._frame = 0
        self._message = "Berpikir"
        self._thinking_text: Optional[str] = None
        self._active = False
        self._timer = None
        self._last_frame: Text = Text("")

    @property
    def active(self) -> bool:
        """True while a turn is running (spinner/thinking content shown)."""
        return self._active

    def start(self, message: str = "Berpikir") -> None:
        self._message = message
        self._thinking_text = None  # back to spinner mode
        self._frame = 0
        self._active = True
        self._render_frame()
        self._ensure_timer()
        self.display = True

    def set_message(self, message: str) -> None:
        self._message = message
        self._thinking_text = None
        self._render_frame()

    def stream_thinking(self, text: str) -> None:
        """Show streaming reasoning/thinking content (Qwen Code style)."""
        self._thinking_text = text
        self._active = True
        self._ensure_timer()
        self.display = True
        self._render_frame()

    def _ensure_timer(self) -> None:
        # set_interval needs a mounted widget / running loop; guard so calls on
        # a not-yet-mounted widget (e.g. unit tests) don't raise.
        if self._timer is None:
            try:
                self._timer = self.set_interval(0.09, self._advance)
            except Exception:
                self._timer = None

    def stop(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        self._thinking_text = None
        self._active = False
        # Stay mounted with one empty line so the log above does not reflow
        # (task L7).
        self._last_frame = Text("")
        try:
            self.update(self._last_frame)
        except Exception:
            pass

    def on_unmount(self) -> None:
        self.stop()

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        self._render_frame()

    def _render_frame(self) -> None:
        frame = self.SPINNER_FRAMES[self._frame]
        t = Text()
        if self._thinking_text:
            # Streaming thinking: spinner + label + last lines + cursor.
            t.append(f" {frame} ", style=f"bold {self._accent}")
            t.append("berpikir", style=f"italic {self._dim}")
            lines = [ln for ln in self._thinking_text.strip().split("\n")]
            shown = "\n".join(lines[-5:])
            t.append("\n " + shown, style=f"italic {self._dim}")
            t.append(" _", style=f"{self._accent}")
        else:
            t.append(f" {frame} ", style=f"bold {self._accent}")
            t.append(self._message, style=f"{self._fg}")
            t.append(" …", style=f"{self._dim}")
        self._last_frame = t
        try:
            self.update(t)
        except Exception:
            # Not mounted yet (e.g. unit test) — content set lazily on mount.
            pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class OpsoraApp(App):
    """Persistent Opsora TUI: scrolling output on top, pinned input below."""

    TITLE = "Opsora"
    SUB_TITLE = TAGLINE  # W2: one canonical tagline, exposed to Textual too

    # Structural layout only — colors come from the active Opsora theme via
    # the instance-level ``self.CSS`` built in ``__init__`` (Textual has no
    # focus/blur messages in 8.x, so the focus-aware input border must live
    # in CSS as ``#inputbox:focus``).
    CSS = """
    #banner {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    #log {
        height: 1fr;
        border: none;
        padding: 0 1;
    }
    #thinking {
        height: auto;
        max-height: 8;
        margin: 0 1;
        padding: 0 1;
    }
    #inputbox {
        dock: bottom;
        margin: 0 1;
        height: 3;
    }
    #statusbar {
        dock: bottom;
        height: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("ctrl+c", "interrupt", "Interrupt"),
        ("ctrl+d", "quit_maybe", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    def __init__(self, backend: TuiBackend, theme_name: Optional[str] = None):
        self.backend = backend
        self._theme_name = theme_name or load_theme_preference()
        self._theme = get_theme(self._theme_name)
        self._busy = False
        # Status-bar state (task B4: actually rendered now).
        self._activity = "Siap"
        self._state = "ok"  # ok | busy | warn | error → colored status dot
        # Instance CSS carries theme colors; must exist before App.__init__
        # builds the stylesheet.
        self.CSS = self._theme_css(self._theme)
        super().__init__()

    @staticmethod
    def _theme_css(t: dict) -> str:
        """Theme-colored CSS fragment (input border states, task L6).

        Idle input: muted ``panel_border``. Focused input: ``accent``.
        Inline programmatic styles would outrank CSS, so the input border is
        owned exclusively here.
        """
        panel_border = t.get("panel_border", t.get("border", "#4a4a5f"))
        accent = t.get("accent", "#5fb8c0")
        return (
            f"#inputbox {{ border: round {panel_border}; }}\n"
            f"#inputbox:focus {{ border: round {accent}; }}\n"
        )

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        t = self._theme
        yield Static(self._banner_renderable(), id="banner")
        yield RichLog(id="log", markup=True, wrap=True, highlight=True)
        yield ThinkingIndicator(
            accent=t.get("accent", "#5fb8c0"),
            dim=t.get("dim", "#8b93a7"),
            fg=t.get("fg", "#e6e6f0"),
            id="thinking")
        yield Input(
            # Short on purpose: 60-char placeholders truncate on phone
            # widths (task L6/W1).
            placeholder="Ketik pesan di sini…",
            id="inputbox")
        yield Static(self._status_text(), id="statusbar")

    def on_mount(self) -> None:
        self._apply_widget_styles()
        # Thinking indicator stays mounted (one reserved empty line when
        # idle, task L7); only its content toggles.
        self.query_one("#inputbox", Input).focus()
        log = self.query_one("#log", RichLog)
        log.write(self._welcome_renderable())
        log.write(Text(""))

    # -- theming (programmatic, version-safe) --------------------------------

    def _apply_widget_styles(self) -> None:
        t = self._theme
        bg = t.get("bg", "#1a1a2e")
        fg = t.get("fg", "#e6e6f0")
        accent = t.get("accent", "#5fb8c0")
        # Explicit theme pairs win; _darken fallbacks keep old behaviour for
        # themes that lack the key.
        panel = t.get("panel", self._darken(bg, 0.25))
        # Task TH4: light themes used to compute status bg = darken(white)
        # = the same gray as the dim text → invisible bar. Themes now carry
        # an explicit, contrast-checked status_bg/status_fg pair.
        status_bg = t.get("status_bg", self._darken(bg, 0.4))
        status_fg = t.get("status_fg", t.get("dim", "#8b93a7"))

        try:
            self.screen.styles.background = bg
        except Exception:
            pass

        banner = self.query_one("#banner", Static)
        banner.styles.color = fg
        banner.styles.background = bg

        log = self.query_one("#log", RichLog)
        log.styles.background = bg
        log.styles.color = fg

        inp = self.query_one("#inputbox", Input)
        inp.styles.background = panel
        inp.styles.color = fg
        # Border intentionally NOT set here: the theme CSS owns it so the
        # ``#inputbox:focus`` rule can swap muted → accent (task L6).
        inp.styles.caret_color = accent

        thinking = self.query_one("#thinking", ThinkingIndicator)
        thinking.styles.background = bg

        status = self.query_one("#statusbar", Static)
        status.styles.background = status_bg
        status.styles.color = status_fg

    @staticmethod
    def _darken(hex_color: str, amount: float) -> str:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) != 6:
            return "#101020"
        try:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
        except ValueError:
            return "#101020"
        f = max(0.0, 1.0 - amount)
        return "#{:02x}{:02x}{:02x}".format(int(r * f), int(g * f), int(b * f))

    # -- renderables ---------------------------------------------------------

    def _banner_renderable(self) -> RenderableType:
        """Banner wordmark + tagline + bottom rule (task L4).

        The rule separates banner from log; ``Rule`` adapts to any width,
        so nothing hardcodes a column count.
        """
        t = self._theme
        accent = t.get("accent", "#5fb8c0")
        secondary = t.get("secondary", t.get("dim", "#8b93a7"))
        border = t.get("border", "#4a4a5f")
        line1 = Text()
        line1.append("OPSORA", style=f"bold {accent}")
        line2 = Text(TAGLINE, style=f"italic {secondary}")
        return Group(line1, line2, Rule(style=border))

    def _health_rows(self, width: int) -> List[Text]:
        """Provider health as a CLOSED box with dynamic width (task L1).

        Every row gets the same cell width, both side borders are drawn,
        and the model list is truncated to fit. On very narrow widths the
        box degrades to borderless dot rows instead of overflowing.
        """
        t = self._theme
        success = t.get("success", "#6abf69")
        error = t.get("error", "#d45555")
        dim = t.get("dim", "#8b93a7")
        border = t.get("border", "#4a4a5f")
        health = self.backend.health
        rows: List[Text] = []
        if not health:
            return rows

        name_w = max(len(h.get("name", "")) for h in health) + 2
        # Row shape: " │ " + "● " + name + " " + models + " │"
        overhead = 3 + 2 + 1 + 2
        models_w = min(34, width - overhead - name_w - 2)

        if models_w < 12:  # too narrow for a box — borderless fallback
            for h in health:
                row = Text(" ")
                if h.get("available"):
                    row.append("● ", style=f"bold {success}")
                    row.append(h.get("name", ""), style="bold")
                else:
                    row.append("● ", style=error)
                    row.append(h.get("name", ""), style=dim)
                rows.append(row)
            return rows

        total_w = overhead + name_w + models_w
        title = " Provider Health "
        top = Text(" ┌─", style=border)
        top.append(title, style=f"bold {dim}")
        top.append("─" * max(0, total_w - len(top.plain) - 1), style=border)
        top.append("┐", style=border)
        rows.append(top)

        for h in health:
            models = ", ".join(h.get("models", [])[:3])
            if len(models) > models_w:
                models = models[: models_w - 1] + "…"
            row = Text(" │ ", style=border)
            if h.get("available"):
                row.append("● ", style=f"bold {success}")
                row.append(f"{h.get('name', ''):<{name_w}}", style="bold")
            else:
                row.append("● ", style=error)
                row.append(f"{h.get('name', ''):<{name_w}}", style=dim)
            row.append(" ", style=border)
            row.append(f"{models:<{models_w}}", style=dim)
            row.append(" │", style=border)
            rows.append(row)

        bottom = Text(" └", style=border)
        bottom.append("─" * (total_w - 3), style=border)
        bottom.append("┘", style=border)
        rows.append(bottom)
        return rows

    def _welcome_renderable(self) -> RenderableType:
        t = self._theme
        accent = t.get("accent", "#5fb8c0")
        secondary = t.get("secondary", t.get("dim", "#8b93a7"))
        dim = t.get("dim", "#8b93a7")
        b = self.backend
        try:
            width = self.size.width
        except Exception:
            width = 80

        lines: List[Text] = []
        if width >= NARROW_WIDTH:
            # Full block-art logo with a gradient that stays readable: the
            # fade floor was raised (task L3, see opsora_tui._gradient_steps).
            from opsora_tui import _gradient_steps
            for line, color in zip(LOGO_LINES, _gradient_steps(accent, len(LOGO_LINES))):
                lines.append(Text(line, style=f"bold {color}"))
        else:
            # Compact wordmark for ~50-col phone terminals (task L2): the
            # 55-char art would wrap and shatter under RichLog(wrap=True).
            mark = Text()
            mark.append(" ● ", style=f"bold {accent}")
            mark.append("OPSORA", style=f"bold {accent}")
            lines.append(mark)
        lines.append(Text(" " + TAGLINE, style=f"italic {secondary}"))
        lines.append(Text(""))

        lines.extend(self._health_rows(width))
        lines.append(Text(""))
        # Info + help lines must fit phone widths too (task L2): drop the
        # provider prefix and "mode" wording when the full line overflows.
        info = f" {b.tools_count} tools · {b.provider}:{b.model} · mode {b.approval}"
        if len(info) > width - 2:
            model_short = b.model.split("/")[-1] if "/" in b.model else b.model
            info = f" {b.tools_count} tools · {model_short} · {b.approval}"
        lines.append(Text(info, style=dim))
        lines.append(Text(
            " /help bantuan · /status detail · Ctrl+L bersihkan",
            style=dim))
        return Group(*lines)

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        return f"{n / 1000:.1f}k" if n >= 1000 else str(n)

    def _status_text(self) -> RenderableType:
        """Status bar: state dot · model · ctx · mode · tokens · activity.

        The dot reflects real state instead of a hardcoded green (task L5);
        activity comes from ``_activity`` (task B4); segments are dropped
        tail-first when the terminal is too narrow to fit them.
        """
        t = self._theme
        accent = t.get("accent", "#5fb8c0")
        dim = t.get("dim", "#8b93a7")
        success = t.get("success", "#6abf69")
        warning = t.get("warning", "#d4a843")
        error = t.get("error", "#d45555")
        b = self.backend
        sb = b.status_bar
        try:
            ctx = sb.context_pct
        except Exception:
            ctx = 0
        try:
            tokens = int(getattr(sb, "session_tokens", 0) or 0)
        except Exception:
            tokens = 0

        ctx_left = max(0, 100 - ctx)
        ctx_color = success if ctx_left > 40 else warning if ctx_left > 15 else error
        dot_style = {
            "ok": f"bold {success}",
            "busy": f"bold {accent}",
            "warn": f"bold {warning}",
            "error": f"bold {error}",
        }.get(self._state, f"bold {success}")

        segments: List[tuple] = [
            (" ● ", dot_style),
            (f"{b.provider}:{b.model}", f"bold {accent}"),
            (f" · ctx {ctx_left}%", ctx_color),
            (f" · {b.approval}", dim),
        ]
        optional: List[tuple] = []
        if tokens > 0:
            optional.append((f" · {self._fmt_tokens(tokens)} tok", dim))
        if self._activity:
            activity = self._activity
            if len(activity) > 24:
                activity = activity[:23] + "…"
            optional.append((f" · {activity}", dim))

        try:
            max_w = self.size.width - 2
        except Exception:
            max_w = 78
        txt = Text()
        for text, style in segments:
            txt.append(text, style=style)
        for text, style in optional:
            if len(txt.plain) + len(text) > max_w:
                break
            txt.append(text, style=style)
        return txt

    # -- input handling ------------------------------------------------------

    def _turn_separator(self) -> Text:
        """Subtle full-width rule between turns (task L8)."""
        sep = self._theme.get("separator", "#2a2a3e")
        try:
            w = max(8, self.size.width - 4)
        except Exception:
            w = 60
        return Text("─" * w, style=sep)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            event.input.value = ""
            return

        if text.startswith("/"):
            # Only clear the input when the command was actually accepted;
            # a busy-rejected command keeps its text (task B2).
            if self._handle_slash(text):
                event.input.value = ""
            return

        if self._busy:
            self._append(Text("Masih memproses, tunggu sebentar…",
                              style=f"{self._theme.get('warning', '#d4a843')}"))
            return

        # Accepted: clear BEFORE doing work, and claim the busy flag on the
        # UI thread NOW — not inside the worker — so two fast Enters can
        # never both pass the guard (task B1).
        event.input.value = ""
        self._busy = True
        self._state = "busy"
        self._activity = "Memproses"

        log = self.query_one("#log", RichLog)
        accent = self._theme.get("accent", "#5fb8c0")
        log.write(Text(""))
        log.write(self._turn_separator())
        umsg = Text()
        # ">" instead of ❯ (U+276F renders as tofu on some Android fonts,
        # task W3).
        umsg.append("> ", style=f"bold {accent}")
        umsg.append(text, style="bold")
        log.write(umsg)
        self.backend.history.append({"role": "user", "content": text})

        # Auto-select model per turn (mirrors classic REPL behaviour).
        try:
            from opsora_v2 import auto_select_model
            self.backend.selection = auto_select_model(text)
            self.backend.status_bar.provider = self.backend.selection.provider
            self.backend.status_bar.model = self.backend.selection.model
            self.backend.provider = self.backend.selection.provider
            self.backend.model = self.backend.selection.model
        except Exception:
            pass
        self._refresh_status()
        self._run_turn_worker()

    def _handle_slash(self, text: str) -> bool:
        """Handle a slash command. Returns True when the input was consumed
        (accepted), False when rejected (e.g. busy) so the caller can keep
        the text in the input box (task B2)."""
        parts = text.split()
        cmd = parts[0].lower()
        success = self._theme.get("success", "#6abf69")
        warning = self._theme.get("warning", "#d4a843")
        dim = self._theme.get("dim", "#8b93a7")

        # Local-only commands that must act on the TUI itself.
        if cmd in ("/exit", "/quit", "/q"):
            self.exit()
            return True
        if cmd in ("/clear", "/reset"):
            self.query_one("#log", RichLog).clear()
            self.backend.history.clear()
            self._append(Text("✓ Layar & riwayat dibersihkan", style=f"{success}"))
            return True

        if self._busy:
            self._append(Text("Masih memproses, tunggu sebentar…",
                              style=f"{warning}"))
            return False

        # Everything else is delegated to the engine's handle_command, whose
        # console output we capture and render into the log (see worker).
        self._append(Text(f"> {text}", style=f"{dim}"))
        # Claim busy on the UI thread before scheduling (task B1).
        self._busy = True
        self._state = "busy"
        self._activity = "Menjalankan perintah"
        self._refresh_status()
        self._run_slash_worker(text)
        return True

    @work(thread=True, exclusive=True, group="slash")
    def _run_slash_worker(self, text: str) -> None:
        self.call_from_thread(self._thinking_start, "Menjalankan perintah")
        b = self.backend
        try:
            from opsora_v2 import handle_command
            from opsora_tui import console as tui_console

            # Task B3: the shared console is not a terminal under Textual,
            # so capture() would strip colors. Force terminal mode, a sane
            # width, and (Rich 15) a color system — _color_system is only
            # auto-detected at construction, so a console created under a
            # non-tty stays colorless even with force_terminal on. Restore
            # everything afterwards so the classic path is unaffected.
            prev_force = getattr(tui_console, "_force_terminal", None)
            prev_width = getattr(tui_console, "_width", None)
            prev_color_system = getattr(tui_console, "_color_system", None)
            tui_console._force_terminal = True
            if getattr(tui_console, "_color_system", None) is None:
                try:
                    from rich.console import COLOR_SYSTEMS
                    tui_console._color_system = COLOR_SYSTEMS["truecolor"]
                except Exception:
                    pass
            try:
                tui_console._width = max(50, min(120, self.size.width - 2))
            except Exception:
                pass
            try:
                with tui_console.capture() as capture:
                    cont, new_sel, resume_id = handle_command(
                        text, b.history, b.selection, b.status_bar, b.session_id)
                captured = capture.get()
            finally:
                tui_console._force_terminal = prev_force
                tui_console._width = prev_width
                tui_console._color_system = prev_color_system
            if captured.strip():
                self.call_from_thread(self._append_ansi, captured)

            if new_sel is not None:
                b.selection = new_sel
                b.provider = getattr(new_sel, "provider", b.provider)
                b.model = getattr(new_sel, "model", b.model)
                try:
                    b.status_bar.provider = new_sel.provider
                    b.status_bar.model = new_sel.model
                except Exception:
                    pass
            if resume_id:
                self.call_from_thread(self._do_resume, resume_id)
            if not cont:
                self.call_from_thread(self.exit)
        except Exception as e:  # noqa: BLE001
            self._state = "error"
            self._activity = "Gagal"
            self.call_from_thread(
                self._append,
                Text(f"✗ {e}", style=f"bold {self._theme.get('error', '#d45555')}"))
        finally:
            self._busy = False
            self.call_from_thread(self._thinking_stop)
            self.call_from_thread(self._refresh_status)
            self.call_from_thread(self._refocus_input)

    def _append_ansi(self, ansi_text: str) -> None:
        """Render captured console output (ANSI) into the log, colors intact."""
        try:
            styled = Text.from_ansi(ansi_text)
        except Exception:
            styled = Text(ansi_text)
        self.query_one("#log", RichLog).write(styled)

    def _do_resume(self, resume_id: str) -> None:
        try:
            from opsora_session import load_session
            session = load_session(resume_id)
            if session:
                self.backend.history = session.messages
                self.backend.session_id = resume_id
        except Exception:
            pass

    # -- turn execution (worker thread) --------------------------------------

    @work(thread=True, exclusive=True, group="turn")
    def _run_turn_worker(self) -> None:
        # NOTE: self._busy is claimed by the caller (on_input_submitted) on
        # the UI thread, BEFORE this worker is scheduled (task B1).
        self.call_from_thread(self._thinking_start, "Berpikir")
        b = self.backend

        def emit(renderable: RenderableType) -> None:
            # Marshal onto the UI thread before touching widgets.
            self.call_from_thread(self._append, renderable)

        def status(text: str) -> None:
            self.call_from_thread(self._thinking_message, text)

        def think(text: str) -> None:
            self.call_from_thread(self._thinking_stream, text)

        try:
            history, selection = b.run_turn(
                b.history, b.selection, b.status_bar, emit, status, think=think)
            b.history = history
            b.selection = selection
            b.provider = getattr(selection, "provider", b.provider)
            b.model = getattr(selection, "model", b.model)
            if b.on_turn_done:
                try:
                    b.on_turn_done(history, selection)
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001 — surface, don't crash the app
            self._state = "error"
            self._activity = "Gagal"
            self.call_from_thread(
                self._append,
                Text(f"✗ {e}", style=f"bold {self._theme.get('error', '#d45555')}"))
        finally:
            self._busy = False
            self.call_from_thread(self._thinking_stop)
            self.call_from_thread(self._refresh_status)
            self.call_from_thread(self._refocus_input)

    # -- UI helpers (UI thread) ----------------------------------------------

    def _append(self, renderable: RenderableType) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _thinking_start(self, message: str = "Berpikir") -> None:
        self._state = "busy"
        self._activity = message
        self._refresh_status()
        try:
            self.query_one("#thinking", ThinkingIndicator).start(message)
        except Exception:
            pass

    def _thinking_message(self, message: str) -> None:
        # Mirror live tool/activity progress into the status bar (task B4).
        if message:
            self._activity = message
            self._refresh_status()
        try:
            self.query_one("#thinking", ThinkingIndicator).set_message(message)
        except Exception:
            pass

    def _thinking_stream(self, text: str) -> None:
        try:
            self.query_one("#thinking", ThinkingIndicator).stream_thinking(text)
        except Exception:
            pass

    def _thinking_stop(self) -> None:
        try:
            self.query_one("#thinking", ThinkingIndicator).stop()
        except Exception:
            pass
        # Only downgrade busy→ok; an error state set by the worker survives.
        if self._state == "busy":
            self._state = "ok"
            self._activity = "Selesai"
            self._refresh_status()

    def _set_activity(self, text: str) -> None:
        # Rendered in the status bar (task B4 — was stored but never shown).
        self._activity = text
        self._refresh_status()

    def _refresh_status(self) -> None:
        try:
            self.query_one("#statusbar", Static).update(self._status_text())
        except Exception:
            pass

    def _refocus_input(self) -> None:
        self.query_one("#inputbox", Input).focus()

    # -- actions -------------------------------------------------------------

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def action_interrupt(self) -> None:
        self._state = "warn"
        self._set_activity("Dibatalkan")
        self.workers.cancel_group(self, "turn")
        self._busy = False
        self._thinking_stop()
        self._refocus_input()

    def action_quit_maybe(self) -> None:
        inp = self.query_one("#inputbox", Input)
        if not inp.value:
            self.exit()
