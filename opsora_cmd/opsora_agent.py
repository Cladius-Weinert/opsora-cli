"""Opsora Autonomous Agent — Loops until task is done.

Architecture:
  ANALYZE → PLAN → [ACT → VERIFY → NEXT/RETRY] → REPORT

Key features:
  - Decomposes complex tasks into subtasks
  - Retries failed actions with different strategies (max 3 attempts)
  - Verifies completion before stopping
  - Compresses context between subtasks
  - Shows progress via todo_write display
  - Kill switch via /abort
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from rich.console import Console
from rich.text import Text

console = Console()


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class SubTask:
    id: int
    description: str
    status: str = "pending"  # pending, in_progress, done, failed, skipped
    result: str = ""
    attempts: int = 0
    max_attempts: int = 3


@dataclass
class AgentResult:
    success: bool
    summary: str
    subtasks_completed: int = 0
    subtasks_total: int = 0
    total_rounds: int = 0
    total_cost: float = 0.0


# ============================================================================
# Prompts
# ============================================================================

PLANNING_PROMPT = """Kamu adalah task planner. User meminta sesuatu dan kamu harus memecahnya jadi subtask konkret.

Aturan:
- Buat 2-8 subtask (jangan terlalu sedikit atau terlalu banyak)
- Setiap subtask harus spesifik dan actionable (bisa dikerjakan dalam 1-3 tool calls)
- Urutkan dari yang paling fundamental ke yang paling akhir
- Kalau task sederhana (< 2 langkah), buat 1-2 subtask saja
- JANGAN buat subtask "verifikasi" terpisah — verifikasi itu bagian dari setiap subtask

Return HANYA JSON array, tanpa teks lain:
[{"id": 1, "description": "..."}, {"id": 2, "description": "..."}]
"""

VERIFICATION_PROMPT = """Apakah subtask ini sudah SELESAI berdasarkan hasil yang ada?

Subtask: {subtask}
Hasil: {result}

Jawab JSON: {{"done": true/false, "reason": "alasan singkat"}}
Hanya JSON, tanpa teks lain."""

FAILURE_ANALYSIS_PROMPT = """Tool call gagal. Analisis kenapa dan kasih alternatif.

Command yang gagal: {command}
Error: {error}
Percobaan ke: {attempt}/3

Kasih 1 alternatif approach yang berbeda. Jawab singkat (1-2 kalimat)."""

COMPLETION_PROMPT = """User meminta: {request}

Subtask yang sudah selesai:
{completed}

Apakah SEMUA yang diminta user sudah terpenuhi?
Jawab JSON: {{"done": true/false, "remaining": ["yang belum"], "summary": "ringkasan singkat"}}
Hanya JSON, tanpa teks lain."""


# ============================================================================
# Autonomous Agent
# ============================================================================

_abort_flag = False


def abort_agent():
    """Signal the agent to stop."""
    global _abort_flag
    _abort_flag = True


def is_aborted() -> bool:
    return _abort_flag


def reset_abort():
    global _abort_flag
    _abort_flag = False


class AutonomousAgent:
    """Fully autonomous agent that decomposes, executes, verifies, and loops."""

    def __init__(
        self,
        invoke_fn: Callable,
        execute_tool_fn: Callable,
        tools: list[dict],
        system_prompt: str,
        max_subtask_rounds: int = 8,
        render_fn: Optional[Callable] = None,
    ):
        self.invoke_fn = invoke_fn
        self.execute_tool_fn = execute_tool_fn
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_subtask_rounds = max_subtask_rounds
        self.render_fn = render_fn  # For rendering tool calls
        self.subtasks: list[SubTask] = []
        self.total_rounds = 0

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def plan(self, user_request: str, provider: str, model: str) -> list[SubTask]:
        """Decompose user request into subtasks using fast LLM."""
        messages = [
            {"role": "system", "content": PLANNING_PROMPT},
            {"role": "user", "content": user_request},
        ]
        try:
            resp = self.invoke_fn(provider, model, messages, use_tools=False)
            content = ""
            if hasattr(resp, "choices"):
                content = resp.choices[0].message.content or ""
            elif isinstance(resp, dict):
                content = resp.get("content", "")

            # Extract JSON from response
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)

            tasks_data = json.loads(content)
            self.subtasks = [
                SubTask(id=t.get("id", i + 1), description=t.get("description", f"Step {i+1}"))
                for i, t in enumerate(tasks_data)
            ]
        except (json.JSONDecodeError, Exception) as e:
            # Fallback: treat entire request as one subtask
            self.subtasks = [SubTask(id=1, description=user_request)]

        self._render_plan()
        return self.subtasks

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_subtask(
        self, subtask: SubTask, provider: str, model: str, history: list[dict]
    ) -> tuple[str, bool]:
        """Execute a single subtask with retry logic.

        Returns (result_text, success_bool).
        """
        subtask.status = "in_progress"
        self._render_progress()

        messages = [
            {"role": "system", "content": self.system_prompt},
            *history[-10:],  # Keep last 10 messages for context
            {"role": "user", "content": f"Kerjain subtask ini: {subtask.description}\n\nGunakan tools yang diperlukan. Kalau gagal, coba approach lain."},
        ]

        for attempt in range(1, subtask.max_attempts + 1):
            subtask.attempts = attempt
            if is_aborted():
                subtask.status = "skipped"
                return "Aborted by user.", False

            try:
                # Run tool-calling loop for this subtask
                result, success = self._run_tool_loop(messages, provider, model, attempt)
                subtask.result = result

                if success:
                    # Verify completion
                    if self._verify_subtask(subtask, provider, model):
                        subtask.status = "done"
                        self._render_progress()
                        return result, True
                    else:
                        # Not fully done — add continuation
                        messages.append({"role": "assistant", "content": result})
                        messages.append({"role": "user", "content": "Subtask belum sepenuhnya selesai. Lanjutin sampai beres."})
                        continue
                else:
                    # Failed — analyze and retry with different approach
                    if attempt < subtask.max_attempts:
                        alt = self._analyze_failure(subtask, result, attempt, provider, model)
                        messages.append({"role": "assistant", "content": result})
                        messages.append({"role": "user", "content": f"Gagal. Coba approach berbeda: {alt}"})
                        console.print(Text(f"  ↻ Retry {attempt}/{subtask.max_attempts}: {alt[:80]}", style="dim"))
                    continue

            except Exception as e:
                result = f"Error: {e}"
                if attempt < subtask.max_attempts:
                    console.print(Text(f"  ↻ Error, retry {attempt}/{subtask.max_attempts}: {str(e)[:60]}", style="dim"))
                    continue

        subtask.status = "failed"
        self._render_progress()
        return subtask.result or "Failed after max attempts.", False

    def _run_tool_loop(
        self, messages: list[dict], provider: str, model: str, attempt: int
    ) -> tuple[str, bool]:
        """Run the ReAct tool-calling loop for a subtask.
        Returns (final_text, success)."""
        for round_idx in range(self.max_subtask_rounds):
            self.total_rounds += 1
            if is_aborted():
                return "Aborted.", False

            try:
                resp = self.invoke_fn(provider, model, messages, use_tools=True)
                msg = resp.choices[0].message if hasattr(resp, "choices") else resp
                msg_dict = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else {"role": "assistant", "content": getattr(msg, "content", "")}
                messages.append(msg_dict)

                content = getattr(msg, "content", None) or ""
                tool_calls = getattr(msg, "tool_calls", None)

                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
                        name = fn.name if hasattr(fn, "name") else fn.get("name", "")
                        args_raw = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", "{}")
                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                        # Execute tool
                        _start = time.time()
                        output = self.execute_tool_fn(name, args)
                        _elapsed = time.time() - _start

                        # Render
                        if self.render_fn:
                            self.render_fn(name, args, output, elapsed=_elapsed)

                        tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                        messages.append({"role": "tool", "tool_call_id": tc_id, "content": output})
                    continue
                else:
                    # No tool calls = LLM thinks it's done
                    return content, True

            except Exception as e:
                return f"Error in tool loop: {e}", False

        return "Max rounds reached for subtask.", False

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _verify_subtask(self, subtask: SubTask, provider: str, model: str) -> bool:
        """Quick LLM check: is this subtask actually done?"""
        prompt = VERIFICATION_PROMPT.format(
            subtask=subtask.description[:200],
            result=subtask.result[:500],
        )
        try:
            resp = self.invoke_fn(provider, model, [
                {"role": "system", "content": "Answer in JSON only."},
                {"role": "user", "content": prompt},
            ], use_tools=False)
            content = ""
            if hasattr(resp, "choices"):
                content = resp.choices[0].message.content or ""
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            result = json.loads(content)
            return result.get("done", True)
        except Exception:
            return True  # Assume done if verification fails

    def _analyze_failure(self, subtask: SubTask, error: str, attempt: int, provider: str, model: str) -> str:
        """Ask fast LLM for an alternative approach."""
        prompt = FAILURE_ANALYSIS_PROMPT.format(
            command=subtask.description[:200],
            error=error[:300],
            attempt=attempt,
        )
        try:
            resp = self.invoke_fn(provider, model, [
                {"role": "user", "content": prompt},
            ], use_tools=False)
            if hasattr(resp, "choices"):
                return (resp.choices[0].message.content or "").strip()[:200]
        except Exception:
            pass
        return "Coba approach yang berbeda dari sebelumnya."

    # ------------------------------------------------------------------
    # Final Completion Check
    # ------------------------------------------------------------------

    def check_overall_completion(self, user_request: str, provider: str, model: str) -> dict:
        """Check if ALL subtasks are done and user request is satisfied."""
        completed = "\n".join(
            f"- [{t.status}] {t.description}: {t.result[:100]}" for t in self.subtasks
        )
        prompt = COMPLETION_PROMPT.format(
            request=user_request[:300],
            completed=completed[:800],
        )
        try:
            resp = self.invoke_fn(provider, model, [
                {"role": "system", "content": "Answer in JSON only."},
                {"role": "user", "content": prompt},
            ], use_tools=False)
            content = ""
            if hasattr(resp, "choices"):
                content = resp.choices[0].message.content or ""
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            return json.loads(content)
        except Exception:
            done_count = sum(1 for t in self.subtasks if t.status == "done")
            return {"done": done_count == len(self.subtasks), "remaining": [], "summary": ""}

    # ------------------------------------------------------------------
    # Main Run Loop
    # ------------------------------------------------------------------

    def run(self, user_request: str, provider: str, model: str, history: list[dict]) -> AgentResult:
        """Main autonomous execution loop."""
        reset_abort()

        # Step 1: Plan
        console.print(Text("  🧠 Planning…", style="bold cyan"))
        self.plan(user_request, provider, model)

        # Step 2: Execute each subtask
        for subtask in self.subtasks:
            if is_aborted():
                break
            result, success = self.execute_subtask(subtask, provider, model, history)
            if success:
                history.append({"role": "assistant", "content": f"[{subtask.description}] ✓ {result[:200]}"})

        # Step 3: Final verification
        console.print(Text("  🔍 Verifying…", style="bold cyan"))
        check = self.check_overall_completion(user_request, provider, model)

        done_count = sum(1 for t in self.subtasks if t.status == "done")
        total = len(self.subtasks)

        # Step 4: If not done and not aborted, do one more pass on remaining
        if not check.get("done", True) and not is_aborted():
            remaining = check.get("remaining", [])
            if remaining:
                console.print(Text(f"  ↻ {len(remaining)} items remaining, continuing…", style="cyan"))
                extra_request = "Masih ada yang belum selesai:\n" + "\n".join(f"- {r}" for r in remaining[:5])
                extra_tasks = [SubTask(id=100 + i, description=r) for i, r in enumerate(remaining[:5])]
                self.subtasks.extend(extra_tasks)
                for subtask in extra_tasks:
                    if is_aborted():
                        break
                    result, success = self.execute_subtask(subtask, provider, model, history)
                    if success:
                        done_count += 1

        # Step 5: Report
        summary = self._generate_summary(user_request, check)
        return AgentResult(
            success=check.get("done", done_count == total),
            summary=summary,
            subtasks_completed=done_count,
            subtasks_total=len(self.subtasks),
            total_rounds=self.total_rounds,
        )

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _render_plan(self):
        """Show the task plan."""
        console.print()
        for t in self.subtasks:
            console.print(Text(f"  ○ [{t.id}] {t.description[:60]}", style="dim"))
        console.print()

    def _render_progress(self):
        """Show current progress."""
        for t in self.subtasks:
            icon = {"pending": "○", "in_progress": "●", "done": "✓", "failed": "✗", "skipped": "⊘"}.get(t.status, "○")
            style = {"pending": "dim", "in_progress": "bold cyan", "done": "green", "failed": "red", "skipped": "dim"}.get(t.status, "dim")
            console.print(Text(f"  {icon} [{t.id}] {t.description[:55]}", style=style))

    def _generate_summary(self, user_request: str, check: dict) -> str:
        """Generate final summary."""
        done = sum(1 for t in self.subtasks if t.status == "done")
        failed = sum(1 for t in self.subtasks if t.status == "failed")
        total = len(self.subtasks)

        lines = [f"Selesai: {done}/{total} subtask"]
        if failed:
            lines.append(f"Gagal: {failed} subtask")
        if check.get("summary"):
            lines.append(check["summary"])
        if check.get("remaining"):
            lines.append("Sisa: " + ", ".join(check["remaining"][:3]))

        return " · ".join(lines)
