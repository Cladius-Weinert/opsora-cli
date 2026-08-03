"""Opsora TUI v3.2 — Premium Interactive Terminal AI

Design improvements:
- Beautiful gradient themes with per-theme color palettes
- Animated status bar with live activity indicators
- Rich welcome screen with provider health
- Enhanced tool call visualization with syntax highlighting
- Auto-complete for slash commands and models
- Keyboard shortcuts (Ctrl+A mode, Ctrl+T theme, Ctrl+V verbose)
- Mobile/Termux optimized layouts
- Better markdown streaming with cursor
- Activity timeline in status bar
"""

from __future__ import annotations

import os
import re
import time
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List, Dict
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.align import Align
from rich.rule import Rule
from rich.tree import Tree

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.filters import HasFocus, Condition
from prompt_toolkit.formatted_text import FormattedText, HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, VSplit, Container
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

console = Console(soft_wrap=True, highlight=True)

# ============================================================================
# THEME SYSTEM — Beautiful gradient color palettes
# ============================================================================

THEMES: Dict[str, Dict[str, Any]] = {
    "dark": {
        "name": "Dark Ocean",
        "description": "Calm dark theme for late nights",
        "colors": {
            "accent": "#5fb8c0",
            "accent_bright": "#8fd8e8",
            "success": "#6abf69",
            "warning": "#d4a843",
            "error": "#d45555",
            "dim": "#6a6a7a",
            "prompt": "#5fb8c0",
            "border": "#3a3a4a",
            "bg": "#0d1117",
            "bg_secondary": "#161b22",
            "text": "#e6edf3",
            "text_secondary": "#8b949e",
            "tool_bg": "#161b22",
            "header": "#4a8fa8",
        }
    },
    "light": {
        "name": "Light Paper",
        "description": "Clean light theme for daylight",
        "colors": {
            "accent": "#0070c0",
            "accent_bright": "#4da8da",
            "success": "#28a745",
            "warning": "#e67e22",
            "error": "#dc3545",
            "dim": "#6c757d",
            "prompt": "#0070c0",
            "border": "#dee2e6",
            "bg": "#ffffff",
            "bg_secondary": "#f8f9fa",
            "text": "#212529",
            "text_secondary": "#6c757d",
            "tool_bg": "#f8f9fa",
            "header": "#0070c0",
        }
    },
    "cyber": {
        "name": "Cyber Neon",
        "description": "High contrast cyberpunk aesthetic",
        "colors": {
            "accent": "#00ffff",
            "accent_bright": "#80ffff",
            "success": "#00ff88",
            "warning": "#ffaa00",
            "error": "#ff4444",
            "dim": "#8888ff",
            "prompt": "#00ffff",
            "border": "#00ffff",
            "bg": "#0a0a0a",
            "bg_secondary": "#121212",
            "text": "#ffffff",
            "text_secondary": "#aaaaaa",
            "tool_bg": "#1a0033",
            "header": "#ff00ff",
        }
    },
    "warm": {
        "name": "Warm Sunset",
        "description": "Cozy warm tones for comfort",
        "colors": {
            "accent": "#ff6b35",
            "accent_bright": "#ff9a5c",
            "success": "#4ade80",
            "warning": "#fbbf24",
            "error": "#f87171",
            "dim": "#a855f7",
            "prompt": "#ff6b35",
            "border": "#f97316",
            "bg": "#1c1917",
            "bg_secondary": "#292524",
            "text": "#fafaf9",
            "text_secondary": "#a8a29e",
            "tool_bg": "#292524",
            "header": "#f97316",
        }
    },
}

_CURRENT_THEME = "dark"
_COLORS = THEMES[_CURRENT_THEME]["colors"].copy()

def _c(key: str) -> str:
    return _COLORS.get(key, "#ffffff")

def get_theme_names() -> List[str]:
    return list(THEMES.keys())

def get_theme(name: str) -> Dict[str, Any]:
    return THEMES.get(name, THEMES["dark"])

def apply_theme(name: str) -> bool:
    global _CURRENT_THEME, _COLORS
    if name not in THEMES:
        return False
    _CURRENT_THEME = name
    _COLORS.update(THEMES[name]["colors"])
    return True

def get_current_theme() -> str:
    return _CURRENT_THEME

def set_theme_colors(theme: Dict[str, str]) -> None:
    _COLORS.update(theme)

# ============================================================================
# VERBOSE MODE
# ============================================================================

_verbose = os.environ.get("OPSORA_VERBOSE", "").lower() in ("1", "true", "yes")

def is_verbose() -> bool:
    return _verbose

def toggle_verbose() -> bool:
    global _verbose
    _verbose = not _verbose
    return _verbose

# ============================================================================
# CREDENTIAL REDACTION
# ============================================================================
#
# redact_display() masks secrets before any text reaches the terminal.
# All patterns are compiled once at import time; each rule keeps a short
# recognizable prefix (e.g. "nvapi-****") so output stays debuggable.

_MASK = "****"


def _mask_keep_prefix(m: "re.Match[str]") -> str:
    """Replacement: keep group(1) (provider prefix), mask the secret body."""
    return m.group(1) + _MASK


def _mask_keep_four(m: "re.Match[str]") -> str:
    """Replacement: keep group(1) (name + separator) and first 4 value chars."""
    return m.group(1) + m.group(2)[:4] + _MASK


# Variable/field names that indicate the following value is sensitive.
_SECRET_NAMES = (
    r"api[_-]?key|apikey|access[_-]?key[_-]?(?:id|secret)?"
    r"|secret[_-]?key|client[_-]?secret|private[_-]?key|signing[_-]?key"
    r"|access[_-]?token|auth[_-]?token|bearer[_-]?token|refresh[_-]?token"
    r"|bot[_-]?token|app[_-]?token|session[_-]?token|security[_-]?token"
    r"|password|passwd|passphrase|credential|credentials|authorization"
    r"|token|secret"
)

# Ordered rules: provider-specific shapes first so the generic key=value
# fallback never partially matches an already-masked token.
_REDACT_RULES = [
    # NVIDIA NIM: nvapi-<long body>
    (re.compile(r"(nvapi-)[A-Za-z0-9_\-]{16,}"), _mask_keep_prefix),
    # OpenAI-style sk-... incl. sk-ws-, sk-proj-, sk-ant-, sk-svc-, sk-test-
    (re.compile(r"(sk-(?:[A-Za-z]{2,8}-)?)[A-Za-z0-9_\-]{16,}"), _mask_keep_prefix),
    # xAI Grok: xai-...
    (re.compile(r"(xai-)[A-Za-z0-9_\-]{16,}"), _mask_keep_prefix),
    # Render: rnd_...
    (re.compile(r"(rnd_)[A-Za-z0-9]{16,}"), _mask_keep_prefix),
    # GitHub fine-grained PATs and classic tokens (ghp_/gho_/ghu_/ghs_/ghr_)
    (re.compile(r"(github_pat_)[A-Za-z0-9_]{16,}"), _mask_keep_prefix),
    (re.compile(r"(gh[pousr]_)[A-Za-z0-9]{20,}"), _mask_keep_prefix),
    # Slack: xoxb-/xoxp-/xoxa-/xoxr-/xoxs-
    (re.compile(r"(xox[baprs]-)[A-Za-z0-9\-]{10,}"), _mask_keep_prefix),
    # Google API keys: AIza...
    (re.compile(r"(AIza)[0-9A-Za-z_\-]{20,}"), _mask_keep_prefix),
    # Alibaba Cloud access key ids: LTAI...
    (re.compile(r"(LTAI)[0-9A-Za-z]{12,}"), _mask_keep_prefix),
    # Telegram bot tokens: <bot id>:<secret>
    (re.compile(r"(\d{6,12}:)[A-Za-z0-9_\-]{25,}"), _mask_keep_prefix),
    # Bearer tokens (Authorization headers, error messages)
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-./+]{16,}={0,2}", re.I), _mask_keep_prefix),
    # Generic fallback: long token-ish value assigned to a secret-looking
    # name (KEY=value, "key": "value", key: value, ...). Keeps first 4
    # chars of the value for debuggability.
    (
        re.compile(
            r'(["\']?(?:' + _SECRET_NAMES + r')["\']?\s*[=:]\s*["\']?)'
            r'([A-Za-z0-9_\-/.+]{16,})',
            re.I,
        ),
        _mask_keep_four,
    ),
]

# Backwards-compatible alias (the original module exposed this name).
_REDACT_PATTERNS = [p for p, _ in _REDACT_RULES]


def redact_display(text: str) -> str:
    """Mask credentials in *text* before it is shown in the terminal.

    Keeps a short prefix of each secret for debuggability (``nvapi-****``)
    and leaves ordinary text and Rich markup untouched. Cheap enough to
    run on every displayed string (compiled regexes, single pass per rule).
    """
    if not text:
        return text
    for pattern, repl in _REDACT_RULES:
        text = pattern.sub(repl, text)
    return text

# ============================================================================
# APPROVAL MODES
# ============================================================================

class ApprovalMode(Enum):
    SUGGEST = "suggest"
    AUTO_EDIT = "auto-edit"
    FULL_AUTO = "full-auto"

APPROVAL_MODES = list(ApprovalMode)
_current_approval_mode = ApprovalMode.FULL_AUTO


def get_approval_mode() -> ApprovalMode:
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
    console.print(Text(f"  ⚠ {action}", style=f"bold {_c('warning')}"))
    if detail:
        console.print(Text(f"    {redact_display(detail)[:200]}", style="dim"))
    try:
        answer = console.input(Text("  lanjut? [Y/n] ", style=f"bold {_c('warning')}")).strip().lower()
        return answer in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False

# ============================================================================
# COLOR HELPER
# ============================================================================

def _c(key: str) -> str:
    return _COLORS.get(key, "#ffffff")

# ============================================================================
# STATUS BAR — Animated with activity timeline
# ============================================================================

@dataclass
class StatusBar:
    provider: str = "alibaba"
    model: str = "qwen-plus"
    approval_mode: ApprovalMode = ApprovalMode.FULL_AUTO
    context_used: int = 0
    context_total: int = 0
    session_tokens: int = 0
    cwd: str = "/root"
    current_activity: str = "🟢 Ready"
    activity_history: List[Dict] = field(default_factory=list)
    last_update: float = 0

    _CTX_WINDOWS = {
        "qwen-plus": 1_000_000, "qwen-turbo": 1_000_000, "qwen-max": 1_000_000,
        "qwen3-coder-plus": 1_000_000, "qwen3-coder-flash": 1_000_000,
        "qwen3.7-max": 1_000_000, "qwen3.7-plus": 1_000_000, "qwen3.7-flash": 1_000_000,
        "meta/llama-3.1-70b-instruct": 131_072, "meta/llama-3.1-8b-instruct": 131_072,
        "nvidia/nemotron-3-super-120b-a12b": 131_072,
        "nvidia/nemotron-3-ultra-550b-a55b": 131_072,
        "nvidia/llama-3.3-nemotron-super-49b-v1.5": 131_072,
        "nvidia/nemotron-3-nano-30b-a3b": 131_072,
        "nvidia/nvidia-nemotron-nano-9b-v2": 131_072,
        "nvidia/nemotron-mini-4b-instruct": 131_072,
        "mistralai/mistral-nemotron": 131_072,
        "mistralai/mistral-medium-3.5-128b": 131_072,
        "stepfun-ai/step-3.7-flash": 131_072,
        "deepseek-ai/deepseek-v4-flash": 131_072, "hy3": 131_072, "kimi-k3": 131_072,
        "gpt-4o": 128_000, "gpt-4o-mini": 128_000,
    }

    def _get_context_window(self) -> int:
        if self.context_total > 0:
            return self.context_total
        return self._CTX_WINDOWS.get(self.model, 131_072)

    @property
    def context_pct(self) -> int:
        total = self._get_context_window()
        if total == 0:
            return 0
        return min(100, int(self.context_used / total * 100))

    def add_activity(self, activity: str, tool: str = "") -> None:
        self.current_activity = activity
        self.activity_history.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "activity": activity,
            "tool": tool
        })
        # Keep last 5 activities
        if len(self.activity_history) > 5:
            self.activity_history = self.activity_history[-5:]
        self.last_update = time.time()

    def render_line(self) -> Text:
        ctx_remaining = 100 - self.context_pct
        ctx_color = _c("success") if ctx_remaining > 40 else _c("warning") if ctx_remaining > 15 else _c("error")

        # Animated pulse for activity
        pulse = "▓" if int(time.time() * 2) % 2 == 0 else "░"
        activity_text = self.current_activity
        if len(activity_text) > 35:
            activity_text = activity_text[:32] + "..."

        t = Text()
        t.append(" ╭", style=f"bold {_c('border')}")
        t.append(" opsora ", style=f"bold {_c('accent')}")
        t.append(f"{self.model} ", style="dim")
        t.append(f"│ {ctx_remaining}% ctx ", style=ctx_color)
        t.append(f"│ {self.approval_mode.value} ", style="dim")
        if self.session_tokens > 0:
            t.append(f"│ {self.session_tokens:,} tok ", style="dim")
        t.append(f"│ {pulse} {activity_text}", style=f"dim {_c('accent')}")
        return t

    def render_compact(self) -> Text:
        """Compact single-line version"""
        ctx_remaining = 100 - self.context_pct
        ctx_color = _c("success") if ctx_remaining > 40 else _c("warning") if ctx_remaining > 15 else _c("error")
        
        t = Text()
        t.append(" ● ", style=f"bold {_c('accent')}")
        t.append("opsora ", style="bold")
        t.append(f"{self.model} ", style="dim")
        t.append(f"{ctx_remaining}%ctx ", style=ctx_color)
        t.append(f"{self.approval_mode.value} ", style="dim")
        if self.session_tokens > 0:
            t.append(f"· {self.session_tokens:,}tok ", style="dim")
        t.append(f"· {self.current_activity}", style="dim")
        return t


# ============================================================================
# STREAMING MARKDOWN — With cursor and smooth animation
# ============================================================================

def stream_markdown(text: str, speed: float = 0.005) -> None:
    """Smooth streaming with blinking cursor"""
    if not text or not text.strip():
        return
    text = redact_display(text)
    
    cursor_chars = ["▌", "▐", "▄", "▀"]
    cursor_idx = 0
    
    try:
        with Live(refresh_per_second=30, auto_refresh=True, transient=True) as live:
            out = ""
            for i, char in enumerate(text):
                out += char
                if i % 2 == 0:
                    cursor = cursor_chars[cursor_idx % 4]
                    cursor_idx += 1
                else:
                    cursor = ""
                live.update(Markdown(out + cursor))
                if i % 3 == 0:
                    time.sleep(speed)
            live.update(Markdown(out.strip()))
    except Exception:
        try:
            with console.status("Thinking…", spinner="dots") as status:
                time.sleep(0.2)
            console.print(Markdown(text))
        except Exception:
            console.print(text)


# ============================================================================
# TOOL CALL DISPLAY — Rich visual hierarchy
# ============================================================================

_TOOL_ICONS = {
    "read_file": "📄", "write_file": "✏️", "edit_file": "🔧",
    "run_command": "▶", "aws_command": "☁️", "memory_add": "🧠",
    "memory_search": "🔍", "graphify_query": "🕸", "workspace_status": "📊",
    "grep_search": "🔎", "glob_search": "📁", "web_fetch": "🌐",
    "list_directory": "📂", "subagent_spawn": "🤖", "todo_write": "📋",
    "git_diff": "📝", "git_status": "🔀", "git_log": "📜", "run_tests": "🧪",
    "git_commit": "📦", "lint_check": "🔍", "image_read": "🖼️", "pip_info": "📋",
    "web_search": "🌐", "db_query": "🗄️", "http_request": "📡",
}

_ERROR_PATTERNS = [
    "error", "failed", "traceback", "not found", "denied",
    "exception", "modulenotfound", "importerror", "permission",
    "timeout", "refused", "no such", "blocked", "cannot",
]


def _is_error_output(output: str) -> bool:
    lower = output.lower()
    return any(pat in lower for pat in _ERROR_PATTERNS)


def render_tool_call(name: str, args: dict[str, Any], output: str, elapsed: float = 0) -> None:
    """Rich tool call visualization with bordered output for errors"""
    icon = _TOOL_ICONS.get(name, "⚙")
    has_output = bool(output and output.strip())
    if has_output:
        output = redact_display(output)
    is_error = has_output and _is_error_output(output)

    # Format args (redact BEFORE truncating so a truncated secret cannot
    # leak its leading characters)
    args_parts = []
    for k, v in args.items():
        sv = redact_display(str(v))
        if len(sv) > 30:
            sv = sv[:27] + "…"
        args_parts.append(sv)
    args_str = ", ".join(args_parts)
    elapsed_str = f" {_dim(elapsed)}s" if elapsed > 0.1 else ""

    # Main line
    line = Text()
    status_icon = "💥" if is_error else "✓"
    status_color = _c('error') if is_error else _c('success')
    line.append(f"  {status_icon} ", style=f"bold {status_color}")
    line.append(f"{icon} {name}", style=f"bold {_c('accent')}")
    if args_str:
        line.append(f" ({args_str})", style="dim")
    if elapsed_str:
        line.append(elapsed_str, style="dim")

    console.print(line)

    # Show output
    if has_output:
        lines = output.strip().split("\n")
        max_lines = 20 if is_error else 10
        display_lines = lines[:max_lines]
        
        for l in display_lines:
            if is_error:
                console.print(Text(f"    │ {l[:80]}", style=f"bold {_c('error')}"))
            else:
                console.print(Text(f"    ╎ {l[:80]}", style=f"dim {_c('dim')}"))
        
        if len(lines) > max_lines:
            console.print(Text(f"    … ({len(lines)} lines total)", style="dim"))

        # For code tools, show syntax highlighted
        if name in ("read_file", "write_file", "edit_file") and not is_error:
            filepath = args.get("filepath", args.get("file_path", ""))
            if filepath and os.path.exists(filepath):
                try:
                    ext = os.path.splitext(filepath)[1]
                    lang = _detect_language(filepath)
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
                        content = fh.read(8192)
                    content = redact_display(content)[:5000]
                    console.print(Syntax(content, lang, theme="monokai", word_wrap=True, line_numbers=True))
                except:
                    pass


def _render_todo(todos: list[dict]) -> None:
    if not todos:
        return
    console.print()
    for t in todos:
        status = t.get("status", "pending")
        tid = t.get("id", "?")
        content = redact_display(str(t.get("content", "")))
        icons = {"pending": "○", "in_progress": "●", "completed": "✓"}
        styles = {"pending": "dim", "in_progress": f"bold {_c('accent')}", "completed": f"dim {_c('success')}"}
        console.print(Text(f"  {icons.get(status, '○')} [{tid}] {content}", style=styles.get(status, "dim")))
    console.print()


def _format_args(args: dict, max_len: int = 60) -> str:
    parts = [redact_display(str(v))[:30] + "…" if len(str(v)) > 30 else redact_display(str(v)) for v in args.values()]
    result = ", ".join(parts)
    return result[:max_len - 1] + "…" if len(result) > max_len else result


def _detect_language(filepath: str) -> str:
    ext_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
        ".md": "markdown", ".sh": "bash", ".bash": "bash", ".sql": "sql",
        ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby",
        ".php": "php", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".env": "bash", ".tf": "hcl",
    }
    for ext, lang in ext_map.items():
        if filepath.endswith(ext):
            return lang
    return "text"


def _dim(val: float) -> str:
    return f"{val:.1f}" if val < 10 else f"{val:.0f}"


# ============================================================================
# FILE TREE — Interactive
# ============================================================================

def render_file_tree(path: str, max_depth: int = 3, max_items: int = 50) -> None:
    from pathlib import Path as P
    root = P(path)
    if not root.is_dir():
        console.print(Text(f"  {path} bukan directory", style=_c("error")))
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
                console.print(Text(f"{prefix}{connector}{entry.name}/", style=f"bold {_c('accent')}"))
                ext = "    " if last else "│   "
                _walk(entry, prefix + ext, depth + 1)
            else:
                console.print(Text(f"{prefix}{connector}{entry.name}", style="dim"))

    console.print(Text(f"  {root.name}/", style=f"bold {_c('accent')}"))
    _walk(root, "  ", 0)


def render_file_edit(filepath: str, old_str: str, new_str: str) -> None:
    """Show compact diff — syntax highlighted inline."""
    import difflib
    diff = list(difflib.unified_diff(
        redact_display(old_str).splitlines(keepends=True),
        redact_display(new_str).splitlines(keepends=True),
        fromfile="old", tofile="new", lineterm="", n=2,
    ))
    if not diff:
        return
    diff_lines = diff[:20]
    diff_text = "\n".join(diff_lines)
    if len(diff) > 20:
        diff_text += f"\n… ({len(diff)} diff lines total)"
    console.print(Syntax(diff_text, "diff", theme="monokai", word_wrap=True))


# ============================================================================
# HELP — Beautiful sections with icons
# ============================================================================

def render_help() -> None:
    console.print()
    
    sections = [
        ("🎮 Commands", [
            ("/help", "tampilkan ini"),
            ("/status", "provider & tools status"),
            ("/models", "list semua model"),
            ("/tools", "daftar tools"),
            ("/mode", "ganti approval (Ctrl+A)"),
            ("/new", "obrolan baru"),
            ("/tree [path]", "struktur folder"),
        ]),
        ("💾 Sessions", [
            ("/sessions", "list session"),
            ("/resume <id>", "lanjutin session"),
            ("/save [nama]", "simpan session"),
            ("/fork", "fork session"),
        ]),
        ("⚡ Quick Actions", [
            ("/run <cmd>", "shell command"),
            ("/read <file>", "baca file"),
            ("/search <q>", "web search"),
            ("/query <sql>", "SQLite query"),
            ("/memory <q>", "cari memory"),
            ("/diff <a> <b>", "bandingin file"),
        ]),
        ("🧠 Skills", [
            ("/solve <problem>", "THINK→PLAN→ACT→VERIFY"),
            ("/review [path]", "review code"),
            ("/explain <file>", "explain code"),
            ("/refactor <file>", "refactor code"),
            ("/test [file]", "generate & run tests"),
            ("/deploy [target]", "deploy project"),
        ]),
        ("🎨 Settings", [
            ("/theme [name]", "ganti tema (dark/light/cyber/warm)"),
            ("/plugins", "list plugins"),
            ("/cost", "session cost & tokens"),
            ("/verbose", "toggle verbose (Ctrl+V)"),
        ]),
        ("🧠 NVIDIA AI", [
            ("/translate <text>", "translate EN↔ID"),
            ("/vision [path]", "analyze screenshot"),
            ("/safety <cmd>", "check command safety"),
            ("/embed <text>", "generate embedding"),
        ]),
        ("⌨️ Shortcuts", [
            ("Ctrl+A", "cycle approval mode"),
            ("Ctrl+T", "cycle theme"),
            ("Ctrl+V", "toggle verbose"),
            ("Ctrl+C", "interrupt/abort"),
            ("Tab", "auto-complete"),
            ("↑/↓", "history"),
        ]),
    ]

    for title, items in sections:
        console.print()
        console.print(Text(f"  {title}", style=f"bold {_c('accent')}"))
        for cmd, desc in items:
            console.print(Text(f"  {cmd:<22}", style=f"bold {_c('accent')}"), Text(desc, style="dim"))
    console.print()


# ============================================================================
# WELCOME SCREEN — Rich with provider health
# ============================================================================

def print_welcome(model: str, tools_count: int, approval: ApprovalMode, provider: str = "alibaba") -> None:
    console.print()
    
    # Animated logo
    logo = [
        "  ██████╗ ██╗   ██╗ ██████╗ ██████╗ ███████╗███╗   ██╗",
        "  ██╔══██╗╚██╗ ██╔╝██╔════╝ ██╔══██╗██╔════╝████╗  ██║",
        "  ██████╔╝ ╚████╔╝ ██║     ██████╔╝█████╗  ██╔██╗ ██║",
        "  ██╔═══╝   ╚██╔╝  ██║     ██╔═══╝ ██╔══╝  ██║╚██╗██║",
        "  ██║        ██║  ███████╗██║     ███████╗██║ ╚████║",
        "  ╚═╝        ╚═╝  ╚══════╝╚═╝     ╚══════╝╚═╝  ╚═══╝",
    ]
    
    for line in logo:
        console.print(Text(line, style=f"bold {_c('accent')}"))
    
    console.print()
    
    # Provider health cards
    providers = [
        ("NVIDIA NIM", "nvidia", ["nemotron-3-ultra", "deepseek-v4-flash", "llama-3.1-70b"]),
        ("Alibaba DashScope", "alibaba", ["qwen-max", "qwen3-coder-plus", "qwen3.7-max"]),
        ("OpenRouter", "openrouter", ["gpt-4o", "claude-3.5-sonnet", "gemini-1.5-pro"]),
        ("AWS Bedrock", "bedrock", ["nova-pro", "nova-lite", "claude-3-haiku"]),
        ("Local (Ollama)", "local", ["llama3.1", "qwen2.5", "codellama"]),
    ]
    
    console.print(Text("  ┌─ Provider Health ─────────────────────────────┐", style=_c("border")))
    for name, key, models in providers:
        avail = is_provider_available(key) if 'is_provider_available' in globals() else True
        status = "🟢" if avail else "🔴"
        model_list = ", ".join(models[:3])
        console.print(Text(f"  │ {status} {name:<20} {model_list}", style="dim" if not avail else ""))
    console.print(Text(f"  └──────────────────────────────────────────────┘", style=_c("border")))
    
    console.print()
    console.print(Text(f"  {tools_count} tools · {model} · {get_approval_mode().value} mode", style="dim"))
    console.print(Text("  /help untuk commands · /status untuk detail · Tab untuk autocomplete", style="dim"))
    console.print()


def is_provider_available(provider: str) -> bool:
    env_keys = {
        "nvidia": "NVIDIA_API_KEY",
        "alibaba": "DASHSCOPE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "bedrock": "AWS_PROFILE",
        "local": None,
    }
    key = env_keys.get(provider)
    if key is None:
        return True
    return bool(os.environ.get(key))


# ============================================================================
# CODEX-STYLE INPUT — Full screen with live status
# ============================================================================

class SlashCompleter(Completer):
    """Smart auto-complete for slash commands and models"""
    
    def __init__(self, get_models_fn=None):
        self._commands = [
            ("/help", "show help"),
            ("/status", "provider & tools status"),
            ("/models", "list all models"),
            ("/tools", "list tools"),
            ("/mode", "switch approval mode"),
            ("/new", "new conversation"),
            ("/tree", "folder structure"),
            ("/sessions", "session list"),
            ("/resume", "resume session"),
            ("/save", "save session"),
            ("/fork", "fork session"),
            ("/run", "run shell command"),
            ("/read", "read file"),
            ("/search", "web search"),
            ("/query", "SQL query"),
            ("/memory", "search memory"),
            ("/diff", "diff files"),
            ("/solve", "problem solver"),
            ("/review", "code review"),
            ("/explain", "explain code"),
            ("/refactor", "refactor code"),
            ("/test", "generate tests"),
            ("/fix-ci", "fix CI"),
            ("/deploy", "deploy project"),
            ("/theme", "change theme"),
            ("/plugins", "list plugins"),
            ("/cost", "session cost"),
            ("/verbose", "toggle verbose"),
            ("/translate", "translate text"),
            ("/vision", "analyze image"),
            ("/safety", "check command"),
            ("/embed", "generate embedding"),
            ("/copy", "copy to clipboard"),
            ("/fork", "fork session"),
            ("/clear", "clear screen"),
            ("/exit", "exit"),
        ]
        self._get_models = get_models_fn
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/'):
            return
        
        parts = text[1:].split(' ', 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        
        # Model completion: /model provider/model
        if cmd == "model":
            if rest.endswith("/") or "/" in rest:
                prov = rest.split("/")[0]
                partial = rest.split("/", 1)[1] if "/" in rest else ""
                # Would need dynamic model list
            else:
                for prov in ["nvidia", "alibaba", "openrouter", "bedrock", "local", "tokenhub"]:
                    if prov.startswith(rest.lower()):
                        yield Completion(f"/model {prov}/", start_position=-len(text), display_meta=f"provider")
            return
        
        # Theme completion
        if cmd == "theme":
            for t in get_theme_names():
                if t.startswith(rest.lower()):
                    yield Completion(f"/theme {t}", start_position=-len(text), display_meta=THEMES[t]["name"])
            return
        
        # Default command completion
        word = cmd
        for c, desc in self._commands:
            if c.startswith("/" + word) or word == "":
                yield Completion(c, start_position=-len(text), display_meta=desc)


def codex_prompt(
    provider: str = "alibaba",
    model: str = "qwen-plus",
    approval: str = "full-auto",
    ctx_pct: int = 0,
    tokens: int = 0,
    completer=None,
) -> str:
    """Full-screen bordered input with live status bar"""
    import sys as _sys
    
    if not _sys.stdin.isatty():
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return "__EXIT__"
    
    if completer is None:
        completer = SlashCompleter()
    
    buf = Buffer(name="input", completer=completer, complete_while_typing=True, multiline=False)
    
    accent = _c("accent")
    dim_c = _c("dim")
    border_c = _c("border")
    bg_c = _c("bg")
    
    ctx_remaining = 100 - ctx_pct
    ctx_color = _c("success") if ctx_remaining > 40 else _c("warning") if ctx_remaining > 15 else _c("error")
    tokens_str = f"{tokens:,}tok" if tokens > 0 else ""
    
    status_text = FormattedText([
        (f"fg:{accent} bg:{bg_c}", f" {provider}:{model} "),
        (f"fg:{border_c} bg:{bg_c}", " │ "),
        (f"fg:{ctx_color} bg:{bg_c}", f"{ctx_remaining}% ctx "),
        (f"fg:{border_c} bg:{bg_c}", "│ "),
        (f"fg:{dim_c} bg:{bg_c}", tokens_str),
        (f"fg:{border_c} bg:{bg_c}", " │ "),
        (f"fg:{dim_c} bg:{bg_c}", f"{approval} "),
    ])
    
    input_line = Window(
        content=BufferControl(buffer=buf, focusable=True),
        height=Dimension.exact(1),
        style=f"bg:{bg_c} fg:{_c('text')}",
    )
    
    status_bar = Window(
        content=FormattedTextControl(status_text),
        height=Dimension.exact(1),
        style=f"bg:{bg_c} fg:{dim_c}",
    )
    
    layout = Layout(HSplit([
        Window(height=Dimension.exact(1), char="═", style=f"fg:{accent} bg:{bg_c}"),
        input_line,
        Window(height=Dimension.exact(1), char="═", style=f"fg:{accent} bg:{bg_c}"),
        status_bar,
        Window(height=Dimension.exact(1), char="═", style=f"fg:{accent} bg:{bg_c}"),
    ]))
    
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
        new_mode = cycle_approval_mode()
        event.app.invalidate()
    
    @kb.add("c-t")
    def _cycle_theme(event):
        themes = get_theme_names()
        current = get_current_theme()
        idx = themes.index(current)
        apply_theme(themes[(idx + 1) % len(themes)])
        event.app.invalidate()
    
    @kb.add("c-v")
    def _toggle_verbose(event):
        toggle_verbose()
        event.app.invalidate()
    
    style = PTStyle.from_dict({
        "window.border": f"fg:{border_c} bg:{bg_c}",
        "focused": f"bg:{bg_c} fg:{accent}",
    })
    
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
        enable_page_navigation_bindings=False,
    )
    
    result = app.run()
    return result or ""


# ============================================================================
# PRINT FUNCTIONS
# ============================================================================

def _print_welcome_banner() -> None:
    """Alternative simple welcome for quick startup"""
    console.print()
    console.print(Text("  ╔══════════════════════════════════════════════════╗", style=f"bold {_c('accent')}"))
    console.print(Text("  ║                  OPSORA v3.2                       ║", style=f"bold {_c('accent')}"))
    console.print(Text("  ║       Multi-Provider AI Coding Agent              ║", style=f"bold {_c('accent')}"))
    console.print(Text("  ╚══════════════════════════════════════════════════╝", style=f"bold {_c('accent')}"))
    console.print()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "console", "redact_display", "ApprovalMode", "get_approval_mode", "set_approval_mode",
    "cycle_approval_mode", "needs_approval", "prompt_approval", "get_approval_mode",
    "StatusBar", "stream_markdown", "render_tool_call", "render_file_tree",
    "render_file_edit", "render_help", "print_welcome", "print_welcome_banner",
    "codex_prompt", "toggle_verbose", "is_verbose", "apply_theme", "get_theme_names",
    "get_current_theme", "set_theme_colors", "THEMES", "_c", "_COLORS",
    "render_tool_call", "render_file_edit", "render_help", "print_welcome",
]