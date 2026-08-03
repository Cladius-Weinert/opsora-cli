"""Comprehensive tests for opsora_subagent.py sub-agent orchestration."""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import json

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_subagent


class TestSubagentTask:
    """Tests for SubagentTask dataclass."""

    def test_task_creation(self):
        task = opsora_subagent.SubagentTask(
            id="sa-001",
            name="research",
            goal="Find API docs"
        )
        assert task.id == "sa-001"
        assert task.name == "research"
        assert task.goal == "Find API docs"
        assert task.status == "pending"
        assert task.result == ""
        assert task.error == ""
        assert task.started_at == 0.0
        assert task.finished_at == 0.0
        assert task.tokens_used == 0

    def test_task_with_custom_values(self):
        task = opsora_subagent.SubagentTask(
            id="sa-002",
            name="implement",
            goal="Write code",
            status="running",
            result="Done",
            error="None",
            started_at=1000.0,
            finished_at=1010.0,
            tokens_used=500
        )
        assert task.status == "running"
        assert task.result == "Done"
        assert task.tokens_used == 500


class TestSubagentResult:
    """Tests for SubagentResult dataclass."""

    def test_result_creation(self):
        task = opsora_subagent.SubagentTask(id="sa-001", name="test", goal="test")
        result = opsora_subagent.SubagentResult(task=task, messages=[{"role": "user", "content": "hi"}])
        assert result.task == task
        assert len(result.messages) == 1

    def test_result_default_messages(self):
        task = opsora_subagent.SubagentTask(id="sa-001", name="test", goal="test")
        result = opsora_subagent.SubagentResult(task=task)
        assert result.messages == []


class TestSubagentOrchestrator:
    """Tests for SubagentOrchestrator class."""

    @pytest.fixture
    def mock_invoke_fn(self):
        """Mock invoke function that returns a response."""
        def invoke(provider, model, messages, use_tools=True):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_message.content = "Task completed successfully"
            mock_message.tool_calls = None
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response
        return invoke

    @pytest.fixture
    def mock_tools(self):
        """Mock tools list."""
        return [{"type": "function", "function": {"name": "read_file", "description": "Read a file"}}]

    @pytest.fixture
    def orchestrator(self, mock_invoke_fn, mock_tools):
        return opsora_subagent.SubagentOrchestrator(
            invoke_fn=mock_invoke_fn,
            tools=mock_tools,
            system_prompt="Test system prompt",
            max_workers=2
        )

    def test_orchestrator_initialization(self, orchestrator):
        assert orchestrator.max_workers == 2
        assert orchestrator.tasks == []
        assert orchestrator._counter == 0

    def test_plan_tasks_success(self, orchestrator, mock_invoke_fn):
        """Test successful task planning."""
        # Mock the invoke_fn to return valid JSON
        def mock_invoke_json(provider, model, messages, use_tools=False):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_message.content = json.dumps([
                {"name": "research", "goal": "Find API documentation"},
                {"name": "implement", "goal": "Write the implementation"}
            ])
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke_json
        tasks = orchestrator.plan_tasks("Build a REST API", "alibaba", "qwen-plus")

        assert len(tasks) == 2
        assert tasks[0].name == "research"
        assert tasks[1].name == "implement"
        assert tasks[0].id == "sa-001"
        assert tasks[1].id == "sa-002"

    def test_plan_tasks_json_decode_error(self, orchestrator):
        """Test fallback when JSON parsing fails."""
        def mock_invoke_bad(provider, model, messages, use_tools=False):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_message.content = "not valid json"
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke_bad
        tasks = orchestrator.plan_tasks("Build something", "alibaba", "qwen-plus")

        # Should fallback to single task
        assert len(tasks) == 1
        assert tasks[0].name == "single"
        assert tasks[0].goal == "Build something"

    def test_plan_tasks_exception_fallback(self, orchestrator):
        """Test fallback when invoke fails."""
        def mock_invoke_fail(provider, model, messages, use_tools=False):
            raise Exception("API error")

        orchestrator.invoke_fn = mock_invoke_fail
        tasks = orchestrator.plan_tasks("Build something", "alibaba", "qwen-plus")

        assert len(tasks) == 1
        assert tasks[0].name == "single"

    def test_execute_all_parallel(self, orchestrator):
        """Test parallel execution of tasks."""
        # Create tasks
        task1 = opsora_subagent.SubagentTask(id="sa-001", name="task1", goal="Do task 1")
        task2 = opsora_subagent.SubagentTask(id="sa-002", name="task2", goal="Do task 2")
        orchestrator.tasks = [task1, task2]

        # Mock _run_task to return results quickly
        def mock_run_task(task, provider, model):
            task.status = "done"
            task.result = f"Result for {task.name}"
            task.finished_at = task.started_at + 1.0
            return opsora_subagent.SubagentResult(task=task, messages=[])

        orchestrator._run_task = mock_run_task

        results = orchestrator.execute_all("alibaba", "qwen-plus")

        assert len(results) == 2
        assert all(r.task.status == "done" for r in results)
        assert results[0].task.result == "Result for task1"
        assert results[1].task.result == "Result for task2"

    def test_execute_all_handles_errors(self, orchestrator):
        """Test error handling in parallel execution."""
        task1 = opsora_subagent.SubagentTask(id="sa-001", name="success", goal="OK")
        task2 = opsora_subagent.SubagentTask(id="sa-002", name="fail", goal="Fail")
        orchestrator.tasks = [task1, task2]

        def mock_run_task(task, provider, model):
            if task.name == "fail":
                raise Exception("Task failed")
            task.status = "done"
            task.result = "Success"
            return opsora_subagent.SubagentResult(task=task, messages=[])

        orchestrator._run_task = mock_run_task

        results = orchestrator.execute_all("alibaba", "qwen-plus")

        assert len(results) == 2
        success = next(r for r in results if r.task.name == "success")
        fail = next(r for r in results if r.task.name == "fail")
        assert success.task.status == "done"
        assert fail.task.status == "error"
        assert "Task failed" in fail.task.error

    def test_run_task_no_tool_calls(self, orchestrator):
        """Test _run_task when model returns no tool calls."""
        task = opsora_subagent.SubagentTask(id="sa-001", name="test", goal="Simple task")

        def mock_invoke(provider, model, messages, use_tools=True):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_message.content = "Direct answer"
            mock_message.tool_calls = None
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke

        result = orchestrator._run_task(task, "alibaba", "qwen-plus")

        assert result.task.status == "done"
        assert result.task.result == "Direct answer"

    def test_run_task_with_tool_calls(self, orchestrator):
        """Test _run_task when model makes tool calls."""
        task = opsora_subagent.SubagentTask(id="sa-001", name="test", goal="Use tools")

        call_count = [0]

        def mock_invoke(provider, model, messages, use_tools=True):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_message = MagicMock()
            if call_count[0] == 1:
                # First call: return tool call
                mock_tc = MagicMock()
                mock_tc.id = "call-1"
                mock_tc.function = MagicMock()
                mock_tc.function.name = "read_file"
                mock_tc.function.arguments = '{"filepath": "test.py"}'
                mock_message.tool_calls = [mock_tc]
                mock_message.content = None
            else:
                # Second call: return final answer
                mock_message.tool_calls = None
                mock_message.content = "Tool result processed"
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke

        with patch('opsora_subagent.execute_tool', return_value="File content"):
            result = orchestrator._run_task(task, "alibaba", "qwen-plus")

        assert result.task.status == "done"
        assert result.task.result == "Tool result processed"

    def test_run_task_max_rounds(self, orchestrator):
        """Test _run_task respects max rounds."""
        task = opsora_subagent.SubagentTask(id="sa-001", name="test", goal="Long task")

        def mock_invoke(provider, model, messages, use_tools=True):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_tc = MagicMock()
            mock_tc.id = "call-1"
            mock_tc.function = MagicMock()
            mock_tc.function.name = "read_file"
            mock_tc.function.arguments = '{"filepath": "test.py"}'
            mock_message.tool_calls = [mock_tc]
            mock_message.content = None
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke

        with patch('opsora_subagent.execute_tool', return_value="Content"):
            result = orchestrator._run_task(task, "alibaba", "qwen-plus")

        # Should stop after max rounds (5) and mark done
        assert result.task.status == "done"

    def test_execute_tool_delegates(self, orchestrator):
        """Test _execute_tool delegates to main execute_tool."""
        with patch('opsora_v2.execute_tool', return_value="Tool output") as mock_exec:
            result = orchestrator._execute_tool("read_file", {"filepath": "test.py"})
            assert result == "Tool output"
            mock_exec.assert_called_once_with("read_file", {"filepath": "test.py"})

    def test_execute_tool_import_error(self, orchestrator):
        """Test _execute_tool handles import error."""
        with patch('opsora_subagent.execute_tool', side_effect=ImportError):
            result = orchestrator._execute_tool("read_file", {"filepath": "test.py"})
            assert "not available in subagent context" in result

    def test_synthesize_success(self, orchestrator):
        """Test synthesize combines results."""
        results = [
            opsora_subagent.SubagentResult(
                task=opsora_subagent.SubagentTask(id="sa-001", name="research", goal="", result="Found docs")
            ),
            opsora_subagent.SubagentResult(
                task=opsora_subagent.SubagentTask(id="sa-002", name="implement", goal="", result="Code written")
            )
        ]

        def mock_invoke(provider, model, messages, use_tools=False):
            mock_response = MagicMock()
            mock_message = MagicMock()
            mock_message.content = "Final synthesized result"
            mock_response.choices = [MagicMock(message=mock_message)]
            return mock_response

        orchestrator.invoke_fn = mock_invoke

        result = orchestrator.synthesize(results, "alibaba", "qwen-plus")
        assert result == "Final synthesized result"

    def test_synthesize_failure(self, orchestrator):
        """Test synthesize handles failure."""
        results = [
            opsora_subagent.SubagentResult(
                task=opsora_subagent.SubagentTask(id="sa-001", name="test", goal="", result="OK")
            )
        ]

        def mock_invoke_fail(provider, model, messages, use_tools=False):
            raise Exception("Synthesis failed")

        orchestrator.invoke_fn = mock_invoke_fail

        result = orchestrator.synthesize(results, "alibaba", "qwen-plus")
        assert "Synthesis failed" in result
        assert "Raw results" in result


class TestRenderMethods:
    """Tests for render methods (smoke tests)."""

    def test_render_plan(self, orchestrator):
        """Test _render_plan doesn't crash."""
        orchestrator.tasks = [
            opsora_subagent.SubagentTask(id="sa-001", name="task1", goal="Goal 1"),
            opsora_subagent.SubagentTask(id="sa-002", name="task2", goal="Goal 2"),
        ]
        # Should not raise
        orchestrator._render_plan()

    def test_render_task_done(self, orchestrator):
        """Test _render_task_done doesn't crash."""
        task = opsora_subagent.SubagentTask(
            id="sa-001", name="test", goal="", status="done",
            result="Result here", started_at=1000, finished_at=1005, tokens_used=100
        )
        result = opsora_subagent.SubagentResult(task=task)
        orchestrator._render_task_done(result)

        # Test error case
        task.status = "error"
        task.error = "Something went wrong"
        orchestrator._render_task_done(result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])