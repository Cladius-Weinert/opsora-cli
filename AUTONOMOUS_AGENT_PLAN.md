# Opsora Autonomous Agent System — Comprehensive Plan

## Goal
Build a fully autonomous problem-solving system that:
- Keeps working until the task is DONE (not limited by rounds)
- Self-corrects when things fail
- Decomposes big tasks into steps
- Verifies completion before stopping
- Can loop/iterate on complex problems

## Current Weaknesses (from code analysis)

| Problem | Location | Impact |
|---------|----------|--------|
| Max 20 rounds then stops | `run_agent_turn()` | Complex tasks incomplete |
| No task verification | Agent loop | Doesn't know when done |
| Error recovery = pip install only | `_try_error_recovery()` | Most failures unhandled |
| problem_solver.py is static stub | `solve_problem()` | Never actually solves anything |
| No retry with different strategy | Agent loop | Gives up on first failure |
| No "stuck" detection | Agent loop | Repeats same failing approach |
| Auto-continue only checks todos | Agent loop | Misses incomplete tasks |
| No progress checkpointing | Agent loop | Loses progress on context overflow |
| Context compression = truncate | `compress_context()` | Loses important context |

## Architecture: Autonomous Agent Loop v2

```
User Request
    │
    ▼
┌─────────────┐
│   ANALYZE   │ ← What does user want? Complex or simple?
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    PLAN     │ ← Break into subtasks (via LLM)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│      EXECUTION LOOP         │
│  ┌─────────┐               │
│  │  ACT    │ ← Execute current subtask  │
│  └────┬────┘               │
│       │                     │
│       ▼                     │
│  ┌─────────┐               │
│  │ VERIFY  │ ← Did it work?           │
│  └────┬────┘               │
│       │                     │
│   ┌───┴───┐                │
│   │       │                 │
│  YES      NO               │
│   │       │                 │
│   ▼       ▼                 │
│  NEXT   RETRY (max 3x)     │
│  TASK   different strategy  │
│   │       │                 │
│   │   ┌───┴───┐            │
│   │   │       │             │
│   │  FIXED  STUCK           │
│   │   │       │             │
│   │  NEXT   ESCALATE        │
│   │  TASK   (ask user)      │
│   │                         │
│   └──────── until ALL DONE ─┘
│
└──────────┬──────────────────┘
           │
           ▼
┌─────────────┐
│   REPORT    │ ← Summary of what was done
└─────────────┘
```

## Implementation Plan

### Phase 1: New Autonomous Agent Core (`opsora_agent.py`)

Create a new module that replaces the static problem_solver with a REAL autonomous system.

```python
class AutonomousAgent:
    """Fully autonomous agent that loops until task is done."""
    
    def __init__(self, invoke_fn, tools, system_prompt, max_subtask_rounds=10):
        self.invoke_fn = invoke_fn
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_subtask_rounds = max_subtask_rounds
        self.task_plan = []
        self.completed = []
        self.failed = []
        self.history = []
    
    def analyze_and_plan(self, user_request: str) -> list[dict]:
        """Ask LLM to decompose request into subtasks."""
        # Returns list of: {id, description, status, result, attempts}
    
    def execute_subtask(self, subtask: dict, selection) -> tuple[str, bool]:
        """Execute one subtask with retry logic.
        Returns (result, success).
        Retries up to 3 times with different strategies."""
    
    def verify_completion(self, subtask: dict, result: str) -> bool:
        """Ask LLM: is this subtask actually done?"""
    
    def handle_failure(self, subtask: dict, error: str, attempt: int) -> str:
        """Analyze failure and suggest alternative approach."""
    
    def compress_between_subtasks(self):
        """Compress history between subtasks to save context."""
    
    def run(self, user_request: str, selection, status_bar) -> str:
        """Main loop: plan → execute → verify → next → report."""
```

### Phase 2: Upgraded SYSTEM_PROMPT

The current system prompt is good but needs autonomous-specific instructions:

```
## AUTONOMOUS MODE RULES:
- NEVER stop until the user's request is fully satisfied
- After completing a step, check: is there more to do?
- If a tool fails, try a DIFFERENT approach (not the same one)
- If stuck after 3 attempts, explain what went wrong and ask user
- Use todo_write to track progress on multi-step tasks
- After each file edit, verify by reading the file back
- After running tests, fix any failures before moving on
```

### Phase 3: Smart Error Recovery v2

Replace the basic pip-install-only recovery with multi-strategy:

```python
def _smart_error_recovery(name, args, output, history, selection):
    """Multi-strategy error recovery."""
    
    # Strategy 1: Missing package → auto-install (existing)
    if "modulenotfounderror" in output.lower():
        ...
    
    # Strategy 2: Permission denied → try with different path/approach
    if "permission denied" in output.lower():
        return suggest_alternative(args, "permission")
    
    # Strategy 3: File not found → search for similar files
    if "no such file" in output.lower():
        return find_similar_file(args)
    
    # Strategy 4: Command not found → suggest alternative
    if "command not found" in output.lower():
        return find_alternative_command(args)
    
    # Strategy 5: Syntax error → show the error and suggest fix
    if "syntaxerror" in output.lower():
        return analyze_syntax_error(output)
    
    # Strategy 6: Connection error → retry with backoff
    if "connection" in output.lower() or "timeout" in output.lower():
        return retry_with_backoff(args)
    
    # Strategy 7: Generic failure → ask LLM for alternative approach
    if any(p in output.lower() for p in ["error", "failed", "exception"]):
        return ask_llm_for_alternative(name, args, output, history, selection)
    
    return output
```

### Phase 4: Task Verification System

```python
def verify_task_completion(user_request: str, history: list, tools_output: list) -> dict:
    """Ask fast LLM: is the user's request satisfied?
    Returns: {done: bool, reason: str, remaining: [str]}"""
    
    prompt = f"""User asked: {user_request[:300]}

Actions taken: {summarize_actions(history)[:500]}

Is the user's request fully satisfied? 
Answer in JSON: {{"done": true/false, "reason": "...", "remaining": ["..."]}}
"""
```

### Phase 5: New Slash Commands

| Command | Description |
|---------|-------------|
| `/auto <task>` | Run autonomous agent on complex task |
| `/loop <task>` | Keep retrying until success |
| `/status` | Show current task plan + progress |
| `/abort` | Kill current autonomous task |
| `/retry` | Retry last failed action with different approach |

### Phase 6: Integration into opsora_v2.py

- Replace `/solve` command with `/auto` using AutonomousAgent
- Add auto-detection: if user request is complex (>2 steps), auto-use agent
- Wire verification into end of agent turn
- Add progress display during autonomous execution

## File Changes

| File | Change |
|------|--------|
| `opsora_cmd/opsora_agent.py` | NEW — AutonomousAgent class (~250 lines) |
| `opsora_cmd/opsora_v2.py` | Add /auto, /loop, /abort commands; wire verification |
| `opsora_cmd/opsora_v2.py` | Upgrade SYSTEM_PROMPT with autonomous rules |
| `opsora_cmd/opsora_v2.py` | Replace `_try_error_recovery` with `_smart_error_recovery` |
| `opsora_cmd/problem_solver.py` | DELETE — replaced by opsora_agent.py |

## Priority Order

1. **opsora_agent.py** — Core autonomous agent (highest impact)
2. **SYSTEM_PROMPT upgrade** — Better instructions for autonomy
3. **Smart error recovery** — Multi-strategy failure handling
4. **Task verification** — Know when done
5. **New slash commands** — /auto, /loop, /abort
6. **Integration** — Wire everything into opsora_v2.py

## Key Design Decisions

1. **Use fast model (qwen-turbo) for planning/verification** — save cost
2. **Use power model (qwen-plus) for execution** — best quality
3. **Max 3 retries per subtask** — prevent infinite loops
4. **Compress context between subtasks** — handle long sessions
5. **Show progress with todo_write** — user sees what's happening
6. **Kill switch (/abort)** — user can stop anytime
