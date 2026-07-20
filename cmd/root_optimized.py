#!/usr/bin/env python3
"""Terminal-first Opsora client with Model Studio integration, context compression, and Codex-like UX."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import boto3
from botocore.config import Config
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.live import Live


# ============================================================================
# Configuration & Constants
# ============================================================================

WORKSPACE_ROOT = Path("/home/ubuntu")
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

console = Console()
OPSORA_ENV = WORKSPACE_ROOT / ".opsora_env"

# Model Studio (Singapore Workspace)
MODEL_STUDIO_URL = "https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
MODEL_STUDIO_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

# Local URLs
LOCAL_URL = os.environ.get("OPSORA_OLLAMA_URL", "http://127.0.0.1:11434/v1")
LOCAL_TAGS_URL = LOCAL_URL.removesuffix("/v1") + "/api/tags"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"

# Limits & Budgets
MAX_TOOL_ROUNDS = 4
MAX_TOOL_OUTPUT = 12_000
MAX_CONTEXT_TOKENS = 8000  # Soft limit for context compression
DAILY_TOKEN_BUDGET = 100000
TOKEN_BUDGET_FILE = WORKSPACE_ROOT / ".opsora" / "token_budget.json"

# Security
SECRET_ENV_NAMES = (
    "NVIDIA_API_KEY", "DASHSCOPE_API_KEY", "ALIBABA_API_KEY",
    "ALIYUN_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN", "OPENAI_API_KEY",
)
SENSITIVE_PATH_PARTS = {".aws", ".ssh", ".gnupg", ".config/gcloud"}
SENSITIVE_FILE_NAMES = {".env", ".opsora_env", "credentials", "id_rsa"}
SENSITIVE_FILE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


# ============================================================================
# Model Tiers (like Codex)
# ============================================================================

MODEL_TIERS = {
    "fast": {"model": "qwen-flash", "desc": "Simple Q&A, fastest, cheapest"},
    "coder": {"model": "qwen3-coder-plus", "desc": "Coding tasks"},
    "plus": {"model": "qwen3.7-plus", "desc": "General purpose, balanced"},
    "max": {"model": "qwen3.7-max", "desc": "Complex reasoning, most expensive"},
    "vision": {"model": "qwen3-vl-plus", "desc": "Image analysis"},
}

DEFAULT_TIER = os.environ.get("OPSORA_TIER", "plus")


# ============================================================================
# Token Budget Tracking
# ============================================================================

def track_usage(model: str, tokens: int) -> None:
    """Track daily token usage"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not TOKEN_BUDGET_FILE.exists():
        TOKEN_BUDGET_FILE.write_text(json.dumps({
            "date": today,
            "total_tokens": 0,
            "by_model": {}
        }))
    
    data = json.loads(TOKEN_BUDGET_FILE.read_text())
    
    if data["date"] != today:
        data = {"date": today, "total_tokens": 0, "by_model": {}}
    
    data["total_tokens"] += tokens
    data["by_model"][model] = data["by_model"].get(model, 0) + tokens
    
    TOKEN_BUDGET_FILE.write_text(json.dumps(data, indent=2))


def check_token_budget() -> tuple[bool, int, int]:
    """Check if within daily budget. Returns (ok, used, limit)"""
    if not TOKEN_BUDGET_FILE.exists():
        return True, 0, DAILY_TOKEN_BUDGET
    
    data = json.loads(TOKEN_BUDGET_FILE.read_text())
    used = data.get("total_tokens", 0)
    
    return used < DAILY_TOKEN_BUDGET, used, DAILY_TOKEN_BUDGET


def show_usage_stats() -> None:
    """Display token usage statistics"""
    if not TOKEN_BUDGET_FILE.exists():
        console.print("[dim]No usage data yet.[/dim]")
        return
    
    data = json.loads(TOKEN_BUDGET_FILE.read_text())
    total = data.get("total_tokens", 0)
    pct = (total / DAILY_TOKEN_BUDGET) * 100
    
    table = Table(title=f"Token Usage - {data['date']}", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    table.add_row("Total Tokens", f"{total:,}")
    table.add_row("Budget", f"{DAILY_TOKEN_BUDGET:,}")
    table.add_row("Used", f"{pct:.1f}%")
    
    console.print(table)
    
    if data.get("by_model"):
        console.print("\n[bold]By Model:[/bold]")
        for model, tokens in sorted(data["by_model"].items()):
            model_pct = (tokens / total * 100) if total > 0 else 0
            console.print(f"  {model}: {tokens:,} ({model_pct:.1f}%)")


# ============================================================================
# Context Compression
# ============================================================================

def compress_context(history: list[dict[str, Any]], max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict[str, Any]]:
    """Compress conversation context to stay within token budget"""
    # Estimate tokens (rough: 1 token ≈ 4 chars for English)
    total_chars = sum(len(msg.get("content", "")) for msg in history)
    estimated_tokens = total_chars // 4
    
    if estimated_tokens <= max_tokens:
        return history
    
    # Keep system prompt and last 3 exchanges
    system_msg = history[0] if history and history[0]["role"] == "system" else None
    recent = history[-6:] if len(history) > 6 else history
    
    # Create summary placeholder
    if len(history) > 6:
        summary = {
            "role": "system",
            "content": f"[Previous conversation compressed - {len(history)-6} messages summarized]"
        }
        return [system_msg, summary] + recent if system_msg else [summary] + recent
    
    return history


# ============================================================================
# Environment Loading
# ============================================================================

def load_export_file(path: Path) -> None:
    """Load simple `export NAME=value` lines without executing shell code."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum() or key[:1].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def csv_env(name: str, fallback: str) -> list[str]:
    value = os.environ.get(name, fallback)
    return [item.strip() for item in value.split(",") if item.strip()]


load_export_file(OPSORA_ENV)


# ============================================================================
# Client Initialization
# ============================================================================

# Model Studio client (primary)
model_studio_client = OpenAI(
    api_key=MODEL_STUDIO_KEY,
    base_url=MODEL_STUDIO_URL,
    timeout=35
) if MODEL_STUDIO_KEY else None

# Legacy clients
nvidia_client = OpenAI(
    api_key=os.environ.get("NVIDIA_API_KEY"),
    base_url=NVIDIA_URL,
    timeout=35
) if os.environ.get("NVIDIA_API_KEY") else None

local_client = OpenAI(
    api_key="ollama",
    base_url=LOCAL_URL,
    timeout=45
)


# ============================================================================
# Model Selection
# ============================================================================

@dataclass
class Selection:
    provider: str
    model: str
    tier: str = "plus"


def get_model_studio_models() -> list[str]:
    """Get available models from Model Studio"""
    try:
        if model_studio_client:
            models = model_studio_client.models.list()
            return sorted([m.id for m in models.data])
    except Exception:
        pass
    return list(MODEL_TIERS.values())


def available_local_models() -> list[str]:
    try:
        with urlopen(LOCAL_TAGS_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [str(item.get("name", "")).strip() for item in payload.get("models", [])]
        return [model for model in models if model]
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return []


def auto_select_model(prompt: str) -> Selection:
    """Automatically select model based on prompt content"""
    prompt_lower = prompt.lower()
    
    # Fast tier indicators
    if any(kw in prompt_lower for kw in ["what is", "who is", "when", "where", "brief", "quick", "simple"]):
        return Selection("model_studio", MODEL_TIERS["fast"]["model"], "fast")
    
    # Coder tier indicators
    if any(kw in prompt_lower for kw in ["code", "function", "class", "def", "bug", "fix", "refactor", "implement", "script", "debug"]):
        return Selection("model_studio", MODEL_TIERS["coder"]["model"], "coder")
    
    # Vision tier indicators
    if any(kw in prompt_lower for kw in ["image", "picture", "photo", "screenshot", "visual", "diagram"]):
        return Selection("model_studio", MODEL_TIERS["vision"]["model"], "vision")
    
    # Max tier indicators
    if any(kw in prompt_lower for kw in ["analyze", "architecture", "design", "strategy", "complex", "deep"]):
        return Selection("model_studio", MODEL_TIERS["max"]["model"], "max")
    
    # Default to plus tier
    return Selection("model_studio", MODEL_TIERS[DEFAULT_TIER]["model"], DEFAULT_TIER)


# Global selection
selection = auto_select_model("")  # Will be updated on first prompt


# ============================================================================
# Tools Definition
# ============================================================================

SAFE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Save a concise non-secret fact in persistent memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source": {"type": "string"}
                },
                "required": ["text"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search persistent memory for relevant context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["query"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graphify_query",
            "description": "Query the local Graphify knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "depth": {"type": "integer"}
                },
                "required": ["query"]
            },
        },
    },
]


# ============================================================================
# Tool Execution
# ============================================================================

def truncate(value: str, maximum: int = MAX_TOOL_OUTPUT) -> str:
    if len(value) <= maximum:
        return value
    return value[:maximum] + f"\n… truncated ({len(value) - maximum} chars omitted)"


def redact_secrets(value: str) -> str:
    result = value
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and len(secret) >= 8:
            result = result.replace(secret, "[REDACTED]")
    return result


def execute_tool(name: str, args: dict[str, Any]) -> str:
    try:
        if name == "memory_add":
            from opsora_memory import add_memory
            return add_memory(args.get("text"), source=args.get("source", "cli"))
        elif name == "memory_search":
            from opsora_memory import search_memory
            return json.dumps(search_memory(args.get("query"), args.get("limit", 5)), ensure_ascii=False)
        elif name == "graphify_query":
            from opsora_tools import graphify_query
            return graphify_query(args.get("query"), depth=args.get("depth", 2))
        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Tool error: {exc}"


# ============================================================================
# API Invocation
# ============================================================================

def create_completion(client: OpenAI, model: str, messages: list[dict[str, Any]], use_tools: bool) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2
    }
    
    if use_tools:
        kwargs.update({
            "tools": SAFE_TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": False
        })
    
    try:
        return client.chat.completions.create(**kwargs).choices[0].message
    except Exception:
        # Fallback without tools if provider rejects tool schema
        if use_tools:
            fallback = {k: v for k, v in kwargs.items() if k not in {"tools", "tool_choice", "parallel_tool_calls"}}
            return client.chat.completions.create(**fallback).choices[0].message
        raise


def invoke(provider: str, model: str, messages: list[dict[str, Any]], use_tools: bool = True) -> Any:
    if provider == "model_studio" and model_studio_client:
        return create_completion(model_studio_client, model, messages, use_tools)
    elif provider == "nvidia" and nvidia_client:
        return create_completion(nvidia_client, model, messages, use_tools)
    elif provider == "local":
        return create_completion(local_client, model, messages, use_tools)
    else:
        raise RuntimeError(f"Provider {provider} is not configured.")


def call_with_fallback(messages: list[dict[str, Any]], use_tools: bool = True) -> tuple[Any, Selection]:
    """Try primary model, fallback to others if needed"""
    candidates = [
        selection,
        Selection("model_studio", MODEL_TIERS["plus"]["model"], "plus"),
        Selection("model_studio", MODEL_TIERS["fast"]["model"], "fast"),
    ]
    
    # Remove duplicates
    seen = set()
    unique_candidates = []
    for c in candidates:
        key = (c.provider, c.model)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(c)
    
    errors = []
    for candidate in unique_candidates:
        try:
            return invoke(candidate.provider, candidate.model, messages, use_tools), candidate
        except Exception as exc:
            errors.append(f"{candidate.provider}:{candidate.model} ({str(exc)[:100]})")
    
    raise RuntimeError("All model attempts failed: " + "; ".join(errors))


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """You are Opsora, a terminal-based AI coding assistant powered by Model Studio.
You help users write, edit, and understand code, run shell commands, and work with cloud resources.
Be concise but complete. Use Indonesian if the user writes in Indonesian.

# Capabilities
- Code writing, review, and debugging
- Shell command execution (with approval)
- AWS cloud operations (read-only by default)
- Memory persistence for context
- Graphify knowledge graph queries

# Response Guidelines
- Be direct and precise
- Use code blocks for code
- Keep explanations concise unless asked for detail
- Prefer Indonesian for Indonesian input"""


# ============================================================================
# Interactive Loop
# ============================================================================

def run_turn(history: list[dict[str, Any]]) -> None:
    global selection
    
    # Compress context if needed
    history = compress_context(history)
    
    for _ in range(MAX_TOOL_ROUNDS):
        with console.status(f"[cyan]⠋ {selection.provider}:{selection.model} is thinking…[/cyan]", spinner="dots"):
            message, used = call_with_fallback(
                [{"role": "system", "content": SYSTEM_PROMPT}, *history],
                use_tools=True
            )
        
        selection = used
        record = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else message
        history.append(record)
        
        content = record.get("content") or ""
        if content:
            console.print()
            console.print(Markdown(content))
            console.print()
        
        # Track tokens
        total_tokens = sum(len(msg.get("content", "")) // 4 for msg in history)
        track_usage(selection.model, total_tokens)
        
        # Check for tool calls
        tool_calls = record.get("tool_calls") or getattr(message, "tool_calls", None)
        if not tool_calls:
            return
        
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else tool_call.function
            name = function.get("name") if isinstance(function, dict) else function.name
            raw_args = function.get("arguments", "{}") if isinstance(function, dict) else function.arguments
            
            try:
                args = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                args = {}
            
            with console.status(f"[yellow]⠋ Executing tool: {name}…[/yellow]", spinner="dots"):
                output = execute_tool(name, args)
            
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            if len(args_str) > 60:
                args_str = args_str[:57] + "..."
            console.print(f"  [dim yellow]⚙ {name}({args_str})[/]")
            
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else tool_call.id
            history.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": output
            })
    
    console.print("[yellow]Tool-call limit reached; start a new request if needed.[/yellow]")


# ============================================================================
# UI Components
# ============================================================================

def print_welcome() -> None:
    console.print()
    title = Text("Opsora", style="bold cyan")
    title.append("   powered by Model Studio", style="dim white")
    console.print(title)
    
    ok, used, limit = check_token_budget()
    budget_color = "green" if ok else "red"
    budget_text = f"{used:,} / {limit:,}"
    
    console.print(Panel(
        f"[bold cyan]{selection.provider}:{selection.model}[/] ([{selection.tier}] tier)\n"
        f"Workspace: ws-u05t2ivr4fghrt6v (Singapore)\n"
        f"Budget: [{budget_color}]{budget_text}[/] ({(used/limit*100):.1f}% used)\n"
        "Type [bold]/help[/bold] for commands. [dim]Ctrl-C exits.[/dim]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 2),
    ))


def show_models() -> None:
    table = Table(title="Model Tiers", box=box.ROUNDED, border_style="cyan")
    table.add_column("Tier", style="cyan")
    table.add_column("Model")
    table.add_column("Use Case")
    table.add_column("Cost")
    
    for tier_name, tier_info in MODEL_TIERS.items():
        current = "◀" if selection.tier == tier_name else " "
        table.add_row(
            f"{current} {tier_name}",
            tier_info["model"],
            tier_info["desc"],
            "💰" if tier_name == "fast" else "💰💰" if tier_name in ["coder", "plus"] else "💰💰💰"
        )
    
    console.print(table)
    console.print("\n[dim]Use /model <tier> to switch. Auto-selection based on prompt.[/dim]")


def show_help() -> None:
    console.print(Panel(
        "[bold]/help[/bold]        Show this help\n"
        "[bold]/status[/bold]      Provider, budget, and tools status\n"
        "[bold]/models[/bold]      Show available model tiers\n"
        "[bold]/model <tier>[/bold]  Switch model tier (fast|coder|plus|max|vision)\n"
        "[bold]/usage[/bold]       Show token usage stats\n"
        "[bold]/new[/bold]         Clear conversation\n"
        "[bold]/clear[/bold]       Redraw screen\n"
        "[bold]/exit[/bold]        Leave Opsora",
        title="Opsora Commands",
        border_style="cyan",
        box=box.ROUNDED,
    ))


def handle_command(value: str, history: list[dict[str, Any]]) -> bool:
    """Handle slash commands. Returns True if should continue, False if exit."""
    global selection
    
    parts = shlex.split(value)
    command = parts[0].lower()
    
    if command in ("/exit", "/quit"):
        return False
    elif command == "/help":
        show_help()
    elif command == "/status":
        ok, used, limit = check_token_budget()
        status_color = "green" if ok else "red"
        console.print(f"[bold]Provider:[/bold] {selection.provider}:{selection.model}")
        console.print(f"[bold]Tier:[/bold] {selection.tier}")
        console.print(f"[bold]Budget:[/bold] [{status_color}]{used:,} / {limit:,} ({(used/limit*100):.1f}%)[/]")
        console.print(f"[bold]Tools:[/bold] {len(SAFE_TOOLS)} safe tools enabled")
    elif command == "/models":
        show_models()
    elif command == "/model" and len(parts) > 1:
        tier = parts[1].lower()
        if tier in MODEL_TIERS:
            selection = Selection("model_studio", MODEL_TIERS[tier]["model"], tier)
            console.print(f"[green]✓[/green] Switched to [bold]{tier}[/bold] tier: {selection.model}")
        else:
            # Try as direct model name
            selection = Selection("model_studio", tier, "custom")
            console.print(f"[green]✓[/green] Switched to model: {tier}")
    elif command == "/usage":
        show_usage_stats()
    elif command == "/new":
        history.clear()
        console.print("[green]✓[/green] Conversation cleared")
    elif command == "/clear":
        console.clear()
        print_welcome()
    else:
        console.print(f"[red]Unknown command:[/red] {command}. Type /help")
    
    return True


# ============================================================================
# Main Entry Point
# ============================================================================

def main() -> None:
    global selection
    
    # Handle direct prompt mode
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        selection = auto_select_model(prompt)
        
        with console.status(f"[cyan]⠋ {selection.model} is thinking…[/cyan]", spinner="dots"):
            try:
                message, used = call_with_fallback(
                    [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                    use_tools=True
                )
                content = message.content or ""
                if content:
                    console.print(Markdown(content))
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        return
    
    # Interactive mode
    console.clear()
    print_welcome()
    
    history: list[dict[str, Any]] = []
    session = PromptSession()
    
    while True:
        try:
            prompt = session.prompt(f"opsora [{selection.tier}] › ")
            
            if not prompt.strip():
                continue
            
            # Handle commands
            if prompt.startswith("/"):
                if not handle_command(prompt, history):
                    break
                continue
            
            # Auto-select model based on prompt
            selection = auto_select_model(prompt)
            
            # Check budget
            ok, used, limit = check_token_budget()
            if not ok:
                console.print(f"[red]⚠ Daily token budget exceeded! ({used:,} / {limit:,})[/red]")
                console.print("[dim]Use /model fast to switch to cheaper model, or wait until tomorrow.[/dim]")
                continue
            
            # Add to history and run turn
            history.append({"role": "user", "content": prompt})
            run_turn(history)
            
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
    
    console.print("\n[dim]Meninggalkan Opsora CLI...[/dim]")


if __name__ == "__main__":
    main()
