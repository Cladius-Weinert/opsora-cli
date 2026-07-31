"""Opsora TUI Engine — Codex/Claude Code-style terminal UI components.

Provides: status bar, approval modes, syntax highlighting, diff display,
context indicator, progress tracking, streaming text, file tree.
"""

from __future__ import annotations

import difflib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console(soft_wrap=True)

# ---------------------------------------------------------------------------
# Approval Modes (Codex-style: suggest / auto-edit / full-auto)
# ---------------------------------------------------------------------------


class ApprovalMode(Enum):
    SUGGEST = "suggest"
    AUTO_EDIT = "auto-edit"
    FULL_AUTO = "full-auto"

    @property
    def label(self) -> str:
        return {
            ApprovalMode.SUGGEST: "[yellow]suggest[/yellow]",
            ApprovalMode.AUTO_EDIT: "[cyan]auto-edit[/cyan]",
            ApprovalMode.FULL_AUTO: "[green]full-auto[/green]",
        }[self]

    @property
    def description(self) -> str:
        return {
            ApprovalMode.SUGGEST: "Read-only — no edits or commands without approval",
            ApprovalMode.AUTO_EDIT: "File edits auto-approved, commands need approval",
            ApprovalMode.FULL_AUTO: "Everything auto-approved in sandbox",
        }[self]


APPROVAL_MODES = list(ApprovalMode)
_current_approval_mode = ApprovalMode.FULL_AUTO


def get_approval_mode() -> ApprovalMode:
    mode = os.environ.get("OPSORA_APPROVAL_MODE", "full-auto").lower()
    try:
        return ApprovalMode(mode)
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
    panel_content = action
    if detail:
        panel_content += f"\n\n{detail}"
    console.print(Panel(panel_content, title="[yellow]Approval Required[/yellow]", border_style="yellow", box=box.ROUNDED))
    try:
        answer = console.input("[bold yellow]Approve? [Y/n] [/bold yellow]").strip().lower()
        return answer in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ---------------------------------------------------------------------------
# Status Bar (Codex-style top bar)
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

    @property
    def context_color(self) -> str:
        pct = self.context_pct
        if pct < 60:
            return "green"
        if pct < 85:
            return "yellow"
        return "red"

    def render(self) -> Panel:
        cwd_short = self.cwd
        if len(cwd_short) > 30:
            cwd_short = "…" + cwd_short[-28:]

        provider_dot = "[green]●[/green]"
        approval_label = self.approval_mode.label
        ctx_color = self.context_color
        ctx_pct = 100 - self.context_pct

        left = f"  {provider_dot} [bold cyan]{self.provider}[/bold cyan]:[cyan]{self.model}[/cyan]"
        center = f"[dim]{cwd_short}[/dim]"
        right = (
            f"[{ctx_color}]{ctx_pct}% context left[/{ctx_color}]"
            f"  │  {approval_label}"
            f"  │  [dim]{self.session_tokens} tok[/dim]  "
        )

        bar = f"{left}  │  {center}  │  {right}"
        return Panel(
            bar,
            box=box.SQUARE,
            border_style="bright_black",
            padding=(0, 1),
            expand=True,
        )


# ---------------------------------------------------------------------------
# Streaming Text Output
# ---------------------------------------------------------------------------


def stream_markdown(text: str, speed: float = 0.012) -> None:
    """Stream markdown text word-by-word with Rich Live display."""
    words = text.split(" ")
    out = ""
    with Live(refresh_per_second=30, auto_refresh=True, transient=False) as live:
        for word in words:
            out += word + " "
            live.update(Markdown(out))
            time.sleep(speed)
    console.print()


def stream_text_raw(text: str, speed: float = 0.008) -> None:
    """Stream plain text character-by-character."""
    with Live(refresh_per_second=40, auto_refresh=True, transient=False) as live:
        out = ""
        for char in text:
            out += char
            live.update(Text(out))
            if char not in (" ", "\n"):
                time.sleep(speed)
    console.print()


# ---------------------------------------------------------------------------
# Tool Call Display
# ---------------------------------------------------------------------------


def render_tool_call(name: str, args: dict[str, Any], output: str) -> None:
    """Render a tool call in Codex-style: icon + name + args + output panel."""
    icons = {
        "read_file": "📄",
        "write_file": "✏️",
        "edit_file": "🔧",
        "run_command": "💻",
        "aws_command": "☁️",
        "memory_add": "🧠",
        "memory_search": "🔍",
        "graphify_query": "🕸️",
        "workspace_status": "📊",
        "grep_search": "🔎",
        "glob_search": "📁",
        "web_fetch": "🌐",
        "subagent_spawn": "🤖",
    }
    icon = icons.get(name, "⚙")

    args_preview = ", ".join(f"{k}={repr(v)[:40]}" for k, v in args.items())
    if len(args_preview) > 80:
        args_preview = args_preview[:77] + "…"

    console.print(f"  [dim yellow]{icon} {name}[/dim yellow][dim]({args_preview})[/dim]")

    if not output:
        return

    truncated = output
    max_len = 800
    if len(output) > max_len:
        truncated = output[:max_len] + f"\n[dim]… ({len(output) - max_len} chars omitted)[/dim]"

    if name in ("read_file", "write_file", "edit_file"):
        lang = _detect_language(args.get("filepath", ""))
        console.print(Panel(
            Syntax(truncated, lang, theme="monokai", line_numbers=False, word_wrap=True),
            title=f"{icon} {name}",
            border_style="dim yellow",
            box=box.SIMPLE,
        ))
    elif name == "run_command":
        console.print(Panel(
            truncated,
            title=f"{icon} {args.get('command', '')}",
            border_style="dim yellow",
            box=box.SIMPLE,
        ))
    else:
        console.print(Panel(
            truncated,
            title=f"{icon} {name}",
            border_style="dim yellow",
            box=box.SIMPLE,
        ))


def _detect_language(filepath: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".md": "markdown", ".sh": "bash", ".bash": "bash", ".sql": "sql",
        ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
        ".php": "php", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".env": "bash", ".gitignore": "text",
    }
    for ext, lang in ext_map.items():
        if filepath.endswith(ext):
            return lang
    return "text"


# ---------------------------------------------------------------------------
# Diff Display
# ---------------------------------------------------------------------------


def render_diff(old_text: str, new_text: str, filepath: str = "") -> None:
    """Render a syntax-highlighted unified diff."""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm="",
    )
    diff_text = "\n".join(diff)
    if not diff_text:
        console.print(f"  [dim]No changes to {filepath}[/dim]")
        return
    console.print(Panel(
        Syntax(diff_text, "diff", theme="monokai"),
        title=f"📝 Diff: {filepath}",
        border_style="cyan",
        box=box.ROUNDED,
    ))


def render_file_edit(filepath: str, old_str: str, new_str: str) -> None:
    """Render a file edit as a focused diff panel."""
    console.print(f"  [cyan]✏️  Editing[/cyan] [bold]{filepath}[/bold]")
    render_diff(old_str, new_str, filepath)


# ---------------------------------------------------------------------------
# File Tree
# ---------------------------------------------------------------------------


def render_file_tree(path: str, max_depth: int = 3, max_items: int = 50) -> Tree:
    """Render a directory as a Rich Tree."""
    from pathlib import Path

    root = Path(path)
    tree = Tree(f"📁 [bold]{root.name}/[/bold]", guide_style="dim")

    def add_children(tree_node, dir_path, depth):
        if depth >= max_depth:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            tree_node.add("[dim]Permission denied[/dim]")
            return

        count = 0
        for entry in entries:
            if count >= max_items:
                tree_node.add(f"[dim]… and more[/dim]")
                break
            if entry.name.startswith(".") and entry.name in (".git", ".node_modules", "__pycache__", ".cache"):
                continue
            count += 1
            if entry.is_dir():
                branch = tree_node.add(f"📁 [bold cyan]{entry.name}/[/bold cyan]")
                add_children(branch, entry, depth + 1)
            else:
                icon = "📄"
                if entry.suffix in (".py",):
                    icon = "🐍"
                elif entry.suffix in (".js", ".ts", ".tsx", ".jsx"):
                    icon = "⚡"
                elif entry.suffix in (".md",):
                    icon = "📝"
                elif entry.suffix in (".json", ".yaml", ".yml", ".toml"):
                    icon = "⚙"
                size = entry.stat().st_size
                size_str = f"{size:,}B" if size < 1024 else f"{size // 1024}KB"
                tree_node.add(f"{icon} {entry.name} [dim]({size_str})[/dim]")

    add_children(tree, root, 0)
    return tree


# ---------------------------------------------------------------------------
# Progress Tracking (for multi-step tasks)
# ---------------------------------------------------------------------------


class TaskProgress:
    """Track and display multi-step task progress."""

    def __init__(self):
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(bar_width=20),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        self._task_id = None
        self._live = None

    def start(self, description: str, total: int) -> None:
        self._live = Live(self.progress, console=console, refresh_per_second=10)
        self._live.start()
        self._task_id = self.progress.add_task(description, total=total)

    def advance(self, advance: int = 1, description: str = "") -> None:
        if self._task_id is not None:
            if description:
                self.progress.update(self._task_id, description=description)
            self.progress.advance(self._task_id, advance)

    def stop(self) -> None:
        if self._live:
            self._live.stop()


# ---------------------------------------------------------------------------
# Welcome Screen (Codex-style)
# ---------------------------------------------------------------------------


def render_welcome(
    provider: str,
    model: str,
    approval_mode: ApprovalMode,
    tools_count: int,
    cwd: str,
) -> Panel:
    """Render the Codex-style welcome panel."""
    time_str = datetime.now().strftime("%H:%M")

    content = Text()
    content.append("  OPSORA", style="bold cyan")
    content.append("  v3.0 — Agentic Terminal\n", style="dim white")
    content.append(f"  {provider}:{model}", style="bold cyan")
    content.append(f"  ·  {cwd}\n", style="dim")
    content.append(f"  {tools_count} tools", style="green")
    content.append(f"  ·  {approval_mode.value} mode", style="yellow")
    content.append(f"  ·  {time_str}\n\n", style="dim")
    content.append("  Type a question or use ", style="dim")
    content.append("/help", style="bold cyan")
    content.append(" for commands. ", style="dim")
    content.append("Ctrl+A", style="bold yellow")
    content.append(" cycles approval mode.", style="dim")

    return Panel(
        content,
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )


# ---------------------------------------------------------------------------
# Help Panel
# ---------------------------------------------------------------------------


def render_help() -> Panel:
    return Panel(
        "[bold]/help[/bold]          Show commands\n"
        "[bold]/status[/bold]        Provider & tool status\n"
        "[bold]/models[/bold]        Provider routes\n"
        "[bold]/tools[/bold]         Available tools\n"
        "[bold]/mode[/bold]          Cycle approval mode\n"
        "[bold]/tree[/bold] [path]    File tree\n"
        "[bold]/sessions[/bold]      List saved sessions\n"
        "[bold]/resume[/bold] <id>   Resume a session\n"
        "[bold]/new[/bold]           New conversation\n"
        "[bold]/run[/bold] <cmd>     Quick shell command\n"
        "[bold]/read[/bold] <file>   Quick file read\n"
        "[bold]/memory[/bold] <q>   Search memory\n"
        "[bold]/clear[/bold]         Clear screen\n"
        "[bold]/exit[/bold]          Exit",
        title="[bold cyan]Commands[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
    )
