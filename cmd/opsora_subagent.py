"""Opsora Subagent System — Orchestrator-Workers pattern.

The main agent can spawn sub-agents to handle focused tasks in parallel,
then merge their results back into the main conversation.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


@dataclass
class SubagentTask:
    id: str
    name: str
    goal: str
    status: str = "pending"
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    tokens_used: int = 0


@dataclass
class SubagentResult:
    task: SubagentTask
    messages: list[dict[str, Any]] = field(default_factory=list)


class SubagentOrchestrator:
    """Manages parallel sub-agent tasks using the orchestrator-workers pattern."""

    def __init__(
        self,
        invoke_fn: Callable,
        tools: list[dict],
        system_prompt: str,
        max_workers: int = 3,
    ):
        self.invoke_fn = invoke_fn
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_workers = max_workers
        self.tasks: list[SubagentTask] = []
        self._counter = 0

    def plan_tasks(self, goal: str, provider: str, model: str) -> list[SubagentTask]:
        """Ask the orchestrator LLM to decompose a goal into sub-tasks."""
        orchestrator_prompt = (
            f"{self.system_prompt}\n\n"
            "You are the ORCHESTRATOR. Your job is to decompose the user's goal into "
            "2-4 focused sub-tasks. Return ONLY a JSON array of objects with 'name' and 'goal' keys.\n"
            "Example: [{\"name\": \"research\", \"goal\": \"Find API docs for X\"}, "
            "{\"name\": \"implement\", \"goal\": \"Write the code for Y\"}]\n"
            "Do NOT include any text outside the JSON array."
        )

        messages = [
            {"role": "system", "content": orchestrator_prompt},
            {"role": "user", "content": goal},
        ]

        try:
            response = self.invoke_fn(provider, model, messages, use_tools=False)
            content = ""
            if hasattr(response, "choices"):
                content = response.choices[0].message.content or ""
            elif isinstance(response, dict):
                content = response.get("content", "")

            tasks_data = json.loads(content.strip())
            self.tasks = []
            for i, td in enumerate(tasks_data):
                self._counter += 1
                self.tasks.append(SubagentTask(
                    id=f"sa-{self._counter:03d}",
                    name=td.get("name", f"task-{i}"),
                    goal=td.get("goal", ""),
                ))
            return self.tasks
        except (json.JSONDecodeError, Exception) as e:
            console.print(f"[yellow]⚠ Orchestrator could not decompose: {e}[/yellow]")
            self._counter += 1
            task = SubagentTask(id=f"sa-{self._counter:03d}", name="single", goal=goal)
            self.tasks = [task]
            return self.tasks

    def execute_all(self, provider: str, model: str) -> list[SubagentResult]:
        """Execute all planned tasks in parallel using ThreadPoolExecutor."""
        results: list[SubagentResult] = []
        self._render_plan()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for task in self.tasks:
                future = executor.submit(self._run_task, task, provider, model)
                futures[future] = task

            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    self._render_task_done(result)
                except Exception as e:
                    task.status = "error"
                    task.error = str(e)
                    results.append(SubagentResult(task=task))
                    self._render_task_done(SubagentResult(task=task))

        return results

    def _run_task(self, task: SubagentTask, provider: str, model: str) -> SubagentResult:
        task.status = "running"
        task.started_at = time.time()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task.goal},
        ]

        for round_idx in range(5):
            try:
                response = self.invoke_fn(provider, model, messages, use_tools=True)

                if hasattr(response, "choices"):
                    msg = response.choices[0].message
                else:
                    msg = response

                msg_dict = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else {"role": "assistant", "content": getattr(msg, "content", "")}
                messages.append(msg_dict)

                content = getattr(msg, "content", None) or ""
                tool_calls = getattr(msg, "tool_calls", None)

                if content and not tool_calls:
                    task.result = content
                    task.status = "done"
                    task.finished_at = time.time()
                    task.tokens_used += len(content.split())
                    return SubagentResult(task=task, messages=messages)

                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
                        name = fn.name if hasattr(fn, "name") else fn.get("name", "")
                        args_raw = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", "{}")
                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                        output = self._execute_tool(name, args)
                        tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": output})
                else:
                    task.status = "done"
                    task.finished_at = time.time()
                    return SubagentResult(task=task, messages=messages)

            except Exception as e:
                task.status = "error"
                task.error = str(e)
                task.finished_at = time.time()
                return SubagentResult(task=task, messages=messages)

        task.status = "done"
        task.finished_at = time.time()
        return SubagentResult(task=task, messages=messages)

    def _execute_tool(self, name: str, args: dict) -> str:
        """Delegate to the main tool executor via a simple import."""
        try:
            from opsora_v2 import execute_tool
            return execute_tool(name, args)
        except ImportError:
            return f"Tool {name} not available in subagent context."

    def _render_plan(self) -> None:
        table = Table(title="🤖 Subagent Plan", box=box.ROUNDED, border_style="cyan")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="cyan")
        table.add_column("Goal")
        for i, task in enumerate(self.tasks, 1):
            table.add_row(str(i), task.name, task.goal[:80])
        console.print(table)

    def _render_task_done(self, result: SubagentResult) -> None:
        task = result.task
        elapsed = task.finished_at - task.started_at if task.finished_at else 0
        if task.status == "done":
            icon = "✅"
            style = "green"
        else:
            icon = "❌"
            style = "red"

        preview = task.result[:200] if task.result else task.error[:200] if task.error else "(empty)"
        console.print(
            f"  {icon} [{style}]{task.name}[/{style}] "
            f"[dim]({elapsed:.1f}s, ~{task.tokens_used} tok)[/dim]"
        )
        if task.result:
            console.print(Panel(
                preview + ("…" if len(task.result) > 200 else ""),
                title=f"↳ {task.name} result",
                border_style="dim cyan",
                box=box.SIMPLE,
            ))

    def synthesize(self, results: list[SubagentResult], provider: str, model: str) -> str:
        """Ask the orchestrator to merge all sub-agent results into a final answer."""
        combined = ""
        for r in results:
            combined += f"\n\n### {r.task.name}\n{r.task.result or r.task.error or '(no output)'}"

        messages = [
            {"role": "system", "content": f"{self.system_prompt}\n\nSynthesize the sub-agent results into a coherent final answer. Be concise."},
            {"role": "user", "content": f"Synthesize these results:\n{combined}"},
        ]

        try:
            response = self.invoke_fn(provider, model, messages, use_tools=False)
            if hasattr(response, "choices"):
                return response.choices[0].message.content or ""
            return str(response)
        except Exception as e:
            return f"Synthesis failed: {e}\n\nRaw results:\n{combined}"
