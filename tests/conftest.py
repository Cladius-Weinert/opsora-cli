"""Shared pytest fixtures for Opsora CLI tests."""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Add package source directory to path so tests import the current
# opsora_cmd modules (not stale installed copies).
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client that returns canned responses."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Test response"
    mock_message.tool_calls = None
    mock_message.model_dump.return_value = {"role": "assistant", "content": "Test response"}
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


@pytest.fixture
def mock_env(monkeypatch):
    """Set up environment variables for testing."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope-key")
    monkeypatch.setenv("OPSORA_PROVIDER_ORDER", "nvidia,alibaba")


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with sample files."""
    # Create sample files
    (tmp_path / "sample.py").write_text("# Sample Python file\nprint('hello')\n")
    (tmp_path / "sample.md").write_text("# Sample Markdown\nThis is a test.\n")
    (tmp_path / "sample.json").write_text('{"key": "value"}\n')
    
    # Create .opsora directory with memory.db
    opsora_dir = tmp_path / ".opsora"
    opsora_dir.mkdir()
    (opsora_dir / "memory.db").write_text("")
    
    return tmp_path


@pytest.fixture
def sample_messages():
    """Sample conversation messages for testing."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
        {"role": "tool", "content": "Tool result here", "name": "read_file"},
        {"role": "user", "content": "Show me more examples."},
        {"role": "assistant", "content": "Here are more examples..."},
    ]
