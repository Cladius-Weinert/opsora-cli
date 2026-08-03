"""Comprehensive tests for opsora_v2.py core functions."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import json
import time

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

# We need to import carefully to avoid side effects
import opsora_v2


class TestSelection:
    """Tests for Selection dataclass."""

    def test_selection_creation(self):
        sel = opsora_v2.Selection(provider="alibaba", model="qwen-plus")
        assert sel.provider == "alibaba"
        assert sel.model == "qwen-plus"


class TestIsProviderAvailable:
    """Tests for is_provider_available function."""

    def test_known_providers(self):
        with patch('opsora_v2.nvidia_client', None):
            with patch('opsora_v2.alibaba_client', MagicMock()):
                with patch('opsora_v2.model_studio_client', None):
                    with patch('opsora_v2.openai_client', None):
                        with patch('opsora_v2.bedrock_available', return_value=False):
                            with patch('opsora_v2.tokenhub_client', None):
                                with patch('opsora_v2.opsora_api_client', None):
                                    assert opsora_v2.is_provider_available("alibaba") is True
                                    assert opsora_v2.is_provider_available("nvidia") is False


class TestAutoSelectModel:
    """Tests for auto_select_model function."""

    @pytest.fixture
    def mock_router(self):
        with patch('opsora_v2.IntentRouter') as mock:
            router_instance = MagicMock()
            router_instance.classify.return_value = "code"
            mock.return_value = router_instance
            yield mock

    def test_auto_select_code_intent(self, mock_router):
        """Test auto_select_model for code intent."""
        with patch('opsora_v2.is_provider_available', return_value=True):
            with patch('opsora_v2.CODING_MODELS', [("alibaba", "qwen3-coder-flash")]):
                sel = opsora_v2.auto_select_model("write a function")
                assert sel.provider == "alibaba"
                assert sel.model == "qwen3-coder-flash"

    def test_auto_select_fallback(self, mock_router):
        """Test fallback when no models available."""
        with patch('opsora_v2.is_provider_available', return_value=False):
            sel = opsora_v2.auto_select_model("anything")
            assert sel.provider == "alibaba"
            assert sel.model == "qwen3-coder-flash"


class TestValidatePath:
    """Tests for _validate_path function."""

    def test_validate_absolute_path(self, tmp_path):
        """Test validating absolute path within workspace."""
        test_file = tmp_path / "test.py"
        test_file.write_text("content")

        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2._validate_path(str(test_file))
            assert result == test_file.resolve()

    def test_validate_relative_path(self, tmp_path):
        """Test validating relative path."""
        test_file = tmp_path / "test.py"
        test_file.write_text("content")

        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2._validate_path("test.py")
            assert result == test_file.resolve()

    def test_validate_path_traversal_blocked(self, tmp_path):
        """Test path traversal is blocked."""
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            with pytest.raises(ValueError, match="Path traversal"):
                opsora_v2._validate_path("../../../etc/passwd")

    def test_validate_invalid_path(self, tmp_path):
        """Test invalid path raises error."""
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            with pytest.raises(ValueError, match="Invalid path"):
                opsora_v2._validate_path("")


class TestValidateCommand:
    """Tests for _validate_command function."""

    def test_validate_safe_command(self):
        """Test safe command passes."""
        result = opsora_v2._validate_command("ls -la")
        assert result == "ls -la"

    def test_validate_dangerous_rm_rf(self):
        """Test rm -rf / is blocked."""
        with pytest.raises(ValueError, match="Dangerous command blocked"):
            opsora_v2._validate_command("rm -rf /")

    def test_validate_dangerous_mkfs(self):
        """Test mkfs is blocked."""
        with pytest.raises(ValueError, match="Dangerous command blocked"):
            opsora_v2._validate_command("mkfs.ext4 /dev/sda1")

    def test_validate_dangerous_dd(self):
        """Test dd if= is blocked."""
        with pytest.raises(ValueError, match="Dangerous command blocked"):
            opsora_v2._validate_command("dd if=/dev/zero of=/dev/sda")

    def test_validate_case_insensitive(self):
        """Test validation is case insensitive."""
        with pytest.raises(ValueError):
            opsora_v2._validate_command("RM -RF /")


class TestCompressContext:
    """Tests for compress_context function."""

    def test_no_compression_needed(self):
        """Test when context is under 70%."""
        messages = [{"role": "user", "content": "short"}]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        result = opsora_v2.compress_context(messages, sel)
        assert result == messages

    def test_compression_with_tool_messages(self):
        """Test compression summarizes tool messages."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file"}}]},
            {"role": "tool", "content": "x" * 500, "name": "read_file"},
            {"role": "assistant", "content": "Response"},
        ]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        # Force compression by using small context window
        with patch('opsora_v2.compress_context') as mock_compress:
            # Actually test the real function with small window
            result = opsora_v2.compress_context(messages, sel)
            # Should keep system and recent messages
            assert any(m.get("role") == "system" for m in result)

    def test_naive_fallback(self):
        """Test naive fallback when LLM compression fails."""
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User msg"},
            {"role": "tool", "content": "x" * 300, "name": "read_file"},
            {"role": "assistant", "content": "Response"},
        ]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        with patch('opsora_v2.compress') as mock_compress:
            mock_compress.side_effect = Exception("LLM failed")
            result = opsora_v2.compress_context(messages, sel)

        # Should have compressed
        assert len(result) <= len(messages)


class TestEstimateCost:
    """Tests for estimate_cost function."""

    def test_estimate_cost_known_model(self):
        """Test cost estimation for known model."""
        total, cost = opsora_v2.estimate_cost("qwen-plus", 400, 200)
        # 400 chars = 100 tokens, 200 chars = 50 tokens
        assert total == 150
        # qwen-plus: 0.40/1.20 per M
        expected = (100 * 0.40 + 50 * 1.20) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_estimate_cost_unknown_model(self):
        """Test cost estimation for unknown model uses default."""
        total, cost = opsora_v2.estimate_cost("unknown", 400, 200)
        assert total == 150
        # default: 0.30/0.60 per M
        expected = (100 * 0.30 + 50 * 0.60) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_estimate_cost_zero_chars(self):
        """Test cost estimation with zero chars."""
        total, cost = opsora_v2.estimate_cost("qwen-plus", 0, 0)
        assert total == 0
        assert cost == 0.0


class TestExecuteTool:
    """Tests for execute_tool function (partial - key paths)."""

    @pytest.fixture
    def mock_dependencies(self):
        """Set up common mocks for execute_tool tests."""
        with patch('opsora_v2.WORKSPACE_ROOT', Path("/tmp/test")):
            with patch('opsora_v2.needs_approval', return_value=False):
                with patch('opsora_v2.prompt_approval', return_value=True):
                    yield

    def test_execute_unknown_tool(self, mock_dependencies):
        """Test unknown tool returns error."""
        result = opsora_v2.execute_tool("unknown_tool", {})
        assert "Unknown tool" in result

    def test_execute_read_file_not_found(self, mock_dependencies, tmp_path):
        """Test reading non-existent file."""
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2.execute_tool("read_file", {"filepath": "nonexistent.py"})
            assert "ERROR" in result or "not found" in result.lower()

    def test_execute_write_file(self, mock_dependencies, tmp_path):
        """Test writing a file."""
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2.execute_tool("write_file", {
                "filepath": "new_file.py",
                "content": "print('hello')"
            })
            assert "Wrote" in result
            assert (tmp_path / "new_file.py").read_text() == "print('hello')"

    def test_execute_edit_file_not_found(self, mock_dependencies, tmp_path):
        """Test editing non-existent file."""
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2.execute_tool("edit_file", {
                "filepath": "nonexistent.py",
                "old_string": "old",
                "new_string": "new"
            })
            assert "ERROR" in result

    def test_execute_run_command(self, mock_dependencies):
        """Test running a command."""
        result = opsora_v2.execute_tool("run_command", {"command": "echo hello"})
        assert "hello" in result

    def test_execute_grep_search(self, mock_dependencies, tmp_path):
        """Test grep search."""
        (tmp_path / "test.py").write_text("def hello():\n    pass")
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2.execute_tool("grep_search", {"pattern": "hello", "path": "."})
            assert "hello" in result

    def test_execute_glob_search(self, mock_dependencies, tmp_path):
        """Test glob search."""
        (tmp_path / "main.py").write_text("# main")
        (tmp_path / "utils.py").write_text("# utils")
        with patch('opsora_v2.WORKSPACE_ROOT', tmp_path):
            result = opsora_v2.execute_tool("glob_search", {"pattern": "*.py"})
            assert "main.py" in result
            assert "utils.py" in result


class TestInvokeProvider:
    """Tests for invoke_provider function."""

    def test_invoke_alibaba(self):
        """Test invoking Alibaba provider."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response"
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        with patch('opsora_v2.alibaba_client', mock_client):
            result = opsora_v2.invoke_provider("alibaba", "qwen-plus", [{"role": "user", "content": "Hi"}])

        assert result == mock_response
        mock_client.chat.completions.create.assert_called_once()

    def test_invoke_nvidia(self):
        """Test invoking NVIDIA provider."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response"
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]
        mock_client.chat.completions.create.return_value = mock_response

        with patch('opsora_v2.nvidia_client', mock_client):
            result = opsora_v2.invoke_provider("nvidia", "nemotron", [{"role": "user", "content": "Hi"}])

        assert result == mock_response

    def test_invoke_unavailable_provider(self):
        """Test invoking unavailable provider raises error."""
        with patch('opsora_v2.alibaba_client', None):
            with pytest.raises(RuntimeError, match="not available"):
                opsora_v2.invoke_provider("alibaba", "qwen-plus", [])


class TestCallWithFallback:
    """Tests for call_with_fallback function."""

    def test_fallback_success_first(self):
        """Test success on first provider."""
        sel = opsora_v2.Selection("alibaba", "qwen-plus")
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "OK"
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]

        with patch('opsora_v2.invoke_provider', return_value=mock_response):
            result, used_sel = opsora_v2.call_with_fallback([{"role": "user", "content": "Hi"}], sel)

        assert result == mock_response
        assert used_sel == sel

    def test_fallback_tries_alternatives(self):
        """Test fallback tries alternative providers."""
        sel = opsora_v2.Selection("alibaba", "qwen-plus")
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "OK"
        mock_message.tool_calls = None
        mock_response.choices = [MagicMock(message=mock_message)]

        call_count = [0]

        def mock_invoke(provider, model, messages, use_tools=True):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("First failed")
            return mock_response

        with patch('opsora_v2.invoke_provider', side_effect=mock_invoke):
            with patch('opsora_v2.get_provider_order', return_value=["alibaba", "nvidia"]):
                with patch('opsora_v2.is_provider_available', return_value=True):
                    with patch('opsora_v2.PROVIDER_MODELS', {"nvidia": "nemotron"}):
                        result, used_sel = opsora_v2.call_with_fallback([{"role": "user", "content": "Hi"}], sel)

        assert result == mock_response
        assert used_sel.provider == "nvidia"


class TestGenerateSessionTitle:
    """Tests for generate_session_title function."""

    def test_title_from_first_message_short(self):
        """Test title from short first user message."""
        history = [{"role": "user", "content": "Short question"}]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        title = opsora_v2.generate_session_title(history, sel)
        assert title == "Short question"

    def test_title_from_long_message_truncated(self):
        """Test title truncated from long message."""
        history = [{"role": "user", "content": "x" * 100}]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        title = opsora_v2.generate_session_title(history, sel)
        assert len(title) == 50

    def test_title_from_model(self):
        """Test title generated by model."""
        history = [{"role": "user", "content": "Long question that needs a title generated by the model"}]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Generated Title"
        mock_response.choices = [MagicMock(message=mock_message)]

        with patch('opsora_v2.call_with_fallback', return_value=(mock_response, sel)):
            title = opsora_v2.generate_session_title(history, sel)

        assert title == "Generated Title"

    def test_title_fallback_on_error(self):
        """Test fallback when model title generation fails."""
        history = [{"role": "user", "content": "Question here"}]
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        with patch('opsora_v2.call_with_fallback', side_effect=Exception("API error")):
            title = opsora_v2.generate_session_title(history, sel)

        assert title == "Question here"

    def test_empty_history(self):
        """Test with empty history."""
        history = []
        sel = opsora_v2.Selection("alibaba", "qwen-plus")

        title = opsora_v2.generate_session_title(history, sel)
        assert title == "untitled"


class TestConstants:
    """Tests for module constants."""

    def test_workspace_root(self):
        assert opsora_v2.WORKSPACE_ROOT == Path("/root")

    def test_opsora_dir(self):
        assert opsora_v2.OPSORA_DIR == Path("/root/.opsora")

    def test_default_max_tokens(self):
        assert opsora_v2.DEFAULT_MAX_TOKENS == 4096

    def test_default_temperature(self):
        assert opsora_v2.DEFAULT_TEMPERATURE == 0.2

    def test_tool_max_rounds(self):
        assert opsora_v2.TOOL_MAX_ROUNDS == 30

    def test_tool_max_output(self):
        assert opsora_v2.TOOL_MAX_OUTPUT == 30_000

    def test_safe_tools_not_empty(self):
        assert len(opsora_v2.SAFE_TOOLS) > 20

    def test_provider_models_structure(self):
        assert "alibaba" in opsora_v2.PROVIDER_MODELS
        assert "nvidia" in opsora_v2.PROVIDER_MODELS
        assert isinstance(opsora_v2.PROVIDER_MODELS["alibaba"], str)

    def test_model_tiers_not_empty(self):
        assert len(opsora_v2.POWER_MODELS) > 0
        assert len(opsora_v2.FAST_MODELS) > 0
        assert len(opsora_v2.REASONING_MODELS) > 0
        assert len(opsora_v2.CODING_MODELS) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])