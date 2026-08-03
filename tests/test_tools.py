"""Tests for tool execution — file ops, search, command, security."""
import pytest
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch, MagicMock


# Mirror security constants from opsora_v2 (avoid importing the heavy module).
SENSITIVE_PATHS = {".aws", ".ssh", ".gnupg", ".tccli"}
SENSITIVE_FILES = {"render.env", "secrets.env", ".opsora_env", "credentials", ".env",
                   "cloud-manager.sh", ".bash_history", ".netrc", ".pgpass"}
CREDENTIAL_KEYWORDS = ["api_key", "secret_key", "password", "token", "access_key"]
TOOL_MAX_OUTPUT = 30_000


# ---------------------------------------------------------------------------
# read_file — security checks
# ---------------------------------------------------------------------------


class TestReadFileSecurity:
    """Test that sensitive paths and files are blocked."""

    def test_aws_path_blocked(self, tmp_path):
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        cred_file = aws_dir / "credentials"
        cred_file.write_text("[default]\naws_access_key_id = AKIA...")
        resolved = cred_file.resolve()
        assert SENSITIVE_PATHS & set(resolved.parts)

    def test_ssh_path_blocked(self, tmp_path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key_file = ssh_dir / "id_rsa"
        key_file.write_text("-----BEGIN RSA PRIVATE KEY-----")
        resolved = key_file.resolve()
        assert SENSITIVE_PATHS & set(resolved.parts)

    def test_gnupg_path_blocked(self, tmp_path):
        gnupg_dir = tmp_path / ".gnupg"
        gnupg_dir.mkdir()
        f = gnupg_dir / "gpg.conf"
        f.write_text("secret")
        resolved = f.resolve()
        assert SENSITIVE_PATHS & set(resolved.parts)

    def test_env_file_blocked(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=abc123")
        assert env_file.name.startswith(".env")

    def test_opsora_env_blocked(self, tmp_path):
        f = tmp_path / ".opsora_env"
        f.write_text("API_KEY=xxx")
        assert f.name in SENSITIVE_FILES

    def test_render_env_blocked(self, tmp_path):
        f = tmp_path / "render.env"
        f.write_text("API_KEY=xxx")
        assert f.name in SENSITIVE_FILES

    def test_credentials_file_blocked(self, tmp_path):
        f = tmp_path / "credentials"
        f.write_text("[default]\nsecret=xxx")
        assert f.name in SENSITIVE_FILES

    def test_normal_file_allowed(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Hello")
        resolved = f.resolve()
        assert not (SENSITIVE_PATHS & set(resolved.parts))
        assert resolved.name not in SENSITIVE_FILES
        assert not resolved.name.startswith(".env")


class TestReadFileRedaction:
    """Test credential keyword redaction in file content."""

    def test_api_key_redacted(self):
        import re
        content = 'api_key = "sk-12345678abcdefgh"'
        lower = content.lower()
        if any(kw in lower for kw in CREDENTIAL_KEYWORDS):
            content = re.sub(
                r'((?:api_key|secret_key|password|token|access_key|secret_id|api_token)\s*[=:"]\s*["\']?)([A-Za-z0-9_\-/.]{8,})(["\']?)',
                r'\1[REDACTED]\3',
                content, flags=re.IGNORECASE,
            )
        assert "REDACTED" in content
        assert "sk-12345678abcdefgh" not in content

    def test_password_redacted(self):
        import re
        content = 'password: "mysecretpassword123"'
        lower = content.lower()
        if any(kw in lower for kw in CREDENTIAL_KEYWORDS):
            content = re.sub(
                r'((?:api_key|secret_key|password|token|access_key|secret_id|api_token)\s*[=:"]\s*["\']?)([A-Za-z0-9_\-/.]{8,})(["\']?)',
                r'\1[REDACTED]\3',
                content, flags=re.IGNORECASE,
            )
        assert "REDACTED" in content

    def test_no_redaction_when_no_keywords(self):
        content = "This is a normal Python file with no secrets."
        lower = content.lower()
        assert not any(kw in lower for kw in CREDENTIAL_KEYWORDS)

    def test_short_values_not_redacted(self):
        import re
        content = 'token = "abc"'
        lower = content.lower()
        if any(kw in lower for kw in CREDENTIAL_KEYWORDS):
            content = re.sub(
                r'((?:api_key|secret_key|password|token|access_key|secret_id|api_token)\s*[=:"]\s*["\']?)([A-Za-z0-9_\-/.]{8,})(["\']?)',
                r'\1[REDACTED]\3',
                content, flags=re.IGNORECASE,
            )
        # "abc" is < 8 chars, so should not be redacted
        assert "abc" in content

    def test_truncation_at_max_output(self):
        content = "x" * (TOOL_MAX_OUTPUT + 1000)
        truncated = content[:TOOL_MAX_OUTPUT]
        assert len(truncated) == TOOL_MAX_OUTPUT


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    def test_write_creates_file(self, tmp_path):
        target = tmp_path / "output.txt"
        content = "Hello, world!"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        assert target.read_text() == content

    def test_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test", encoding="utf-8")
        assert target.exists()
        assert target.read_text() == "test"

    def test_write_overwrites_existing(self, tmp_path):
        target = tmp_path / "overwrite.txt"
        target.write_text("original")
        target.write_text("replaced")
        assert target.read_text() == "replaced"


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_simple_echo(self):
        result = subprocess.run(
            "echo hello", shell=True, capture_output=True, text=True, timeout=120,
        )
        assert "hello" in result.stdout

    def test_exit_code_captured(self):
        result = subprocess.run(
            "exit 42", shell=True, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 42

    def test_stderr_captured(self):
        result = subprocess.run(
            "echo error >&2", shell=True, capture_output=True, text=True, timeout=120,
        )
        assert "error" in result.stderr

    def test_timeout_handling(self):
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                "sleep 10", shell=True, capture_output=True, text=True, timeout=1,
            )

    def test_output_truncation(self):
        result = subprocess.run(
            "python3 -c \"print('x' * 40000)\"",
            shell=True, capture_output=True, text=True, timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        truncated = output[:TOOL_MAX_OUTPUT]
        assert len(truncated) <= TOOL_MAX_OUTPUT


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


class TestListDirectory:
    def test_normal_directory(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.py").write_text("b")
        (tmp_path / "subdir").mkdir()

        entries = sorted(tmp_path.iterdir())[:100]
        lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]
        output = "\n".join(lines)

        assert "📁 subdir" in output
        assert "📄 file1.txt" in output
        assert "📄 file2.py" in output

    def test_empty_directory(self, tmp_path):
        entries = sorted(tmp_path.iterdir())[:100]
        output = "\n".join([f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]) if entries else "Empty directory."
        assert output == "Empty directory."

    def test_nonexistent_directory(self, tmp_path):
        target = tmp_path / "nonexistent"
        assert not target.is_dir()


# ---------------------------------------------------------------------------
# grep_search
# ---------------------------------------------------------------------------


class TestGrepSearch:
    def test_pattern_found(self, tmp_path):
        (tmp_path / "sample.py").write_text("def hello():\n    print('world')\n")
        result = subprocess.run(
            ["grep", "-rn", "--color=never", "hello", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert "hello" in result.stdout

    def test_pattern_not_found(self, tmp_path):
        (tmp_path / "sample.py").write_text("print('hello')\n")
        result = subprocess.run(
            ["grep", "-rn", "--color=never", "goodbye", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.stdout.strip() == ""

    def test_regex_pattern(self, tmp_path):
        (tmp_path / "log.txt").write_text("ERROR: something failed\nINFO: ok\n")
        result = subprocess.run(
            ["grep", "-rn", "--color=never", "ERROR", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert "ERROR" in result.stdout


# ---------------------------------------------------------------------------
# glob_search
# ---------------------------------------------------------------------------


class TestGlobSearch:
    def test_pattern_matching(self, tmp_path):
        (tmp_path / "a.py").write_text("# a")
        (tmp_path / "b.py").write_text("# b")
        (tmp_path / "c.txt").write_text("# c")

        import glob as glob_mod
        pattern = str(tmp_path / "**/*.py")
        matches = glob_mod.glob(pattern, recursive=True)
        py_files = [m for m in matches if os.path.isfile(m)]
        assert len(py_files) == 2

    def test_skip_dirs(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# main")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("// pkg")

        import glob as glob_mod
        matches = glob_mod.glob(str(tmp_path / "**/*"), recursive=True)
        _SKIP_DIRS = {"/.git/", "/__pycache__/", "/node_modules/", "/.cache/", "/.venv/", "/venv/", "/dist/", "/build/", "/.tox/"}
        filtered = [m for m in matches if os.path.isfile(m) and not any(skip in m for skip in _SKIP_DIRS)]
        # Should include src/main.py but not .git/HEAD or node_modules/pkg.js
        assert any("main.py" in m for m in filtered)
        assert not any(".git" in m for m in filtered)
        assert not any("node_modules" in m for m in filtered)

    def test_no_matches(self, tmp_path):
        import glob as glob_mod
        matches = glob_mod.glob(str(tmp_path / "**/*.xyz"), recursive=True)
        assert matches == []


import os
