"""Tests for credential redaction in the TUI display layer (opsora_tui).

Covers task 5 of the Phase-1 security refactor: secrets must never reach
the terminal through stream_markdown / render_tool_call / diffs / prompts.
All secrets below are FAKE but match real-world shapes.
"""
import io
import time

import pytest

from opsora_tui import redact_display, _REDACT_PATTERNS, _MASK

# ---------------------------------------------------------------------------
# Fake secrets — same shapes as real provider credentials, zero real values
# ---------------------------------------------------------------------------

FAKE_NVAPI = "nvapi-" + "FakeNvKey0123456789" * 3          # NVIDIA NIM (nvapi-<64>)
FAKE_SK = "sk-" + "FakeOpenAIKey0123456789" * 2             # OpenAI-style sk-...
FAKE_SK_WS = "sk-ws-" + "FakeDashScopeKey012345" * 3       # DashScope sk-ws- style
FAKE_SK_PROJ = "sk-proj-" + "FakeOpenAIProjKey0123" * 2    # OpenAI project key
FAKE_XAI = "xai-" + "FakeXaiGrokKey012345678" * 2          # xAI Grok
FAKE_GHP = "ghp_" + "FakeGitHubClassicPAT01" * 2           # GitHub classic PAT
FAKE_GH_PAT = "github_pat_" + "FakeFineGrainedTok01" * 3   # GitHub fine-grained PAT
FAKE_XOXB = "xoxb-" + "FakeSlackBotTokenValue" * 2         # Slack bot token shape (letters-only so push scanners don't flag the fake)
FAKE_BEARER = "Bearer " + "fake-bearer-token_value.0123456789"
FAKE_AIZA = "AIza" + "FakeGoogleKey0123456789_-x"          # Google API key
FAKE_LTAI = "LTAI" + "5tFakeAlibabaKeyId01234"             # Alibaba access key id
FAKE_TG_BOT = "123456789:FakeTelegramBotToken0123456789abc"  # Telegram bot token
FAKE_RND = "rnd_" + "FakeRenderKey0123456789" * 2          # Render key
FAKE_GENERIC = "FakeGenericApiKeyValue0123456789"          # for key=value fallback

ALL_PREFIXED_SECRETS = [
    FAKE_NVAPI, FAKE_SK, FAKE_SK_WS, FAKE_SK_PROJ, FAKE_XAI,
    FAKE_GHP, FAKE_GH_PAT, FAKE_XOXB, FAKE_AIZA, FAKE_LTAI,
    FAKE_TG_BOT, FAKE_RND,
]


# ---------------------------------------------------------------------------
# Provider token shapes are masked
# ---------------------------------------------------------------------------


class TestProviderTokenRedaction:
    @pytest.mark.parametrize("secret,masked", [
        (FAKE_NVAPI, "nvapi-****"),
        (FAKE_SK, "sk-****"),
        (FAKE_SK_WS, "sk-ws-****"),
        (FAKE_SK_PROJ, "sk-proj-****"),
        (FAKE_XAI, "xai-****"),
        (FAKE_GHP, "ghp_****"),
        (FAKE_GH_PAT, "github_pat_****"),
        (FAKE_XOXB, "xoxb-****"),
        (FAKE_AIZA, "AIza****"),
        (FAKE_LTAI, "LTAI****"),
        (FAKE_TG_BOT, "123456789:****"),
        (FAKE_RND, "rnd_****"),
    ])
    def test_secret_masked_keeps_prefix(self, secret, masked):
        assert redact_display(secret) == masked

    @pytest.mark.parametrize("secret", ALL_PREFIXED_SECRETS)
    def test_secret_absent_from_output(self, secret):
        assert secret not in redact_display(f"key is {secret} ok")

    def test_bearer_token_masked(self):
        out = redact_display(f"Authorization: {FAKE_BEARER}")
        assert "fake-bearer-token_value.0123456789" not in out
        assert "Bearer ****" in out

    def test_bearer_case_insensitive(self):
        out = redact_display("bearer " + "fake-bearer-token_value.0123456789")
        assert "fake-bearer-token_value" not in out


class TestGenericKeyValueRedaction:
    def test_env_style_assignment(self):
        out = redact_display(f"API_KEY={FAKE_GENERIC}")
        assert FAKE_GENERIC not in out
        assert out == "API_KEY=Fake****"

    def test_json_style_keeps_quotes(self):
        out = redact_display(f'"client_secret": "{FAKE_GENERIC}"')
        assert FAKE_GENERIC not in out
        assert out == '"client_secret": "Fake****"'

    def test_password_field(self):
        out = redact_display(f"password={FAKE_GENERIC}")
        assert FAKE_GENERIC not in out
        assert "Fake****" in out

    def test_bare_token_name(self):
        out = redact_display(f"DISCORD_TOKEN={FAKE_GENERIC}")
        assert FAKE_GENERIC not in out

    def test_access_key_secret_shape(self):
        # Alibaba-style: 30-char base64-ish value on a secret-looking name
        out = redact_display("ACCESS_KEY_SECRET=NmhNxFakeSecretValue012345678")
        assert "NmhNxFakeSecretValue012345678" not in out
        assert "NmhN****" in out

    def test_short_value_not_redacted(self):
        # < 16 chars: too short to be a real token, must pass through
        assert redact_display("api_key=short") == "api_key=short"


# ---------------------------------------------------------------------------
# Normal text and Rich markup pass through unchanged
# ---------------------------------------------------------------------------


class TestPassThrough:
    @pytest.mark.parametrize("text", [
        "Hello, world! Everything is fine.",
        "The model qwen3-coder-plus answered in 1.2s with 512 tokens.",
        "def foo():\n    return 42  # no secrets here",
        "https://opsora-landing-zeta.vercel.app/docs?section=api",
        "Error: ModuleNotFoundError — no module named 'opsora_missing'",
        "sk-shortkey is not a real key shape",
        "ghp_tooshort",
        "AIzaShort123",
        "line 123456: short note after a colon",
        "  ╭─ opsora ─╮  │ ├ └ ── status bar art",
        "100% ctx · 1,234tok · full-auto",
    ])
    def test_normal_text_unchanged(self, text):
        assert redact_display(text) == text

    @pytest.mark.parametrize("markup", [
        "[bold red]Error:[/bold red] request failed",
        "[dim]│[/dim] tool output line",
        "**bold** and _italic_ and `inline code`",
        "# Heading\n- item 1\n- item 2",
    ])
    def test_rich_and_markdown_markup_unchanged(self, markup):
        assert redact_display(markup) == markup

    def test_empty_and_none_ish(self):
        assert redact_display("") == ""

    def test_redacted_text_still_renders_in_rich(self):
        """Masked output must not break Rich rendering."""
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.text import Text

        text = redact_display(f"Auth failed: {FAKE_NVAPI} and {FAKE_BEARER}")
        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=100)
        console.print(Text(text))
        console.print(Markdown(text))
        rendered = buf.getvalue()
        assert FAKE_NVAPI not in rendered
        assert "nvapi-****" in rendered


# ---------------------------------------------------------------------------
# Composite messages, idempotency, wiring
# ---------------------------------------------------------------------------


class TestComposite:
    def test_error_message_with_multiple_secrets(self):
        msg = (
            f"AuthenticationError: Invalid API key {FAKE_SK}. "
            f"env NVIDIA_API_KEY={FAKE_NVAPI} "
            f"Authorization: {FAKE_BEARER} "
            f"telegram bot {FAKE_TG_BOT}"
        )
        out = redact_display(msg)
        for secret in (FAKE_SK, FAKE_NVAPI, FAKE_BEARER.split(" ", 1)[1], FAKE_TG_BOT):
            assert secret not in out
        assert "AuthenticationError: Invalid API key sk-****" in out
        assert "NVIDIA_API_KEY=nvapi-****" in out

    def test_idempotent(self):
        msg = f"key={FAKE_GENERIC} token {FAKE_NVAPI}"
        once = redact_display(msg)
        assert redact_display(once) == once

    def test_patterns_are_compiled_module_level(self):
        import re
        assert _REDACT_PATTERNS
        assert all(isinstance(p, re.Pattern) for p in _REDACT_PATTERNS)
        assert _MASK == "****"


class TestWiring:
    """Display choke points must redact before anything reaches console."""

    def test_render_tool_call_redacts_output(self, monkeypatch):
        import opsora_tui

        captured = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                captured.extend(args)

        monkeypatch.setattr(opsora_tui, "console", FakeConsole())
        opsora_tui.render_tool_call(
            "run_command",
            {"cmd": "deploy.sh"},
            output=f"error: invalid key {FAKE_NVAPI} rejected",
        )
        joined = "\n".join(str(c) for c in captured)
        assert FAKE_NVAPI not in joined
        assert "nvapi-****" in joined

    def test_render_tool_call_redacts_long_arg_before_truncation(self, monkeypatch):
        """A long secret passed as a tool arg must not leak its first 27 chars."""
        import opsora_tui

        captured = []

        class FakeConsole:
            def print(self, *args, **kwargs):
                captured.extend(args)

        monkeypatch.setattr(opsora_tui, "console", FakeConsole())
        opsora_tui.render_tool_call(
            "http_request",
            {"authorization": FAKE_NVAPI},  # 70 chars > 30-char arg truncation
            output="ok",
        )
        joined = "\n".join(str(c) for c in captured)
        assert FAKE_NVAPI not in joined
        assert FAKE_NVAPI[:27] not in joined
        assert "nvapi-****" in joined


# ---------------------------------------------------------------------------
# Performance sanity
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_10kb_string_stays_fast(self):
        line = "2026-08-04 10:00:00 INFO request completed in 123ms status=200 tokens=512\n"
        text = line * 140  # ~10.6 KB
        # embed secrets in the middle
        text = text[:5000] + f"\nleaked: {FAKE_NVAPI} and API_KEY={FAKE_GENERIC}\n" + text[5000:]
        assert len(text) > 10_000

        start = time.perf_counter()
        out = redact_display(text)
        elapsed = time.perf_counter() - start

        assert FAKE_NVAPI not in out
        assert FAKE_GENERIC not in out
        assert "nvapi-****" in out
        # Compiled regexes over 10KB should be milliseconds; generous bound
        # guards against catastrophic backtracking regressions.
        assert elapsed < 0.25, f"redact_display took {elapsed:.3f}s on 10KB"
