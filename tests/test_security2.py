"""Phase 1 wave-2 security tests: command injection in run_tests / lint_check.

Complements tests/test_security.py (wave 1: file tools, run_command, git
tools, session ids, pricing). Covers the remaining shell=True call sites
that were converted to argv lists + cwd:

- run_tests: repo path is validated (is_dir) and the test filter is parsed
  into validated argv tokens — never interpolated into a shell string.
- lint_check: target path is validated and the linter runs as an argv list.
- pip_info: the package name is a literal argv element.

No network access; all paths use pytest tmp_path fixtures. Legitimate usage
(pytest run, -k filter, ruff lint) is verified to keep working.
"""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_v2  # noqa: E402


@pytest.fixture
def workspace(tmp_path):
    """Patch WORKSPACE_ROOT to a fresh dir; provide an 'outside' dir next to it."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with patch.object(opsora_v2, "WORKSPACE_ROOT", ws):
        with patch.object(opsora_v2, "needs_approval", return_value=False):
            yield SimpleNamespace(ws=ws, outside=outside, tmp=tmp_path)


def _make_pytest_project(root: Path, passing: bool = True) -> Path:
    """Create a minimal pytest project with one test file."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    body = (
        "def test_ok():\n    assert True\n"
        if passing
        else "def test_bad():\n    assert False\n"
    )
    (root / "test_demo.py").write_text(body)
    return root


# ============================================================================
# Command injection — run_tests
# ============================================================================

class TestRunTestsInjection:
    """run_tests must not inject shell commands via path or filter."""

    def test_path_injection_neutralized(self, workspace):
        """A malicious path must not execute embedded commands."""
        target = workspace.outside / "pwned_run_tests"
        malicious = f"/tmp/nonexistent; touch {target}"
        result = opsora_v2.execute_tool("run_tests", {"path": malicious})
        assert not target.exists()
        assert result.startswith("ERROR")  # rejected as a directory

    def test_existing_dir_with_metacharacters_safe(self, workspace):
        """An existing dir whose name contains $(...) cannot trigger execution.

        The dir holds a pyproject.toml so the pytest branch really runs a
        subprocess with the hostile directory name as its cwd.
        """
        marker = "pwned_rt_marker"
        evil_dir = workspace.tmp / f"evil_$(touch {marker})"
        _make_pytest_project(evil_dir)
        result = opsora_v2.execute_tool("run_tests", {"path": str(evil_dir)})
        assert not (Path.cwd() / marker).exists()  # substitution before cd
        assert not (evil_dir / marker).exists()    # substitution after cd
        assert isinstance(result, str) and result

    def test_filter_shell_injection_rejected(self, workspace):
        """';' metacharacters in the filter are rejected, not executed."""
        proj = _make_pytest_project(workspace.ws / "proj_f1")
        target = workspace.outside / "pwned_filter"
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": f"; touch {target}"}
        )
        assert not target.exists()
        assert result.startswith("ERROR")

    def test_filter_command_substitution_rejected(self, workspace):
        """$(...) in the filter is rejected, not executed."""
        proj = _make_pytest_project(workspace.ws / "proj_f2")
        target = workspace.outside / "pwned_filter_subst"
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": f"$(touch {target})"}
        )
        assert not target.exists()
        assert result.startswith("ERROR")

    def test_filter_option_injection_rejected(self, workspace):
        """Arbitrary pytest options cannot be smuggled in via the filter."""
        proj = _make_pytest_project(workspace.ws / "proj_f3")
        for evil in ("--collect-only", "-o cache_dir=/tmp/x", "--version"):
            result = opsora_v2.execute_tool(
                "run_tests", {"path": str(proj), "filter": evil}
            )
            assert result.startswith("ERROR"), f"option {evil!r} was not rejected"

    def test_filter_unparseable_rejected(self, workspace):
        """An unbalanced quote in the filter returns a clear error."""
        proj = _make_pytest_project(workspace.ws / "proj_f4")
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": '"unterminated'}
        )
        assert result.startswith("ERROR")
        assert "parse" in result.lower()

    def test_legitimate_run_tests_works(self, workspace):
        """Plain run_tests on a real pytest project still passes."""
        proj = _make_pytest_project(workspace.ws / "proj_ok")
        result = opsora_v2.execute_tool("run_tests", {"path": str(proj)})
        assert "1 passed" in result

        # relative path resolution against the workspace still works
        result = opsora_v2.execute_tool("run_tests", {"path": "proj_ok"})
        assert "1 passed" in result

    def test_legitimate_filter_path_and_node_id_work(self, workspace):
        """A test-path / node-id filter still works."""
        proj = _make_pytest_project(workspace.ws / "proj_node")
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": "test_demo.py"}
        )
        assert "1 passed" in result
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": "test_demo.py::test_ok"}
        )
        assert "1 passed" in result

    def test_legitimate_k_filter_works(self, workspace):
        """A '-k <expr>' keyword filter still works (incl. boolean exprs)."""
        proj = _make_pytest_project(workspace.ws / "proj_k")
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": "-k test_ok"}
        )
        assert "1 passed" in result
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(proj), "filter": "-k test_ok and not test_zzz"}
        )
        assert "1 passed" in result

    def test_missing_dir_returns_error(self, workspace):
        """A non-existent path returns a clear error instead of running anything."""
        result = opsora_v2.execute_tool(
            "run_tests", {"path": str(workspace.outside / "no_such_dir")}
        )
        assert result.startswith("ERROR")


# ============================================================================
# Command injection — lint_check
# ============================================================================

class TestLintCheckInjection:
    """lint_check must not inject shell commands via the path argument."""

    def test_path_injection_neutralized(self, workspace):
        """A malicious path must not execute embedded commands."""
        target = workspace.outside / "pwned_lint"
        malicious = f"/tmp/nonexistent; touch {target}"
        result = opsora_v2.execute_tool("lint_check", {"path": malicious})
        assert not target.exists()
        assert result.startswith("ERROR")

    def test_existing_dir_with_metacharacters_safe(self, workspace):
        """An existing dir whose name contains $(...) cannot trigger execution."""
        marker = "pwned_lint_marker"
        evil_dir = workspace.tmp / f"evil_lint_$(touch {marker})"
        evil_dir.mkdir()
        (evil_dir / "clean.py").write_text("X = 1\n")
        result = opsora_v2.execute_tool("lint_check", {"path": str(evil_dir)})
        assert not (Path.cwd() / marker).exists()  # substitution before cd
        assert not (evil_dir / marker).exists()    # substitution after cd
        assert isinstance(result, str) and result

    def test_legitimate_lint_clean_file(self, workspace):
        """Linting a clean file/dir keeps working (ruff is installed here)."""
        proj = workspace.ws / "lint_ok"
        proj.mkdir()
        (proj / "clean.py").write_text("X = 1\n")
        result = opsora_v2.execute_tool("lint_check", {"path": str(proj)})
        assert not result.startswith("ERROR")

    def test_legitimate_lint_finds_issue(self, workspace):
        """Lint output still surfaces real findings."""
        proj = workspace.ws / "lint_bad"
        proj.mkdir()
        (proj / "bad.py").write_text("import os\n\nX = 1\n")  # unused import
        result = opsora_v2.execute_tool("lint_check", {"path": str(proj)})
        assert "F401" in result  # ruff's unused-import code

    def test_lint_single_file_target(self, workspace):
        """A single-file lint target keeps working."""
        proj = workspace.ws / "lint_file"
        proj.mkdir()
        bad = proj / "bad.py"
        bad.write_text("import os\n\nX = 1\n")
        result = opsora_v2.execute_tool("lint_check", {"path": str(bad)})
        assert "F401" in result

    def test_missing_path_returns_error(self, workspace):
        """A non-existent path returns a clear error instead of running anything."""
        result = opsora_v2.execute_tool(
            "lint_check", {"path": str(workspace.outside / "no_such_dir")}
        )
        assert result.startswith("ERROR")


# ============================================================================
# Command injection — pip_info (argv literal, was shell + shlex.quote)
# ============================================================================

class TestPipInfoInjection:
    """pip_info must pass the package name as a literal argv element."""

    def test_package_name_is_literal(self, workspace):
        """Metacharacters in the package name cannot execute anything."""
        marker = "/tmp/pwned_pip_info"
        if Path(marker).exists():
            Path(marker).unlink()
        result = opsora_v2.execute_tool(
            "pip_info", {"package": f"nonexistent; touch {marker}"}
        )
        assert not Path(marker).exists()
        assert "not found" in result.lower() or "error" in result.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
