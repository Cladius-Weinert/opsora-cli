"""Opsora TUI — Codex-style terminal UI.

Minimal, clean, fast. No panels. No boxes. Just content.
Plus a bordered input box at the bottom (Codex-style).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import HasFocus
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, VSplit
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import SearchToolbar

console = Console(soft_wrap=True)

# ---------------------------------------------------------------------------
# Approval Modes
# ---------------------------------------------------------------------------

class ApprovalMode(Enum):
    SUGGEST = "suggest"
    AUTO_EDIT = "auto-edit"
    FULL_AUTO = "full-auto"

APPROVAL_MODES = list(ApprovalMode)
_current_approval_mode = ApprovalMode.FULL_AUTO


def get_approval_mode() -> ApprovalMode:
    import os
    try:
        return ApprovalMode(os.environ.get("OPSORA_APPROVAL_MODE", "full-auto").lower())
    except ValueError:
        return _current_approval_mode


def set_approval_mode(mode: ApprovalMode) -> None:
    global _current_approval_mode
    _current_approval_mode = mode


def cycle_approval_mode() -> ApprovalMode:
    global _current_approval_mode
    idx = APPROVAL_MODES.index(_current_approval_mode)
    _current_approval_mode = APPROVAL_MODES[(idx + 1) % len(APPROVAL_MODES)]
    return _current_approval_mode


def needs_approval(action_type: str) -> bool:
    mode = get_approval_mode()
    if mode == ApprovalMode.FULL_AUTO:
        return False
    if mode == ApprovalMode.AUTO_EDIT and action_type in ("read_file", "write_file", "edit_file"):
        return False
    return True


def prompt_approval(action: str, detail: str = "") -> bool:
    console.print(Text(f"  ⚠ {action}", style="yellow"))
    if detail:
        console.print(Text(f"    {detail[:200]}", style="dim"))
    try:
        answer = console.input(Text("  lanjut? [Y/n] ", style="yellow bold")).strip().lower()
        return answer in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ---------------------------------------------------------------------------
# Status Bar — Codex-style single line header
# ---------------------------------------------------------------------------

@dataclass
class StatusBar:
    provider: str = "alibaba"
    model: str = "qwen-plus"
    approval_mode: ApprovalMode = ApprovalMode.FULL_AUTO
    context_used: int = 0
    context_total: int = 32768
    session_tokens: int = 0
    cwd: str = "/root"

    @property
    def context_pct(self) -> int:
        if self.context_total == 0:
            return 0
        return min(100, int(self.context_used / self.context_total * 100))

    def render_line(self) -> Text:
        """Render as a single compact line — Codex-style."""
        ctx_remaining = 100 - self.context_pct
        ctx_color = "green" if ctx_remaining > 40 else "yellow" if ctx_remaining > 15 else "red"

        t = Text()
        t.append("opsora", style="bold cyan")
        t.append(f"  {self.model}", style="dim")
        t.append(f"  {ctx_remaining}% ctx", style=ctx_color)
        t.append(f"  {self.approval_mode.value}", style="dim")
        if self.session_tokens > 0:
            t.append(f"  {self.session_tokens} tok", style="dim")
        return t


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def stream_markdown(text: str, speed: float = 0.008) -> None:
    """Stream markdown — transient Live, then final clean print."""
    if not text or not text.strip():
        return
    words = text.split(" ")
    out = ""
    try:
        with Live(refresh_per_second=30, auto_refresh=True, transient=True) as live:
            for word in words:
                out += word + " "
                live.update(Markdown(out))
                time.sleep(speed)
        console.print(Markdown(out.strip()))
    except Exception:
        console.print(Markdown(text))


# ---------------------------------------------------------------------------
# Tool Call Display — Codex-style: compact, no borders
# ---------------------------------------------------------------------------

_TOOL_ICONS = {
    "read_file": "📄", "write_file": "✏️", "edit_file": "🔧",
    "run_command": "▶", "aws_command": "☁", "memory_add": "🧠",
    "memory_search": "🔍", "graphify_query": "🕸", "workspace_status": "📊",
    "grep_search": "🔎", "glob_search": "📁", "web_fetch": "🌐",
    "list_directory": "📂", "subagent_spawn": "🤖", "todo_write": "📋",
    "git_diff": "📝", "git_status": "🔀", "git_log": "📜", "run_tests": "🧪",
    "git_commit": "📦", "lint_check": "🔍", "image_read": "🖼️", "pip_info": "📋",
}


def render_tool_call(name: str, args: dict[str, Any], output: str) -> None:
    """Codex-style tool display: compact header + indented output."""
    icon = _TOOL_ICONS.get(name, "⚙")

    # --- Special: todo_write ---
    if name == "todo_write":
        todos = args.get("todos", [])
        if todos:
            console.print()
            for t in todos:
                status = t.get("status", "pending")
                tid = t.get("id", "?")
                content = t.get("content", "")
                if status == "completed":
                    console.print(Text(f"  ✓ [{tid}] {content}", style="green"))
                elif status == "in_progress":
                    console.print(Text(f"  ● [{tid}] {content}", style="cyan bold"))
                else:
                    console.print(Text(f"  ○ [{tid}] {content}", style="dim"))
            console.print()
        return

    # --- Compact args ---
    args_parts = []
    for v in args.values():
        sv = str(v)
        if len(sv) > 50:
            sv = sv[:47] + "…"
        args_parts.append(sv)
    args_short = ", ".join(args_parts)

    # Header: ✓ icon name(args)
    console.print(Text(f"  {icon} {name}({args_short})", style="bold dim"))

    if not output or output.strip() == "":
        return

    # Truncate
    max_len = 4000 if name == "read_file" else 2000
    truncated = output.strip()
    if len(truncated) > max_len:
        truncated = truncated[:max_len] + f"\n  … {len(output) - max_len} chars lagi"

    # File content: syntax highlight
    if name in ("read_file", "write_file", "edit_file"):
        lang = _detect_language(args.get("filepath", ""))
        indented = "\n".join(f"    {line}" for line in truncated.split("\n"))
        console.print(Syntax(indented, lang, theme="monokai", word_wrap=True))
    elif name == "run_command":
        indented = "\n".join(f"    {line}" for line in truncated.split("\n"))
        console.print(Text(indented, style="dim"))
    else:
        indented = "\n".join(f"    {line}" for line in truncated.split("\n"))
        console.print(Text(indented, style="dim"))


def _detect_language(filepath: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".md": "markdown", ".sh": "bash", ".bash": "bash", ".sql": "sql",
        ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
        ".php": "php", ".c": "c", ".cpp": "cpp", ".h": "c",
    }
    for ext, lang in ext_map.items():
        if filepath.endswith(ext):
            return lang
    return "text"


# ---------------------------------------------------------------------------
# Diff Display
# ---------------------------------------------------------------------------

def render_file_edit(filepath: str, old_str: str, new_str: str) -> None:
    """Show a compact diff after file edit."""
    import difflib
    diff = list(difflib.unified_diff(
        old_str.splitlines(keepends=True),
        new_str.splitlines(keepends=True),
        fromfile="old", tofile="new", lineterm="",
    ))
    if not diff:
        return
    diff_text = "\n".join(diff)
    console.print(Syntax(diff_text, "diff", theme="monokai"))


# ---------------------------------------------------------------------------
# File Tree
# ---------------------------------------------------------------------------

def render_file_tree(path: str, max_depth: int = 3, max_items: int = 50) -> None:
    from pathlib import Path as P
    root = P(path)
    if not root.is_dir():
        console.print(Text(f"  {path} bukan directory", style="red"))
        return

    def _walk(dirpath, prefix, depth):
        if depth >= max_depth:
            return
        try:
            entries = sorted(dirpath.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if not e.name.startswith(".")]
        for i, entry in enumerate(entries[:max_items]):
            last = i == len(entries[:max_items]) - 1
            connector = "└── " if last else "├── "
            if entry.is_dir():
                console.print(Text(f"{prefix}{connector}{entry.name}/", style="cyan"))
                ext = "    " if last else "│   "
                _walk(entry, prefix + ext, depth + 1)
            else:
                console.print(Text(f"{prefix}{connector}{entry.name}", style="dim"))

    console.print(Text(f"  {root.name}/", style="cyan bold"))
    _walk(root, "  ", 0)


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def render_help() -> None:
    """Print help as clean text, no panels."""
    console.print()
    console.print(Text("  commands", style="bold cyan"))
    lines = [
        ("  /help", "tampilin ini"),
        ("  /status", "provider & tools"),
        ("  /models", "list model"),
        ("  /tools", "daftar tools"),
        ("  /mode", "ganti approval mode"),
        ("  /tree [path]", "struktur folder"),
        ("  /sessions", "list session"),
        ("  /resume <id>", "lanjutin session"),
        ("  /save [nama]", "simpan session"),
        ("  /new", "obrolan baru"),
        ("  /run <cmd>", "jalankan command"),
        ("  /read <file>", "baca file"),
        ("  /diff <a> <b>", "bandingin 2 file"),
        ("  /memory <q>", "cari di memory"),
        ("  /agent <goal>", "spawn sub-agents"),
    ]
    for cmd, desc in lines:
        console.print(Text(cmd, style="bold cyan"), Text(f"  {desc}", style="dim"))

    console.print()
    console.print(Text("  skills", style="bold cyan"))
    skills = [
        ("  /review [path]", "review code changes (git diff)"),
        ("  /deploy [target]", "deploy ke render/vercel"),
        ("  /explain <file>", "explain code"),
        ("  /refactor <file>", "refactor code"),
        ("  /test [file]", "generate & run tests"),
        ("  /fix-ci", "fix CI failures"),
    ]
    for cmd, desc in skills:
        console.print(Text(cmd, style="bold green"), Text(f"  {desc}", style="dim"))

    console.print()
    console.print(Text("  other", style="bold cyan"))
    other = [
        ("  /cost", "session cost & tokens"),
        ("  /copy", "copy last response to clipboard"),
        ("  /fork", "fork session (save + clear)"),
        ("  /clear", "bersihin layar"),
        ("  /exit", "keluar"),
    ]
    for cmd, desc in other:
        console.print(Text(cmd, style="bold yellow"), Text(f"  {desc}", style="dim"))
    console.print()


# ---------------------------------------------------------------------------
# Welcome — Codex-style minimal
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Codex-style Bordered Input Box
# ---------------------------------------------------------------------------

def codex_prompt(
    provider: str = "alibaba",
    model: str = "qwen-plus",
    approval: str = "full-auto",
    ctx_pct: int = 0,
    tokens: int = 0,
    completer=None,
) -> str:
    """Codex-style bordered input box at terminal bottom.

    Layout:
        ──────────────────────────
         ❯ [user types here]
        opsora  model  ctx%  mode
    """
    import sys as _sys

    # Fallback for piped/non-TTY input
    if not _sys.stdin.isatty():
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return "__EXIT__"

    buf = Buffer(name="input", completer=completer)

    # Top border line
    top_border = FormattedTextControl(
        FormattedText([("fg:#444444", "  ─" + "─" * 50)])
    )

    # Prompt prefix + input
    prompt_prefix = FormattedTextControl(
        FormattedText([
            ("fg:#00aaaa bold", "  ❯ "),
        ])
    )

    # Bottom status bar
    status_text = FormattedText([
        ("fg:#555555", f"  opsora  {provider}:{model}"),
        ("fg:#444444", f"  {100 - ctx_pct}% ctx"),
        ("fg:#444444", f"  {approval}"),
        ("fg:#444444", f"  {tokens} tok" if tokens else ""),
    ])
    status_bar_ctrl = FormattedTextControl(status_text)

    # Key bindings
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        event.app.exit(result=buf.text)

    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result="__INTERRUPT__")

    @kb.add("c-d")
    def _exit(event):
        if not buf.text:
            event.app.exit(result="__EXIT__")

    @kb.add("c-a")
    def _cycle_mode(event):
        # Delegate to external handler
        new_mode = cycle_approval_mode()
        event.app.invalidate()

    # Build layout — Codex-style bordered box
    layout = Layout(HSplit([
        # Spacer (pushes input to bottom of visible area)
        Window(height=Dimension.exact(0)),
        # Top border
        Window(content=top_border, height=Dimension.exact(1)),
        # Input line: prefix + buffer
        VSplit([
            Window(content=prompt_prefix, width=Dimension.exact(5)),
            Window(content=BufferControl(buffer=buf, focusable=True), height=Dimension.exact(1)),
        ], height=Dimension.exact(1)),
        # Bottom status bar
        Window(content=status_bar_ctrl, height=Dimension.exact(1)),
    ]))

    style = PTStyle.from_dict({
        "bottom-toolbar": "fg:#555555",
    })

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
    )

    result = app.run()
    return result or ""


def print_welcome(model: str, tools_count: int, approval: ApprovalMode) -> None:
    console.print()
    console.print(Text("opsora", style="bold cyan"), Text(f"  {model}  ·  {tools_count} tools  ·  {approval.value}", style="dim"))
    console.print()
