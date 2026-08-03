"""Opsora Themes — Color themes for the TUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "name": "Dark (Default)",
        "bg": "#1a1a2e", "fg": "#e0e0e0", "accent": "#00ffff",
        "success": "#00ff88", "warning": "#ffaa00", "error": "#ff4444",
        "dim": "#666666", "prompt": "#00ffff", "border": "#444444",
        "tool_call": "#ffdd00", "code_bg": "#0d1117",
    },
    "light": {
        "name": "Light",
        "bg": "#ffffff", "fg": "#333333", "accent": "#0066cc",
        "success": "#008844", "warning": "#cc8800", "error": "#cc0000",
        "dim": "#999999", "prompt": "#0066cc", "border": "#cccccc",
        "tool_call": "#886600", "code_bg": "#f6f8fa",
    },
    "cyber": {
        "name": "Cyberpunk",
        "bg": "#0a0a0a", "fg": "#00ff00", "accent": "#ff00ff",
        "success": "#00ff00", "warning": "#ffff00", "error": "#ff0000",
        "dim": "#005500", "prompt": "#ff00ff", "border": "#00ff00",
        "tool_call": "#ffff00", "code_bg": "#0a0a0a",
    },
    "warm": {
        "name": "Warm Sunset",
        "bg": "#2d2a24", "fg": "#e8d5b7", "accent": "#ff8c42",
        "success": "#7ec882", "warning": "#f0c040", "error": "#e85050",
        "dim": "#8a7a6a", "prompt": "#ff8c42", "border": "#5a4a3a",
        "tool_call": "#f0c040", "code_bg": "#1e1b17",
    },
}

_THEME_PATH = Path("/root/.opsora/theme.json")


def get_theme(name: str = "dark") -> dict[str, str]:
    return THEMES.get(name, THEMES["dark"])


def list_themes() -> list[str]:
    return list(THEMES.keys())


def apply_theme(theme: dict[str, str]) -> dict[str, Any]:
    """Return prompt_toolkit Style dict from theme."""
    return {
        "prompt": f"bold {theme.get('prompt', '#00ffff')}",
        "toolbar": f"bg:{theme.get('bg', '#1a1a2e')} {theme.get('dim', '#666666')}",
        "border": theme.get("border", "#444444"),
        "accent": theme.get("accent", "#00ffff"),
        "success": theme.get("success", "#00ff88"),
        "warning": theme.get("warning", "#ffaa00"),
        "error": theme.get("error", "#ff4444"),
        "dim": theme.get("dim", "#666666"),
        "fg": theme.get("fg", "#e0e0e0"),
    }


def save_theme_preference(name: str) -> None:
    _THEME_PATH.parent.mkdir(parents=True, exist_ok=True)
    _THEME_PATH.write_text(json.dumps({"theme": name}), encoding="utf-8")


def load_theme_preference() -> str:
    if _THEME_PATH.is_file():
        try:
            data = json.loads(_THEME_PATH.read_text(encoding="utf-8"))
            return data.get("theme", "dark")
        except (json.JSONDecodeError, OSError):
            pass
    return "dark"
