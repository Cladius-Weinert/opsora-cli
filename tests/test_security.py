"""Security & Phase 1 bug-fix tests.

Covers:
- File tools (read_file/write_file/edit_file) cannot escape the workspace,
  including via symlinks, and legitimate in-workspace ops still work.
- run_command no longer uses shell=True: metacharacter injection is
  neutralized and unparseable commands return a clear error.
- git tools (git_diff/git_status/git_log/git_commit) no longer build shell
  strings from user-controlled paths.
- Session ids are uuid4-based (no time.time() collisions) and keep the
  12-char lowercase hex DB format.
- Pricing has a single source of truth: opsora_v2 uses opsora_cost's
  MODEL_COSTS (config/model_costs.json + built-in fallback), no local copy.

No network access; all paths use pytest tmp_path fixtures.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_cost  # noqa: E402
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


# ============================================================================
# Path traversal — file tools
# ============================================================================

class TestFileToolPathTraversal:
    """File tools must stay inside the workspace."""

    def test_read_absolute_path_outside_workspace_blocked(self, workspace):
        """Reading an absolute path outside the workspace is blocked."""
        result = opsora_v2.execute_tool("read_file", {"filepath": "/etc/passwd"})
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert "root:" not in result  # no content leaked

    def test_read_relative_traversal_blocked(self, workspace):
        """Reading via ../ traversal is blocked."""
        result = opsora_v2.execute_tool(
            "read_file", {"filepath": "../../../../etc/passwd"}
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert "root:" not in result

    def test_write_outside_workspace_blocked(self, workspace):
        """Writing to a path outside the workspace is blocked and creates nothing."""
        target = workspace.outside / "evil.txt"
        result = opsora_v2.execute_tool(
            "write_file", {"filepath": str(target), "content": "pwned"}
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert not target.exists()

    def test_write_relative_traversal_blocked(self, workspace):
        """Writing via ../ traversal is blocked and creates nothing."""
        target = workspace.outside / "evil2.txt"
        rel = os.path.relpath(target, workspace.ws)  # ../outside/evil2.txt
        result = opsora_v2.execute_tool(
            "write_file", {"filepath": rel, "content": "pwned"}
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert not target.exists()

    def test_edit_outside_workspace_blocked(self, workspace):
        """Editing a file outside the workspace is blocked and leaves it unchanged."""
        target = workspace.outside / "victim.txt"
        target.write_text("original content")
        result = opsora_v2.execute_tool(
            "edit_file",
            {"filepath": str(target), "old_string": "original", "new_string": "hacked"},
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert target.read_text() == "original content"

    def test_read_symlink_escaping_workspace_blocked(self, workspace):
        """A symlink inside the workspace pointing outside must not be readable."""
        link = workspace.ws / "sneaky_link"
        os.symlink("/etc/passwd", str(link))
        result = opsora_v2.execute_tool("read_file", {"filepath": "sneaky_link"})
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert "root:" not in result

    def test_write_through_symlink_dir_escaping_workspace_blocked(self, workspace):
        """Writing through a symlinked dir that escapes the workspace is blocked."""
        link_dir = workspace.ws / "escape_dir"
        os.symlink(str(workspace.outside), str(link_dir))
        target = workspace.outside / "via_symlink.txt"
        result = opsora_v2.execute_tool(
            "write_file", {"filepath": "escape_dir/via_symlink.txt", "content": "pwned"}
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert not target.exists()

    def test_write_through_symlink_file_escaping_workspace_blocked(self, workspace):
        """Overwriting an outside file via a symlinked filename is blocked."""
        target = workspace.outside / "target.txt"
        target.write_text("precious data")
        link = workspace.ws / "innocent_link"
        os.symlink(str(target), str(link))
        result = opsora_v2.execute_tool(
            "write_file", {"filepath": "innocent_link", "content": "overwritten"}
        )
        assert "traversal" in result.lower() or "blocked" in result.lower()
        assert target.read_text() == "precious data"

    def test_legitimate_workspace_ops_still_work(self, workspace):
        """Normal in-workspace read/write/edit must keep working."""
        # write (new file + nested dir creation)
        result = opsora_v2.execute_tool(
            "write_file", {"filepath": "sub/hello.py", "content": "print('hi')\n"}
        )
        assert "Wrote" in result
        assert (workspace.ws / "sub" / "hello.py").read_text() == "print('hi')\n"

        # read back (relative and absolute)
        assert "print('hi')" in opsora_v2.execute_tool(
            "read_file", {"filepath": "sub/hello.py"}
        )
        assert "print('hi')" in opsora_v2.execute_tool(
            "read_file", {"filepath": str(workspace.ws / "sub" / "hello.py")}
        )

        # edit
        result = opsora_v2.execute_tool(
            "edit_file",
            {"filepath": "sub/hello.py", "old_string": "hi", "new_string": "hello"},
        )
        assert "Edited" in result
        assert (workspace.ws / "sub" / "hello.py").read_text() == "print('hello')\n"

    def test_symlink_inside_workspace_still_works(self, workspace):
        """A symlink that stays inside the workspace is allowed."""
        real = workspace.ws / "real.txt"
        real.write_text("inside content")
        os.symlink(str(real), str(workspace.ws / "link.txt"))
        result = opsora_v2.execute_tool("read_file", {"filepath": "link.txt"})
        assert "inside content" in result


# ============================================================================
# Command injection — run_command
# ============================================================================

class TestRunCommandInjection:
    """run_command must not allow shell metacharacter injection."""

    def test_semicolon_injection_does_not_create_file(self, workspace):
        """'; touch /tmp/pwned_$$' must not create any file."""
        before = set(Path("/tmp").glob("pwned_*"))
        result = opsora_v2.execute_tool(
            "run_command", {"command": "echo hello; touch /tmp/pwned_$$"}
        )
        after = set(Path("/tmp").glob("pwned_*"))
        assert after == before, f"injection created file(s): {after - before}"
        assert not Path("/tmp/pwned_$$").exists()
        # The whole string is passed as literal arguments to echo.
        assert "hello" in result

    def test_semicolon_injection_into_outside_dir_neutralized(self, workspace):
        """Injected 'touch' targeting a known path must not run."""
        target = workspace.outside / "pwned_marker"
        result = opsora_v2.execute_tool(
            "run_command", {"command": f"echo hi; touch {target}"}
        )
        assert not target.exists()
        assert "echo hi" in result or "hi" in result

    def test_and_chain_injection_neutralized(self, workspace):
        """'&&' chaining must not execute a second command."""
        target = workspace.outside / "pwned_and"
        opsora_v2.execute_tool(
            "run_command", {"command": f"true && touch {target}"}
        )
        assert not target.exists()

    def test_command_substitution_neutralized(self, workspace):
        """$(...) and backticks must not be executed."""
        target = workspace.outside / "pwned_subst"
        opsora_v2.execute_tool(
            "run_command", {"command": f"echo $(touch {target})"}
        )
        opsora_v2.execute_tool(
            "run_command", {"command": f"echo `touch {target}`"}
        )
        assert not target.exists()

    def test_redirect_neutralized(self, workspace):
        """'>' must not write files via the shell."""
        target = workspace.outside / "pwned_redirect"
        opsora_v2.execute_tool(
            "run_command", {"command": f"echo pwned > {target}"}
        )
        assert not target.exists()

    def test_unparseable_command_returns_clear_error(self, workspace):
        """An unbalanced quote fails parsing and returns a clear error."""
        result = opsora_v2.execute_tool(
            "run_command", {"command": 'echo "unterminated'}
        )
        assert result.startswith("ERROR")
        assert "parse" in result.lower()

    def test_empty_command_returns_clear_error(self, workspace):
        """An empty/whitespace command returns a clear error."""
        result = opsora_v2.execute_tool("run_command", {"command": "   "})
        assert result.startswith("ERROR")

    def test_normal_commands_still_work(self, workspace):
        """Ordinary commands (with arguments) keep working."""
        assert "hello" in opsora_v2.execute_tool(
            "run_command", {"command": "echo hello"}
        )
        listing = opsora_v2.execute_tool("run_command", {"command": "ls -la"})
        assert "ERROR" not in listing
        # runs inside the workspace
        (workspace.ws / "marker.txt").write_text("x")
        assert "marker.txt" in opsora_v2.execute_tool(
            "run_command", {"command": "ls"}
        )


# ============================================================================
# Command injection — git tools
# ============================================================================

class TestGitToolInjection:
    """git tools must not inject shell commands via the path argument."""

    @pytest.mark.parametrize("tool", ["git_diff", "git_status", "git_log"])
    def test_path_injection_neutralized(self, workspace, tool):
        """A malicious path must not execute embedded commands."""
        target = workspace.outside / f"pwned_{tool}"
        malicious = f"/tmp/nonexistent; touch {target}"
        result = opsora_v2.execute_tool(tool, {"path": malicious})
        assert not target.exists()
        assert "ERROR" in result  # rejected as a directory, nothing executed

    @pytest.mark.parametrize("tool", ["git_diff", "git_status", "git_log"])
    def test_existing_dir_with_metacharacters_safe(self, workspace, tool):
        """Even an existing dir whose name contains $(...) cannot trigger execution.

        If a shell were involved, `$(touch <marker>)` in the path would run
        during expansion (in the shell's cwd, or inside the dir after cd).
        """
        marker = f"pwned_dir_{tool}"
        evil_dir = workspace.tmp / f"evil_$(touch {marker})"
        evil_dir.mkdir()  # dir names cannot contain '/', so marker is relative
        result = opsora_v2.execute_tool(tool, {"path": str(evil_dir)})
        assert not (Path.cwd() / marker).exists()  # substitution before cd
        assert not (evil_dir / marker).exists()    # substitution after cd
        # Not a git repo: git's own error (or clean fallback) is returned as text.
        assert isinstance(result, str) and result

    def test_git_commit_message_injection_neutralized(self, workspace):
        """git_commit message must be passed as a literal argv element."""
        repo = _make_git_repo(workspace.ws / "repo_commit")
        (repo / "new.txt").write_text("change")
        target = workspace.outside / "pwned_commit"
        result = opsora_v2.execute_tool(
            "git_commit",
            {"path": str(repo), "message": f"evil $(touch {target}); touch {target}"},
        )
        assert not target.exists()
        assert isinstance(result, str) and result

    def test_git_tools_normal_ops_still_work(self, workspace):
        """Normal git status/diff/log keep working on a real repo."""
        repo = _make_git_repo(workspace.ws / "repo_ok")

        # clean tree after initial commit
        status = opsora_v2.execute_tool("git_status", {"path": str(repo)})
        assert status == "Clean working tree." or status == ""

        # modify a file -> status + diff reflect it
        (repo / "file.txt").write_text("modified line\n")
        status = opsora_v2.execute_tool("git_status", {"path": str(repo)})
        assert "file.txt" in status
        diff = opsora_v2.execute_tool("git_diff", {"path": str(repo)})
        assert "---FULL DIFF---" in diff
        assert "file.txt" in diff

        # log shows the initial commit; count parameter works
        log = opsora_v2.execute_tool(
            "git_log", {"path": str(repo), "count": 5}
        )
        assert "initial commit" in log

        # relative path resolution against the workspace still works
        rel = os.path.relpath(repo, workspace.ws)
        assert "initial commit" in opsora_v2.execute_tool(
            "git_log", {"path": rel, "count": 1}
        )

    def test_git_tools_missing_dir_returns_error(self, workspace):
        """A non-existent path returns a clear error instead of running anything."""
        for tool in ("git_diff", "git_status", "git_log"):
            result = opsora_v2.execute_tool(
                tool, {"path": str(workspace.outside / "no_such_dir")}
            )
            assert result.startswith("ERROR")


# ============================================================================
# Phase 1 bugfix — session id generation (was sha256(time.time())[:12])
# ============================================================================

class TestSessionIdGeneration:
    """Session ids must be collision-safe and keep the DB's 12-hex format."""

    def test_format_is_12_lowercase_hex(self):
        """DB compatibility: sessions.id rows are 12 lowercase hex chars."""
        for _ in range(20):
            sid = opsora_v2.generate_session_id()
            assert re.fullmatch(r"[0-9a-f]{12}", sid), f"bad session id format: {sid!r}"

    def test_rapid_generation_no_collisions(self):
        """The old sha256(str(time.time())) collided within one clock tick;
        uuid4-based ids must not collide across rapid consecutive calls."""
        ids = [opsora_v2.generate_session_id() for _ in range(1000)]
        assert len(set(ids)) == 1000

    def test_main_uses_helper(self):
        """main() must delegate to generate_session_id (single definition)."""
        import inspect
        src = inspect.getsource(opsora_v2.main)
        assert "generate_session_id()" in src
        assert "sha256" not in src and "time.time()" not in src


# ============================================================================
# Phase 1 bugfix — single source of truth for model pricing
# ============================================================================

class TestModelCostsSingleSource:
    """opsora_v2 must price via opsora_cost.MODEL_COSTS, not a local copy."""

    def test_v2_uses_opsora_cost_table(self):
        """Same dict object — no duplicated pricing table."""
        assert opsora_v2.MODEL_COSTS is opsora_cost.MODEL_COSTS

    def test_estimate_cost_uses_shared_rates(self):
        """estimate_cost matches opsora_cost's rates for a known model."""
        model = "qwen-plus"
        assert model in opsora_cost.MODEL_COSTS
        in_rate, out_rate = opsora_cost.MODEL_COSTS[model]
        total, cost = opsora_v2.estimate_cost(model, 400, 200)  # 100 + 50 tokens
        assert total == 150
        expected = (100 * in_rate + 50 * out_rate) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_uses_shared_default(self):
        """Unknown models fall back to opsora_cost's default cost."""
        total, cost = opsora_v2.estimate_cost("no-such-model", 400, 200)
        assert total == 150
        expected = (100 * opsora_cost._DEFAULT_COST[0]
                    + 50 * opsora_cost._DEFAULT_COST[1]) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_no_local_pricing_dict_in_source(self):
        """The hard-coded pricing dict must not be reintroduced."""
        src = Path(opsora_v2.__file__).read_text(encoding="utf-8")
        assert "MODEL_COSTS = {" not in src


# ============================================================================
# Helpers
# ============================================================================

def _make_git_repo(path: Path) -> Path:
    """Create a real git repo with one commit (offline, no global config needed)."""
    path.mkdir(parents=True, exist_ok=True)
    git = ["git"]
    subprocess.run(git + ["init", "-q"], cwd=path, check=True)
    (path / "file.txt").write_text("original line\n")
    subprocess.run(git + ["add", "-A"], cwd=path, check=True)
    subprocess.run(
        git + ["-c", "user.email=test@test.local", "-c", "user.name=Test",
               "-c", "commit.gpgsign=false", "commit", "-q", "-m", "initial commit"],
        cwd=path, check=True,
    )
    return path
