"""Opsora Themes — SINGLE source of truth for all TUI color themes.

Both UI layers consume the palettes defined here:

- ``opsora_tui_v2`` (Textual full-screen TUI) reads flat theme dicts via
  :func:`get_theme`.
- ``opsora_tui`` (classic Rich/prompt_toolkit UI) derives its nested
  ``THEMES``/``_COLORS`` view from this module instead of keeping its own
  copy (the two systems used to diverge under identical names).

Color hierarchy (do NOT use ``accent`` for everything):

- ``accent``    — reserved for primary emphasis: logo wordmark, prompt
  marker, focused input border, active model name, spinner glyph.
- ``secondary`` — muted color for supporting text (tagline, labels).
- ``dim``       — low-emphasis text; MUST hold >= 4.5:1 contrast against
  ``bg`` (WCAG AA) so it stays readable on dim phone screens.
- ``fg``        — body text, high contrast (>= 7:1 against ``bg``).
- ``status_bg``/``status_fg`` — explicit status-bar pair so light themes
  don't end up with invisible bars (bg and text used to collide).

Palettes are tuned for narrow (~50-70 col) Android/Termux terminals:
muted teal accent instead of neon, no pure-saturated body text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Color-role keys every theme must provide (used by tests to guard the
# contract; ``name``/``description`` are metadata, not colors).
THEME_KEYS = (
    "bg", "fg", "accent", "accent_bright", "secondary", "dim",
    "success", "warning", "error", "prompt", "border", "separator",
    "panel", "panel_border", "status_bg", "status_fg",
    "tool_bg", "code_bg", "header", "tool_call",
)

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "name": "Dark Ocean",
        "description": "Calm dark theme for late nights",
        "bg": "#1a1a2e", "fg": "#e6e6f0",
        "accent": "#5fb8c0", "accent_bright": "#8fd8e8",
        "secondary": "#a8b8c8", "dim": "#8b93a7",
        "success": "#6abf69", "warning": "#d4a843", "error": "#d45555",
        "prompt": "#5fb8c0", "border": "#4a4a5f", "separator": "#2a2a3e",
        "panel": "#151526", "panel_border": "#4a4a5f",
        "status_bg": "#101020", "status_fg": "#8b93a7",
        "tool_bg": "#161b22", "code_bg": "#0d1117",
        "header": "#4a8fa8", "tool_call": "#d4a843",
    },
    "light": {
        "name": "Light Paper",
        "description": "Clean light theme for daylight",
        "bg": "#ffffff", "fg": "#24292f",
        "accent": "#0070c0", "accent_bright": "#4da8da",
        "secondary": "#57606a", "dim": "#5a6167",
        "success": "#1a7f37", "warning": "#b45309", "error": "#cf222e",
        "prompt": "#0070c0", "border": "#d0d7de", "separator": "#e4e8ec",
        "panel": "#f6f8fa", "panel_border": "#c9d1d9",
        "status_bg": "#eef1f4", "status_fg": "#5a6167",
        "tool_bg": "#f6f8fa", "code_bg": "#f6f8fa",
        "header": "#0070c0", "tool_call": "#b45309",
    },
    "cyber": {
        "name": "Cyber Neon",
        "description": "High-contrast cyberpunk aesthetic",
        # Coherent take: soft mint body (not pure #00ff00), magenta accent
        # used sparingly, slate-green dim that clears WCAG AA on the bg.
        "bg": "#0a0e12", "fg": "#cde8d2",
        "accent": "#e060c8", "accent_bright": "#f090e0",
        "secondary": "#9fc0a8", "dim": "#87a08a",
        "success": "#62e88a", "warning": "#e8d062", "error": "#f2708a",
        "prompt": "#e060c8", "border": "#2a4a3a", "separator": "#16241c",
        "panel": "#0d1318", "panel_border": "#2a4a3a",
        "status_bg": "#0b1015", "status_fg": "#87a08a",
        "tool_bg": "#10161c", "code_bg": "#0c1014",
        "header": "#e060c8", "tool_call": "#e8d062",
    },
    "warm": {
        "name": "Warm Sunset",
        "description": "Cozy warm tones for comfort",
        "bg": "#2d2a24", "fg": "#e8d5b7",
        "accent": "#ff8c42", "accent_bright": "#ff9a5c",
        "secondary": "#c8b494", "dim": "#a89888",
        "success": "#7ec882", "warning": "#f0c040", "error": "#e85050",
        "prompt": "#ff8c42", "border": "#5a4a3a", "separator": "#3a342c",
        "panel": "#262320", "panel_border": "#5a4a3a",
        "status_bg": "#221f1a", "status_fg": "#a89888",
        "tool_bg": "#292524", "code_bg": "#1e1b17",
        "header": "#f97316", "tool_call": "#f0c040",
    },
}

_THEME_PATH = Path("/root/.opsora/theme.json")


def get_theme(name: str = "dark") -> dict[str, str]:
    return THEMES.get(name, THEMES["dark"])


def list_themes() -> list[str]:
    return list(THEMES.keys())


def apply_theme(theme: dict[str, str]) -> dict[str, Any]:
    """Return prompt_toolkit Style dict from a flat theme (compat helper)."""
    return {
        "prompt": f"bold {theme.get('prompt', '#5fb8c0')}",
        "toolbar": f"bg:{theme.get('bg', '#1a1a2e')} {theme.get('dim', '#8b93a7')}",
        "border": theme.get("border", "#4a4a5f"),
        "accent": theme.get("accent", "#5fb8c0"),
        "success": theme.get("success", "#6abf69"),
        "warning": theme.get("warning", "#d4a843"),
        "error": theme.get("error", "#d45555"),
        "dim": theme.get("dim", "#8b93a7"),
        "fg": theme.get("fg", "#e6e6f0"),
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


# ---------------------------------------------------------------------------
# WCAG contrast helpers — used to keep dim/secondary text readable (>= 4.5:1)
# and by the test-suite to guard the palette contract.
# ---------------------------------------------------------------------------

def _channel_linear(value: float) -> float:
    """sRGB channel (0..1) -> linear-light value."""
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a ``#rrggbb`` color (0.0 .. 1.0).

    Returns 0.0 for malformed input so callers never raise on bad data.
    """
    if not isinstance(hex_color, str):
        return 0.0
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return 0.0
    try:
        r = int(hex_color[0:2], 16) / 255
        g = int(hex_color[2:4], 16) / 255
        b = int(hex_color[4:6], 16) / 255
    except ValueError:
        return 0.0
    return 0.2126 * _channel_linear(r) + 0.7152 * _channel_linear(g) + 0.0722 * _channel_linear(b)


def _is_valid_hex(hex_color: Any) -> bool:
    """True when *hex_color* is a parseable ``#rrggbb`` string."""
    if not isinstance(hex_color, str):
        return False
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return False
    try:
        int(hex_color, 16)
    except ValueError:
        return False
    return True


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG contrast ratio between two hex colors (1.0 .. 21.0).

    >= 4.5 is the AA minimum for normal text; >= 7.0 is AAA. Malformed
    input yields 1.0 (no contrast) rather than an exception or a bogus
    maximum — a safe neutral for callers that feed untrusted values.
    """
    if not _is_valid_hex(color_a) or not _is_valid_hex(color_b):
        return 1.0
    lum_a = relative_luminance(color_a)
    lum_b = relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)
