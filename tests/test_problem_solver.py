"""Comprehensive tests for problem_solver.py THINK→PLAN→ACT→VERIFY→REPORT system."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import problem_solver


class TestSafeReadFile:
    """Tests for _safe_read_file function."""

    def test_read_existing_file(self, tmp_path):
        """Test reading an existing file."""
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver._safe_read_file(Path("test.py"))

        assert "print('hello')" in result

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading a non-existent file."""
        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver._safe_read_file(Path("nonexistent.py"))

        assert "ERROR:" in result

    def test_blocks_sensitive_paths(self, tmp_path):
        """Test blocking of sensitive paths."""
        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver._safe_read_file(Path(".aws/credentials"))

        assert "BLOCKED" in result
        assert "credential" in result.lower()

    def test_blocks_sensitive_files(self, tmp_path):
        """Test blocking of sensitive files."""
        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver._safe_read_file(Path(".env"))

        assert "BLOCKED" in result
        assert "credentials" in result.lower()

    def test_truncates_long_content(self, tmp_path):
        """Test that long content is truncated."""
        test_file = tmp_path / "large.py"
        test_file.write_text("x" * 50000)

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver._safe_read_file(Path("large.py"))

        assert len(result) <= problem_solver.TOOL_MAX_OUTPUT


class TestSafeGlobSearch:
    """Tests for _safe_glob_search function."""

    def test_finds_python_files(self, tmp_path):
        """Test finding Python files."""
        (tmp_path / "main.py").write_text("# main")
        (tmp_path / "utils.py").write_text("# utils")
        (tmp_path / "readme.md").write_text("# readme")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_glob_search("*.py", ".")

        assert len(results) == 2
        assert all(r.endswith(".py") for r in results)

    def test_respects_workspace_boundary(self, tmp_path):
        """Test that search stays within workspace."""
        outside = tmp_path.parent / "outside.py"
        outside.write_text("# outside")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_glob_search("*.py", "..")

        assert any("ERROR" in r for r in results)

    def test_limits_results(self, tmp_path):
        """Test result limiting."""
        for i in range(25):
            (tmp_path / f"file{i}.py").write_text(f"# file {i}")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_glob_search("*.py", ".")

        assert len(results) <= 20


class TestSafeGrepSearch:
    """Tests for _safe_grep_search function."""

    def test_finds_pattern(self, tmp_path):
        """Test finding pattern in files."""
        (tmp_path / "test.py").write_text("def hello():\n    print('world')")
        (tmp_path / "other.py").write_text("def goodbye():\n    print('bye')")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_grep_search("hello", ".", "py")

        assert len(results) >= 1
        assert any("hello" in r for r in results)

    def test_no_matches(self, tmp_path):
        """Test when pattern not found."""
        (tmp_path / "test.py").write_text("print('hello')")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_grep_search("nonexistent", ".", "py")

        assert len(results) == 0 or (len(results) == 1 and "ERROR" in results[0])

    def test_respects_workspace_boundary(self, tmp_path):
        """Test that search stays within workspace."""
        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            results = problem_solver._safe_grep_search("pattern", "..", "py")

        assert any("ERROR" in r for r in results)


class TestSolveProblem:
    """Tests for solve_problem main function."""

    @pytest.fixture
    def mock_workspace(self, tmp_path):
        """Create a mock workspace with test files."""
        (tmp_path / "main.py").write_text("""
def buggy_function(x):
    return x / 0  # Bug: division by zero

class MyClass:
    def method(self):
        return "hello"
""")
        (tmp_path / "utils.py").write_text("""
def helper():
    return 42
""")
        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            yield tmp_path

    def test_solve_with_file_candidate(self, mock_workspace):
        """Test solving problem that mentions a file."""
        result = problem_solver.solve_problem("Fix the bug in main.py")

        assert "think" in result
        assert "plan" in result
        assert "act" in result
        assert "verify" in result
        assert "report" in result
        assert result["status"] in ("completed", "failed")

    def test_solve_with_error_indicators(self, mock_workspace):
        """Test solving problem with error keywords."""
        result = problem_solver.solve_problem("There's an error: division by zero in main.py")

        assert result["act"]["step"] == 1
        assert "division by zero" in result["act"]["output"].lower() or "main.py" in result["act"]["output"]

    def test_solve_general_problem(self, mock_workspace):
        """Test solving a general problem without specific file/error."""
        result = problem_solver.solve_problem("How to implement a REST API?")

        assert result["status"] in ("completed", "failed")
        assert len(result["plan"]) > 0

    def test_solve_empty_problem(self, mock_workspace):
        """Test solving with empty problem."""
        result = problem_solver.solve_problem("")

        assert result["status"] in ("completed", "failed")
        assert "think" in result

    def test_solve_short_problem(self, mock_workspace):
        """Test solving with very short problem."""
        result = problem_solver.solve_problem("bug")

        assert result["status"] in ("completed", "failed")

    def test_solve_with_context(self, mock_workspace):
        """Test solving with additional context."""
        result = problem_solver.solve_problem(
            "Fix the bug",
            context="Error occurs in production"
        )

        assert result["status"] in ("completed", "failed")

    def test_solve_with_history(self, mock_workspace):
        """Test solving with conversation history."""
        history = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"}
        ]
        result = problem_solver.solve_problem("Continue fixing", history=history)

        assert result["status"] in ("completed", "failed")

    def test_solve_max_steps(self, mock_workspace):
        """Test max_steps parameter."""
        result = problem_solver.solve_problem("Complex problem", max_steps=3)
        assert result["status"] in ("completed", "failed")

    def test_act_result_structure(self, mock_workspace):
        """Test that act result has expected structure."""
        result = problem_solver.solve_problem("test problem")

        act = result["act"]
        assert "step" in act
        assert "action" in act
        assert "output" in act
        assert "details" in act
        assert "next_action" in act

    def test_verify_contains_expected_keywords(self, mock_workspace):
        """Test verify output contains expected keywords."""
        result = problem_solver.solve_problem("test problem")

        verify = result["verify"].lower()
        assert any(kw in verify for kw in ["verify", "berhasil", "tidak", "error", "output"])

    def test_report_contains_problem_summary(self, mock_workspace):
        """Test report contains problem summary."""
        result = problem_solver.solve_problem("Fix the authentication bug in login.py")

        report = result["report"].lower()
        assert "authentication" in report or "bug" in report or "login" in report

    def test_next_step_populated(self, mock_workspace):
        """Test next_step is populated."""
        result = problem_solver.solve_problem("test problem")

        assert "next_step" in result
        assert len(result["next_step"]) > 0

    def test_details_populated(self, mock_workspace):
        """Test details field is populated."""
        result = problem_solver.solve_problem("test problem")

        assert "details" in result
        assert len(result["details"]) > 0


class TestProblemSolverIntegration:
    """Integration-style tests for problem solver."""

    def test_file_discovery_and_read(self, tmp_path):
        """Test full flow: discover file -> read -> analyze."""
        (tmp_path / "app.py").write_text("""
def calculate(x, y):
    return x + y

def divide(a, b):
    return a / b  # Potential bug
""")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver.solve_problem("Check divide function in app.py for bugs")

        assert result["status"] in ("completed", "failed")
        # Should have found and read the file
        assert "divide" in result["act"]["output"].lower() or "app.py" in result["act"]["output"]

    def test_error_search_flow(self, tmp_path):
        """Test flow: extract error -> search -> find."""
        (tmp_path / "service.py").write_text("""
class Service:
    def process(self):
        raise ValueError("Invalid input")
""")

        with patch('problem_solver.WORKSPACE_ROOT', tmp_path):
            result = problem_solver.solve_problem("Error: ValueError Invalid input in service.py")

        assert result["status"] in ("completed", "failed")
        assert "ValueError" in result["act"]["output"] or "Invalid input" in result["act"]["output"]


class TestConstants:
    """Tests for module constants."""

    def test_workspace_root(self):
        assert problem_solver.WORKSPACE_ROOT == Path("/root")

    def test_opsora_dir(self):
        assert problem_solver.OPSORA_DIR == Path("/root/.opsora")

    def test_sensitive_paths(self):
        assert ".aws" in problem_solver.SENSITIVE_PATHS
        assert ".ssh" in problem_solver.SENSITIVE_PATHS
        assert ".gnupg" in problem_solver.SENSITIVE_PATHS

    def test_sensitive_files(self):
        assert ".env" in problem_solver.SENSITIVE_FILES
        assert "secrets.env" in problem_solver.SENSITIVE_FILES
        assert "credentials" in problem_solver.SENSITIVE_FILES

    def test_credential_keywords(self):
        assert "api_key" in problem_solver.CREDENTIAL_KEYWORDS
        assert "secret_key" in problem_solver.CREDENTIAL_KEYWORDS
        assert "password" in problem_solver.CREDENTIAL_KEYWORDS
        assert "token" in problem_solver.CREDENTIAL_KEYWORDS

    def test_tool_max_output(self):
        assert problem_solver.TOOL_MAX_OUTPUT == 30_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])