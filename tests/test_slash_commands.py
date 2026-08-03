"""Comprehensive tests for opsora_v2.py slash command handlers."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import json
import time

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_v2
from opsora_v2 import Selection, handle_command, StatusBar


class TestHandleCommand:
    """Tests for handle_command function."""

    @pytest.fixture
    def mock_setup(self):
        """Common mock setup for handle_command tests."""
        with patch('opsora_v2.console') as mock_console:
            with patch('opsora_v2.get_approval_mode') as mock_approval:
                with patch('opsora_v2.set_approval_mode') as mock_set_approval:
                    with patch('opsora_v2.cycle_approval_mode') as mock_cycle:
                        mock_approval.return_value = opsora_v2.ApprovalMode.FULL_AUTO
                        mock_cycle.return_value = opsora_v2.ApprovalMode.FULL_AUTO
                        yield {
                            'console': mock_console,
                            'approval': mock_approval,
                            'set_approval': mock_set_approval,
                            'cycle': mock_cycle
                        }

    @pytest.fixture
    def status_bar(self):
        """Create a status bar for testing."""
        return StatusBar(
            provider="alibaba",
            model="qwen-plus",
            approval_mode=opsora_v2.ApprovalMode.FULL_AUTO,
            cwd="/root",
            current_activity="Test"
        )

    @pytest.fixture
    def selection(self):
        """Create a selection for testing."""
        return Selection("alibaba", "qwen-plus")

    @pytest.fixture
    def history(self):
        """Create a sample history."""
        return [{"role": "user", "content": "test"}]

    def test_exit_command(self, mock_setup, status_bar, selection, history):
        """Test /exit command."""
        cont, new_sel, resume_id = handle_command("/exit", history, selection, status_bar, "sess1")
        assert cont is False
        assert new_sel is None
        assert resume_id is None

    def test_quit_command(self, mock_setup, status_bar, selection, history):
        """Test /quit command."""
        cont, _, _ = handle_command("/quit", history, selection, status_bar, "sess1")
        assert cont is False

    def test_help_command(self, mock_setup, status_bar, selection, history):
        """Test /help command."""
        with patch('opsora_v2.render_help') as mock_help:
            cont, _, _ = handle_command("/help", history, selection, status_bar, "sess1")
            assert cont is True
            mock_help.assert_called_once()

    def test_status_command(self, mock_setup, status_bar, selection, history):
        """Test /status command."""
        with patch('opsora_v2._show_status') as mock_status:
            cont, _, _ = handle_command("/status", history, selection, status_bar, "sess1")
            assert cont is True
            mock_status.assert_called_once()

    def test_models_command(self, mock_setup, status_bar, selection, history):
        """Test /models command."""
        with patch('opsora_v2._show_models') as mock_models:
            cont, _, _ = handle_command("/models", history, selection, status_bar, "sess1")
            assert cont is True
            mock_models.assert_called_once()

    def test_tools_command(self, mock_setup, status_bar, selection, history):
        """Test /tools command."""
        with patch('opsora_v2._show_tools') as mock_tools:
            cont, _, _ = handle_command("/tools", history, selection, status_bar, "sess1")
            assert cont is True
            mock_tools.assert_called_once()

    def test_mode_command(self, mock_setup, status_bar, selection, history):
        """Test /mode command."""
        # ApprovalMode is SUGGEST/AUTO_EDIT/FULL_AUTO since the Phase 1 TUI
        # refactor (PLAN_ONLY was removed) — cycle to SUGGEST here.
        mock_setup['cycle'].return_value = opsora_v2.ApprovalMode.SUGGEST
        cont, _, _ = handle_command("/mode", history, selection, status_bar, "sess1")
        assert cont is True
        mock_setup['set_approval'].assert_called_with(opsora_v2.ApprovalMode.SUGGEST)

    def test_model_command_valid(self, mock_setup, status_bar, selection, history):
        """Test /model command with valid provider."""
        with patch('opsora_v2.is_provider_available', return_value=True):
            with patch('opsora_v2.PROVIDER_MODELS', {"alibaba": "qwen-plus,qwen-max"}):
                cont, new_sel, _ = handle_command("/model alibaba qwen-max", history, selection, status_bar, "sess1")
                assert cont is True
                assert new_sel is not None
                assert new_sel.provider == "alibaba"
                assert new_sel.model == "qwen-max"

    def test_model_command_invalid_provider(self, mock_setup, status_bar, selection, history):
        """Test /model command with unavailable provider."""
        with patch('opsora_v2.is_provider_available', return_value=False):
            cont, new_sel, _ = handle_command("/model unavailable", history, selection, status_bar, "sess1")
            assert cont is True
            assert new_sel is None

    def test_tree_command(self, mock_setup, status_bar, selection, history):
        """Test /tree command."""
        with patch('opsora_v2.render_file_tree') as mock_tree:
            cont, _, _ = handle_command("/tree /root", history, selection, status_bar, "sess1")
            assert cont is True
            mock_tree.assert_called_once_with("/root")

    def test_sessions_command_empty(self, mock_setup, status_bar, selection, history):
        """Test /sessions command with no sessions."""
        with patch('opsora_v2.list_sessions', return_value=[]):
            cont, _, _ = handle_command("/sessions", history, selection, status_bar, "sess1")
            assert cont is True

    def test_sessions_command_with_sessions(self, mock_setup, status_bar, selection, history):
        """Test /sessions command with sessions."""
        sessions = [
            {"id": "abc123", "title": "Test Session", "model": "qwen-plus", "updated_at": time.time()}
        ]
        with patch('opsora_v2.list_sessions', return_value=sessions):
            cont, _, _ = handle_command("/sessions", history, selection, status_bar, "sess1")
            assert cont is True

    def test_resume_command_valid(self, mock_setup, status_bar, selection, history):
        """Test /resume command with valid session."""
        session = opsora_v2.Session(
            id="abc123", title="Test", provider="alibaba", model="qwen-plus",
            created_at=time.time(), updated_at=time.time(), token_count=100,
            approval_mode="full-auto", messages=[{"role": "user", "content": "hi"}]
        )
        with patch('opsora_v2.load_session', return_value=session):
            cont, new_sel, resume_id = handle_command("/resume abc123", history, selection, status_bar, "sess1")
            assert cont is True
            assert new_sel is not None
            assert new_sel.provider == "alibaba"
            assert resume_id == "abc123"

    def test_resume_command_not_found(self, mock_setup, status_bar, selection, history):
        """Test /resume command with non-existent session."""
        with patch('opsora_v2.load_session', return_value=None):
            cont, new_sel, _ = handle_command("/resume nonexistent", history, selection, status_bar, "sess1")
            assert cont is True
            assert new_sel is None

    def test_new_command(self, mock_setup, status_bar, selection, history):
        """Test /new command."""
        history.append({"role": "user", "content": "old"})
        cont, _, _ = handle_command("/new", history, selection, status_bar, "sess1")
        assert cont is True
        assert len(history) == 0

    def test_clear_command(self, mock_setup, status_bar, selection, history):
        """Test /clear command."""
        with patch('opsora_v2.console.clear') as mock_clear:
            with patch('opsora_v2.print_welcome') as mock_welcome:
                cont, _, _ = handle_command("/clear", history, selection, status_bar, "sess1")
                assert cont is True
                mock_clear.assert_called_once()
                mock_welcome.assert_called_once()

    def test_run_command(self, mock_setup, status_bar, selection, history):
        """Test /run command."""
        with patch('opsora_v2.execute_tool', return_value="output") as mock_exec:
            with patch('opsora_v2._validate_command', return_value="echo test"):
                cont, _, _ = handle_command("/run echo test", history, selection, status_bar, "sess1")
                assert cont is True
                mock_exec.assert_called_with("run_command", {"command": "echo test"})

    def test_run_command_dangerous(self, mock_setup, status_bar, selection, history):
        """Test /run command with dangerous command."""
        with patch('opsora_v2._validate_command', side_effect=ValueError("Dangerous")):
            cont, _, _ = handle_command("/run rm -rf /", history, selection, status_bar, "sess1")
            assert cont is True

    def test_read_command(self, mock_setup, status_bar, selection, history):
        """Test /read command."""
        with patch('opsora_v2.execute_tool', return_value="file content") as mock_exec:
            with patch('opsora_v2._validate_path'):
                cont, _, _ = handle_command("/read test.py", history, selection, status_bar, "sess1")
                assert cont is True
                mock_exec.assert_called_with("read_file", {"filepath": "test.py"})

    def test_memory_command(self, mock_setup, status_bar, selection, history):
        """Test /memory command."""
        with patch('opsora_v2.execute_tool', return_value="memory result") as mock_exec:
            cont, _, _ = handle_command("/memory test query", history, selection, status_bar, "sess1")
            assert cont is True
            mock_exec.assert_called_with("memory_search", {"query": "test query"})

    def test_agent_command(self, mock_setup, status_bar, selection, history):
        """Test /agent command."""
        with patch('opsora_v2.run_subagent', return_value="Subagent result") as mock_subagent:
            cont, _, _ = handle_command("/agent complex task", history, selection, status_bar, "sess1")
            assert cont is True
            mock_subagent.assert_called_once()

    def test_agent_command_no_goal(self, mock_setup, status_bar, selection, history):
        """Test /agent command without goal."""
        cont, _, _ = handle_command("/agent", history, selection, status_bar, "sess1")
        assert cont is True

    def test_review_command(self, mock_setup, status_bar, selection, history):
        """Test /review command."""
        with patch('opsora_v2.execute_tool') as mock_exec:
            mock_exec.side_effect = [
                "diff output",  # git_diff
                "status output"  # git_status
            ]
            with patch('opsora_v2.run_agent_turn') as mock_agent:
                mock_agent.return_value = (history, selection)
                cont, _, _ = handle_command("/review", history, selection, status_bar, "sess1")
                assert cont is True
                assert len(history) > 1  # Should have added review prompt

    def test_review_command_no_changes(self, mock_setup, status_bar, selection, history):
        """Test /review command with no changes."""
        with patch('opsora_v2.execute_tool') as mock_exec:
            mock_exec.side_effect = [
                "No changes",  # git_diff
                "Clean"  # git_status
            ]
            cont, _, _ = handle_command("/review", history, selection, status_bar, "sess1")
            assert cont is True

    def test_deploy_command(self, mock_setup, status_bar, selection, history):
        """Test /deploy command."""
        with patch('opsora_v2.run_agent_turn') as mock_agent:
            mock_agent.return_value = (history, selection)
            cont, _, _ = handle_command("/deploy render", history, selection, status_bar, "sess1")
            assert cont is True
            assert len(history) > 1

    def test_explain_command(self, mock_setup, status_bar, selection, history):
        """Test /explain command."""
        with patch('opsora_v2.execute_tool', return_value="code content") as mock_exec:
            with patch('opsora_v2._validate_path'):
                with patch('opsora_v2.run_agent_turn') as mock_agent:
                    mock_agent.return_value = (history, selection)
                    cont, _, _ = handle_command("/explain test.py my_function", history, selection, status_bar, "sess1")
                    assert cont is True
                    mock_exec.assert_called_with("read_file", {"filepath": "test.py"})

    def test_explain_command_no_file(self, mock_setup, status_bar, selection, history):
        """Test /explain command without file."""
        cont, _, _ = handle_command("/explain", history, selection, status_bar, "sess1")
        assert cont is True

    def test_refactor_command(self, mock_setup, status_bar, selection, history):
        """Test /refactor command."""
        with patch('opsora_v2.execute_tool', return_value="code content") as mock_exec:
            with patch('opsora_v2._validate_path'):
                with patch('opsora_v2.run_agent_turn') as mock_agent:
                    mock_agent.return_value = (history, selection)
                    cont, _, _ = handle_command("/refactor test.py", history, selection, status_bar, "sess1")
                    assert cont is True

    def test_test_command(self, mock_setup, status_bar, selection, history):
        """Test /test command."""
        with patch('opsora_v2.run_agent_turn') as mock_agent:
            mock_agent.return_value = (history, selection)
            cont, _, _ = handle_command("/test test.py", history, selection, status_bar, "sess1")
            assert cont is True

    def test_fix_ci_command(self, mock_setup, status_bar, selection, history):
        """Test /fix-ci command."""
        with patch('opsora_v2.run_agent_turn') as mock_agent:
            mock_agent.return_value = (history, selection)
            cont, _, _ = handle_command("/fix-ci", history, selection, status_bar, "sess1")
            assert cont is True

    def test_solve_command(self, mock_setup, status_bar, selection, history):
        """Test /solve command."""
        with patch('opsora_v2.solve_problem', return_value={
            "think": "Thinking...",
            "plan": "Plan steps",
            "act": {"action": "Action", "output": "Output"},
            "verify": "Verified",
            "report": "Report",
            "status": "completed",
            "next_step": "Next"
        }) as mock_solve:
            cont, _, _ = handle_command("/solve fix this bug", history, selection, status_bar, "sess1")
            assert cont is True
            mock_solve.assert_called_once()

    def test_solve_command_no_problem(self, mock_setup, status_bar, selection, history):
        """Test /solve command without problem."""
        cont, _, _ = handle_command("/solve", history, selection, status_bar, "sess1")
        assert cont is True

    def test_unknown_command(self, mock_setup, status_bar, selection, history):
        """Test unknown command."""
        cont, _, _ = handle_command("/unknown", history, selection, status_bar, "sess1")
        assert cont is True
        # Should print error message
        mock_setup['console'].print.assert_called()

    def test_save_command(self, mock_setup, status_bar, selection, history):
        """Test /save command."""
        with patch('opsora_v2.save_session', return_value="session123") as mock_save:
            cont, _, _ = handle_command("/save My Session", history, selection, status_bar, "sess1")
            assert cont is True
            mock_save.assert_called_once()

    def test_delete_command(self, mock_setup, status_bar, selection, history):
        """Test /delete command."""
        with patch('opsora_v2.delete_session', return_value=True) as mock_delete:
            cont, _, _ = handle_command("/delete session123", history, selection, status_bar, "sess1")
            assert cont is True
            mock_delete.assert_called_with("session123")

    def test_delete_command_not_found(self, mock_setup, status_bar, selection, history):
        """Test /delete command for non-existent session."""
        with patch('opsora_v2.delete_session', return_value=False) as mock_delete:
            cont, _, _ = handle_command("/delete nonexistent", history, selection, status_bar, "sess1")
            assert cont is True

    def test_search_command(self, mock_setup, status_bar, selection, history):
        """Test /search command."""
        with patch('opsora_v2.web_search', return_value="Search results") as mock_search:
            cont, _, _ = handle_command("/search python tutorial", history, selection, status_bar, "sess1")
            assert cont is True
            mock_search.assert_called_with("python tutorial")

    def test_query_command(self, mock_setup, status_bar, selection, history):
        """Test /query command."""
        with patch('opsora_v2.db_query', return_value="Query results") as mock_query:
            cont, _, _ = handle_command("/query SELECT * FROM sessions", history, selection, status_bar, "sess1")
            assert cont is True
            mock_query.assert_called_with("SELECT * FROM sessions")

    def test_theme_command_list(self, mock_setup, status_bar, selection, history):
        """Test /theme command without argument (lists themes)."""
        with patch('opsora_v2.list_themes', return_value=["dark", "light"]):
            with patch('opsora_v2.get_theme', return_value={"name": "Dark"}):
                with patch('opsora_v2.load_theme_preference', return_value="dark"):
                    cont, _, _ = handle_command("/theme", history, selection, status_bar, "sess1")
                    assert cont is True

    def test_theme_command_set(self, mock_setup, status_bar, selection, history):
        """Test /theme command with valid theme."""
        with patch('opsora_v2.list_themes', return_value=["dark", "light"]):
            with patch('opsora_v2.get_theme', return_value={"name": "Light", "accent": "#fff"}):
                with patch('opsora_v2.save_theme_preference') as mock_save:
                    with patch('opsora_v2.set_theme_colors') as mock_set:
                        cont, _, _ = handle_command("/theme light", history, selection, status_bar, "sess1")
                        assert cont is True
                        mock_save.assert_called_with("light")
                        mock_set.assert_called_once()

    def test_verbose_command(self, mock_setup, status_bar, selection, history):
        """Test /verbose command."""
        with patch('opsora_v2.toggle_verbose', return_value=True) as mock_toggle:
            cont, _, _ = handle_command("/verbose", history, selection, status_bar, "sess1")
            assert cont is True
            mock_toggle.assert_called_once()

    def test_plugins_command(self, mock_setup, status_bar, selection, history):
        """Test /plugins command."""
        with patch('opsora_v2._plugin_manager') as mock_pm:
            mock_pm.status.return_value = {"plugin1": {"description": "Test plugin"}}
            cont, _, _ = handle_command("/plugins", history, selection, status_bar, "sess1")
            assert cont is True

    def test_cost_command(self, mock_setup, status_bar, selection, history):
        """Test /cost command."""
        with patch('opsora_v2._cost_tracker') as mock_tracker:
            mock_tracker.session_total.return_value = {
                "total_tokens": 1000,
                "total_cost": 0.001,
                "total_calls": 5,
                "by_model": {"qwen-plus": {"tokens": 1000, "cost": 0.001, "calls": 5}}
            }
            cont, _, _ = handle_command("/cost", history, selection, status_bar, "sess1")
            assert cont is True

    def test_translate_command(self, mock_setup, status_bar, selection, history):
        """Test /translate command."""
        with patch('opsora_v2.translate_text', return_value="Translated") as mock_translate:
            cont, _, _ = handle_command("/translate hello world", history, selection, status_bar, "sess1")
            assert cont is True
            mock_translate.assert_called_with("hello world", "Indonesian")

    def test_translate_command_en(self, mock_setup, status_bar, selection, history):
        """Test /translate command with en target."""
        with patch('opsora_v2.translate_text', return_value="Translated") as mock_translate:
            cont, _, _ = handle_command("/translate en halo dunia", history, selection, status_bar, "sess1")
            assert cont is True
            mock_translate.assert_called_with("halo dunia", "English")

    def test_vision_command(self, mock_setup, status_bar, selection, history):
        """Test /vision command."""
        with patch('opsora_v2.analyze_image', return_value="Image analysis") as mock_vision:
            cont, _, _ = handle_command("/vision image.png describe this", history, selection, status_bar, "sess1")
            assert cont is True
            mock_vision.assert_called_with("image.png", "describe this")

    def test_safety_command(self, mock_setup, status_bar, selection, history):
        """Test /safety command."""
        with patch('opsora_v2.check_command_safety', return_value={"safe": True, "reason": "OK", "model": "test"}) as mock_safety:
            cont, _, _ = handle_command("/safety rm -rf /tmp", history, selection, status_bar, "sess1")
            assert cont is True
            mock_safety.assert_called_with("rm -rf /tmp")

    def test_embed_command(self, mock_setup, status_bar, selection, history):
        """Test /embed command."""
        with patch('opsora_v2.generate_embedding', return_value=[0.1, 0.2, 0.3]) as mock_embed:
            cont, _, _ = handle_command("/embed test text", history, selection, status_bar, "sess1")
            assert cont is True
            mock_embed.assert_called_with("test text")

    def test_fork_command(self, mock_setup, status_bar, selection, history):
        """Test /fork command."""
        with patch('opsora_v2.generate_session_title', return_value="Forked Session"):
            with patch('opsora_v2.save_session', return_value="fork123") as mock_save:
                history.append({"role": "user", "content": "test"})
                cont, _, _ = handle_command("/fork", history, selection, status_bar, "sess1")
                assert cont is True
                mock_save.assert_called_once()

    def test_loop_command(self, mock_setup, status_bar, selection, history):
        """Test /loop command."""
        with patch('opsora_v2.is_aborted', side_effect=[False, False, True]):
            with patch('opsora_v2.run_agent_turn') as mock_agent:
                mock_agent.return_value = (history, selection)
                cont, _, _ = handle_command("/loop test task", history, selection, status_bar, "sess1")
                assert cont is True

    def test_auto_command(self, mock_setup, status_bar, selection, history):
        """Test /auto command."""
        with patch('opsora_v2.AutonomousAgent') as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent.run.return_value = MagicMock(success=True, summary="Done", subtasks_completed=3, subtasks_total=3, total_rounds=5)
            mock_agent_class.return_value = mock_agent

            cont, _, _ = handle_command("/auto build API", history, selection, status_bar, "sess1")
            assert cont is True
            mock_agent_class.assert_called_once()

    def test_abort_command(self, mock_setup, status_bar, selection, history):
        """Test /abort command."""
        with patch('opsora_v2.abort_agent') as mock_abort:
            cont, _, _ = handle_command("/abort", history, selection, status_bar, "sess1")
            assert cont is True
            mock_abort.assert_called_once()


class TestStatusBar:
    """Tests for StatusBar dataclass."""

    def test_status_bar_creation(self):
        bar = StatusBar(
            provider="alibaba",
            model="qwen-plus",
            approval_mode=opsora_v2.ApprovalMode.FULL_AUTO,
            cwd="/root",
            current_activity="Ready"
        )
        assert bar.provider == "alibaba"
        assert bar.model == "qwen-plus"
        assert bar.approval_mode == opsora_v2.ApprovalMode.FULL_AUTO


class TestSlashCompleter:
    """Tests for SlashCompleter class."""

    def test_completer_initialization(self):
        """Test completer can be instantiated."""
        from prompt_toolkit.completion import Completer
        completer = opsora_v2.SlashCompleter()
        assert isinstance(completer, Completer)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])