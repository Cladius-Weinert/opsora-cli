"""Tests for the Opsora theme system (opsora_themes) — palette contract.

Every theme must satisfy WCAG contrast minima so text is readable on
narrow Android/Termux terminals. The test suite guards against accidental
regressions when palettes are tuned.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

from opsora_themes import (
    THEMES,
    THEME_KEYS,
    contrast_ratio,
    relative_luminance,
    get_theme,
    list_themes,
)


# ---------------------------------------------------------------------------
# Palette structure
# ---------------------------------------------------------------------------

class TestPaletteStructure:
    """Every theme must provide all required color roles (task TH1)."""

    def test_four_themes_exist(self):
        assert len(THEMES) == 4
        assert set(THEMES.keys()) == {"dark", "light", "cyber", "warm"}

    def test_each_theme_has_all_keys(self):
        for name, theme in THEMES.items():
            missing = set(THEME_KEYS) - set(theme.keys())
            assert not missing, f"Theme {name!r} missing keys: {missing}"

    def test_each_theme_has_name_and_description(self):
        for name, theme in THEMES.items():
            assert "name" in theme, f"Theme {name!r} missing 'name'"
            assert "description" in theme, f"Theme {name!r} missing 'description'"
            assert isinstance(theme["name"], str) and theme["name"]
            assert isinstance(theme["description"], str) and theme["description"]

    def test_all_color_values_are_valid_hex(self):
        for name, theme in THEMES.items():
            for key in THEME_KEYS:
                val = theme[key]
                assert val.startswith("#") and len(val) == 7, (
                    f"Theme {name!r} key {key!r} has invalid hex: {val!r}"
                )
                # Verify it parses
                r = int(val[1:3], 16)
                g = int(val[3:5], 16)
                b = int(val[5:7], 16)
                assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255


# ---------------------------------------------------------------------------
# WCAG contrast contract
# ---------------------------------------------------------------------------

class TestContrastContract:
    """All themes must meet minimum WCAG contrast ratios (task TH2)."""

    @pytest.mark.parametrize("theme_name", ["dark", "light", "cyber", "warm"])
    def test_dim_against_bg_aa(self, theme_name):
        """dim text must be >= 4.5:1 against bg (WCAG AA)."""
        t = THEMES[theme_name]
        cr = contrast_ratio(t["dim"], t["bg"])
        assert cr >= 4.5, (
            f"Theme {theme_name!r}: dim({t['dim']}) vs bg({t['bg']}) "
            f"= {cr:.2f}:1, need >= 4.5"
        )

    @pytest.mark.parametrize("theme_name", ["dark", "light", "cyber", "warm"])
    def test_secondary_against_bg_aa(self, theme_name):
        """secondary text must be >= 4.5:1 against bg (WCAG AA)."""
        t = THEMES[theme_name]
        cr = contrast_ratio(t["secondary"], t["bg"])
        assert cr >= 4.5, (
            f"Theme {theme_name!r}: secondary({t['secondary']}) vs bg({t['bg']}) "
            f"= {cr:.2f}:1, need >= 4.5"
        )

    @pytest.mark.parametrize("theme_name", ["dark", "light", "cyber", "warm"])
    def test_fg_against_bg_aaa(self, theme_name):
        """fg (body text) must be >= 7.0:1 against bg (WCAG AAA)."""
        t = THEMES[theme_name]
        cr = contrast_ratio(t["fg"], t["bg"])
        assert cr >= 7.0, (
            f"Theme {theme_name!r}: fg({t['fg']}) vs bg({t['bg']}) "
            f"= {cr:.2f}:1, need >= 7.0"
        )

    @pytest.mark.parametrize("theme_name", ["dark", "light", "cyber", "warm"])
    def test_status_fg_against_status_bg_aa(self, theme_name):
        """status_fg must be >= 4.5:1 against status_bg (WCAG AA)."""
        t = THEMES[theme_name]
        cr = contrast_ratio(t["status_fg"], t["status_bg"])
        assert cr >= 4.5, (
            f"Theme {theme_name!r}: status_fg({t['status_fg']}) vs "
            f"status_bg({t['status_bg']}) = {cr:.2f}:1, need >= 4.5"
        )

    @pytest.mark.parametrize("theme_name", ["dark", "light", "cyber", "warm"])
    def test_accent_against_bg_minimal(self, theme_name):
        """accent must be >= 3.0:1 against bg (minimum for large text)."""
        t = THEMES[theme_name]
        cr = contrast_ratio(t["accent"], t["bg"])
        assert cr >= 3.0, (
            f"Theme {theme_name!r}: accent({t['accent']}) vs bg({t['bg']}) "
            f"= {cr:.2f}:1, need >= 3.0"
        )


# ---------------------------------------------------------------------------
# Specific known-good / known-bad contrast values (task TH3)
# ---------------------------------------------------------------------------

class TestKnownContrastValues:
    """Document specific contrast values to prevent regressions."""

    def test_old_broken_dim_is_below_threshold(self):
        """The OLD dim (#666666) on dark bg (#1a1a2e) fails AA — documents the fix."""
        cr = contrast_ratio("#666666", "#1a1a2e")
        assert cr < 4.5, (
            f"Old dim #666666 on #1a1a2e = {cr:.2f}:1 — should be below 4.5"
        )

    def test_malformed_input_returns_one(self):
        """Malformed hex colors yield 1.0 (no contrast) instead of crashing."""
        assert contrast_ratio("bad", "#ffffff") == 1.0
        assert contrast_ratio("#ffffff", "bad") == 1.0
        assert contrast_ratio("", "") == 1.0
        assert contrast_ratio("#xyz", "#000000") == 1.0


# ---------------------------------------------------------------------------
# Single source of truth — opsora_tui derives its view (task TH1)
# ---------------------------------------------------------------------------

class TestSingleSource:
    """opsora_tui must consume opsora_themes, not keep its own palette."""

    def test_classic_themes_derived_from_opsora_themes(self):
        import opsora_tui
        assert set(opsora_tui.THEMES) == set(THEMES)
        for name, flat in THEMES.items():
            nested = opsora_tui.THEMES[name]
            assert nested["name"] == flat["name"]
            for key in THEME_KEYS:
                assert nested["colors"][key] == flat[key], (
                    f"opsora_tui THEMES[{name!r}][{key!r}] diverged from "
                    f"opsora_themes — two palettes with the same name again")

    def test_classic_apply_theme_switches_colors(self):
        import opsora_tui
        try:
            assert opsora_tui.apply_theme("warm") is True
            assert opsora_tui._c("accent") == THEMES["warm"]["accent"]
            assert opsora_tui.get_current_theme() == "warm"
            assert opsora_tui.apply_theme("nope") is False
        finally:
            opsora_tui.apply_theme("dark")

    def test_classic_set_theme_colors_merges_partial(self):
        import opsora_tui
        try:
            opsora_tui.apply_theme("dark")
            opsora_tui.set_theme_colors({"accent": "#123456"})
            assert opsora_tui._c("accent") == "#123456"
            # other roles untouched
            assert opsora_tui._c("dim") == THEMES["dark"]["dim"]
        finally:
            opsora_tui.apply_theme("dark")

    def test_apply_theme_replaces_not_merges(self):
        """Switching themes must not leak keys from the previous palette."""
        import opsora_tui
        try:
            opsora_tui.apply_theme("dark")
            opsora_tui.set_theme_colors({"legacy_key_only_dark": "#010101"})
            opsora_tui.apply_theme("light")
            # _c falls back to #ffffff for keys absent from the new palette
            assert opsora_tui._c("legacy_key_only_dark") == "#ffffff"
        finally:
            opsora_tui.apply_theme("dark")

    def test_light_status_bar_not_invisible_anymore(self):
        """TH4 regression guard: light status bg must differ from dim text."""
        t = THEMES["light"]
        assert t["status_bg"].lower() != "#999999"
        assert t["status_bg"].lower() != t["dim"].lower()

    def test_cyber_no_longer_hostile(self):
        """TH5: no pure #00ff00 body, no #005500 dim, no #ff00ff accent."""
        t = THEMES["cyber"]
        assert t["fg"].lower() != "#00ff00"
        assert t["dim"].lower() != "#005500"
        assert t["accent"].lower() != "#ff00ff"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_relative_luminance_known_values(self):
        """Known WCAG relative luminance values."""
        # Pure black
        assert relative_luminance("#000000") == 0.0
        # Pure white
        assert relative_luminance("#ffffff") == 1.0
        # Mid-gray (#808080) — approximate
        lum = relative_luminance("#808080")
        assert 0.2 < lum < 0.22

    def test_relative_luminance_malformed(self):
        assert relative_luminance("nothex") == 0.0
        assert relative_luminance("#fff") == 0.0  # short form
        assert relative_luminance("#gggggg") == 0.0  # invalid hex

    def test_contrast_ratio_black_white(self):
        """Black on white = 21.0:1 (maximum)."""
        cr = contrast_ratio("#000000", "#ffffff")
        assert abs(cr - 21.0) < 0.01

    def test_contrast_ratio_identical(self):
        """Same color = 1.0:1 (no contrast)."""
        cr = contrast_ratio("#5fb8c0", "#5fb8c0")
        assert abs(cr - 1.0) < 0.01

    def test_get_theme_returns_dict(self):
        theme = get_theme("dark")
        assert isinstance(theme, dict)
        assert theme["name"] == "Dark Ocean"

    def test_get_theme_unknown_falls_back_to_dark(self):
        theme = get_theme("nonexistent")
        assert theme["name"] == "Dark Ocean"

    def test_list_themes(self):
        names = list_themes()
        assert names == ["dark", "light", "cyber", "warm"]