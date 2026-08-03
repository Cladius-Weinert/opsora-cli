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
from rich.panel import Panel
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Input, RichLog, Static

from opsora_themes import get_theme, load_theme_preference


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
    on_turn_done: Optional[Callable[[list, Any], None]] = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class OpsoraApp(App):
    """Persistent Opsora TUI: scrolling output on top, pinned input below."""

    TITLE = "Opsora"
    SUB_TITLE = "multi-provider AI"

    # Structural layout only — colors are applied programmatically in
    # ``_apply_widget_styles`` so they always follow the active Opsora theme
    # and never depend on Textual design-token names (which vary by version).
    CSS = """
    #banner {
        height: auto;
        padding: 0 1;
    }
    #log {
        height: 1fr;
        border: none;
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
        super().__init__()
        self.backend = backend
        self._theme_name = theme_name or load_theme_preference()
        self._theme = get_theme(self._theme_name)
        self._busy = False

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._banner_renderable(), id="banner")
        yield RichLog(id="log", markup=True, wrap=True, highlight=True)
        yield Input(placeholder="Tanya Opsora…  (Enter kirim · /help commands)", id="inputbox")
        yield Static(self._status_text(), id="statusbar")

    def on_mount(self) -> None:
        self._apply_widget_styles()
        self.query_one("#inputbox", Input).focus()
        log = self.query_one("#log", RichLog)
        log.write(self._welcome_renderable())
        log.write(Text(""))

    # -- theming (programmatic, version-safe) --------------------------------

    def _apply_widget_styles(self) -> None:
        t = self._theme
        bg = t.get("bg", "#1a1a2e")
        fg = t.get("fg", "#e0e0e0")
        accent = t.get("accent", "#00ffff")
        dim = t.get("dim", "#8a8a9a")
        # Slightly darker panel for the input + status bar.
        panel = self._darken(bg, 0.25)
        status_bg = self._darken(bg, 0.4)

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
        inp.styles.border = ("tall", accent)
        inp.styles.caret_color = accent

        status = self.query_one("#statusbar", Static)
        status.styles.background = status_bg
        status.styles.color = dim

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
        t = self._theme
        accent = t.get("accent", "#00ffff")
        dim = t.get("dim", "#8a8a9a")
        b = self.backend
        line1 = Text()
        line1.append("OPSORA", style=f"bold {accent}")
        line1.append("  one terminal · every AI provider", style=f"italic {dim}")
        return line1

    def _welcome_renderable(self) -> RenderableType:
        t = self._theme
        accent = t.get("accent", "#00ffff")
        success = t.get("success", "#00ff88")
        error = t.get("error", "#ff4444")
        dim = t.get("dim", "#8a8a9a")
        border = t.get("border", "#444444")
        b = self.backend

        lines: List[Text] = []
        logo = [
            " ██████╗ ██╗   ██╗ ██████╗ ██████╗ ███████╗███╗   ██╗",
            " ██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔══██╗██╔════╝████╗  ██║",
            " ██████╔╝ ╚████╔╝ ██║     ██████╔╝█████╗  ██╔██╗ ██║",
            " ██╔═══╝   ╚██╔╝  ██║     ██╔═══╝ ██╔══╝  ██║╚██╗██║",
            " ██║        ██║  ███████╗██║     ███████╗██║ ╚████║",
            " ╚═╝        ╚═╝  ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝",
        ]
        from opsora_tui import _gradient_steps
        for line, color in zip(logo, _gradient_steps(accent, len(logo))):
            lines.append(Text(line, style=f"bold {color}"))
        lines.append(Text("     One terminal · Every AI provider · Zero lock-in",
                          style=f"italic {dim}"))
        lines.append(Text(""))

        # Provider health with colored dots (reliable on Android terminals).
        lines.append(Text(" ┌─ Provider Health ─────────────────────────────┐", style=border))
        for h in b.health:
            row = Text(" │ ")
            if h.get("available"):
                row.append("● ", style=f"bold {success}")
                row.append(f"{h['name']:<20}", style="bold")
            else:
                row.append("● ", style=error)
                row.append(f"{h['name']:<20}", style="dim")
            row.append(", ".join(h.get("models", [])[:3]), style=dim)
            lines.append(row)
        lines.append(Text(" └───────────────────────────────────────────────┘", style=border))
        lines.append(Text(""))
        lines.append(Text(
            f" {b.tools_count} tools · {b.provider}:{b.model} · {b.approval} mode",
            style=dim))
        lines.append(Text(
            " /help commands · /status detail · Ctrl+L clear · input selalu di bawah",
            style=dim))
        return Group(*lines)

    def _status_text(self) -> RenderableType:
        t = self._theme
        accent = t.get("accent", "#00ffff")
        dim = t.get("dim", "#8a8a9a")
        b = self.backend
        sb = b.status_bar
        try:
            ctx = sb.context_pct
        except Exception:
            ctx = 0
        txt = Text()
        txt.append(f" {b.provider}:{b.model}", style=f"bold {accent}")
        txt.append("  │  ", style=dim)
        txt.append(f"{100 - ctx}% ctx", style=dim)
        txt.append("  │  ", style=dim)
        txt.append(b.approval, style=dim)
        if getattr(self, "_activity", ""):
            txt.append("  │  ", style=dim)
            txt.append(self._activity, style=dim)
        return txt

    # -- input handling ------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if self._busy:
            self._append(Text("⏳ Masih memproses turn sebelumnya…", style="yellow"))
            return

        if text.startswith("/"):
            self._handle_slash(text)
            return

        log = self.query_one("#log", RichLog)
        log.write(Text(f"▸ {text}", style="bold cyan"))
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

    def _handle_slash(self, text: str) -> None:
        parts = text.split()
        cmd = parts[0].lower()
        log = self.query_one("#log", RichLog)

        if cmd in ("/exit", "/quit", "/q"):
            self.exit()
            return
        if cmd in ("/clear", "/reset"):
            log.clear()
            self.backend.history.clear()
            self._append(Text("✓ Layar & riwayat dibersihkan", style="green"))
            return
        if cmd == "/status":
            self._append(self._welcome_renderable())
            return
        if cmd == "/help":
            self._append(Panel(
                "[bold]/exit[/bold] keluar   [bold]/clear[/bold] bersihkan   "
                "[bold]/status[/bold] detail   [bold]/help[/bold] bantuan\n"
                "[dim]Ctrl+L clear · Ctrl+C interrupt · Ctrl+D keluar\n"
                "Command lengkap tersedia di mode klasik: OPSORA_CLASSIC=1 opsora[/dim]",
                title="Opsora commands", border_style="cyan"))
            return
        # Unknown slash command — hint to classic mode.
        self._append(Text(
            f"✗ '{cmd}' belum didukung di TUI baru. Pakai mode klasik: "
            f"OPSORA_CLASSIC=1 opsora", style="yellow"))

    # -- turn execution (worker thread) --------------------------------------

    @work(thread=True, exclusive=True, group="turn")
    def _run_turn_worker(self) -> None:
        self._busy = True
        self._set_activity("Berpikir…")
        b = self.backend

        def emit(renderable: RenderableType) -> None:
            # Marshal onto the UI thread before touching widgets.
            self.call_from_thread(self._append, renderable)

        def status(text: str) -> None:
            self.call_from_thread(self._set_activity, text)

        try:
            history, selection = b.run_turn(
                b.history, b.selection, b.status_bar, emit, status)
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
            self.call_from_thread(self._append,
                                  Text(f"✗ {e}", style="bold red"))
        finally:
            self._busy = False
            self.call_from_thread(self._set_activity, "")
            self.call_from_thread(self._refresh_status)
            self.call_from_thread(self._refocus_input)

    # -- UI helpers (UI thread) ----------------------------------------------

    def _append(self, renderable: RenderableType) -> None:
        self.query_one("#log", RichLog).write(renderable)

    def _set_activity(self, text: str) -> None:
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
        self._set_activity("interrupted")
        self.workers.cancel_group(self, "turn")
        self._busy = False
        self._refocus_input()

    def action_quit_maybe(self) -> None:
        inp = self.query_one("#inputbox", Input)
        if not inp.value:
            self.exit()
