#!/usr/bin/env python3
"""
Opsora CLI v3 — Codex/Claude Code-style Agentic Terminal Assistant

Integrates: TUI engine, agent loop with self-reflection, sub-agents,
MCP tools, session persistence, approval modes, and multi-provider routing.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen, Request

# --- OpenAI client (with fallback to lightweight urllib implementation) ---
try:
    from openai import OpenAI
except (ImportError, Exception):
    from openai_lite import OpenAI

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner

# Opsora modules
from opsora_tui import (
    ApprovalMode,
    StatusBar,
    codex_prompt,
    console,
    cycle_approval_mode,
    get_approval_mode,
    is_verbose,
    needs_approval,
    print_welcome,
    prompt_approval,
    redact_display,
    render_file_edit,
    render_file_tree,
    render_help,
    render_tool_call,
    set_approval_mode,
    set_theme_colors,
    stream_markdown,
    toggle_verbose,
)
from opsora_session import (
    Session,
    delete_session,
    list_sessions,
    load_session,
    save_session,
    search_sessions,
)
from opsora_subagent import SubagentOrchestrator
from opsora_mcp_v2 import MCPClient_v2
from problem_solver import solve_problem
# Phase 1: imported at module level (stdlib-only, no network at import time)
# so slash-command handlers are patchable in tests via opsora_v2.<name>.
from opsora_new_tools import web_search, db_query
from opsora_nvidia import (
    analyze_image,
    analyze_screenshot,
    check_command_safety,
    generate_embedding,
    translate_text,
)
# Phase 1 (tasks 16-18): provider resilience — structured logging with
# correlation ids, externalized timeouts, retry with backoff, circuit breaker.
from opsora_resilience import (
    CircuitOpenError,
    all_breaker_status,
    get_breaker,
    get_config as get_resilience_config,
    get_logger as get_structured_logger,
    is_transient_error,
    new_turn_correlation_id,
    reset_breakers,
    retry_with_backoff,
)

# v3.1 upgrades (lazy imports where possible for startup speed)
# MODEL_COSTS/_DEFAULT_COST: single source of truth for pricing lives in
# opsora_cost (config/model_costs.json with built-in fallback) — Phase 1.
from opsora_cost import CostTracker, extract_usage, MODEL_COSTS, _DEFAULT_COST
from opsora_routing import IntentRouter as _IntentRouter, route as _smart_route
from opsora_themes import load_theme_preference, get_theme, list_themes, save_theme_preference, apply_theme
from opsora_plugins import PluginManager
from opsora_agent import AutonomousAgent, abort_agent, reset_abort, is_aborted

# ============================================================================
# Workspace Configuration
# ============================================================================

WORKSPACE_ROOT = Path(os.environ.get("OPSORA_WORKSPACE_ROOT", "/root"))
OPSORA_DIR = WORKSPACE_ROOT / ".opsora"
OPSORA_DIR.mkdir(exist_ok=True)

# Configuration defaults
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2
# Phase 1 (task 17): kept as the documented fallback; provider getters read
# the live value from config/resilience.json (get_resilience_config()).
DEFAULT_TIMEOUT = 40
MAX_CONTEXT_TOKENS = 131072


def load_env_file(path: Path) -> None:
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
        key, value = key.strip(), value.strip()
        if not key.replace("_", "").isalnum() or key[:1].isdigit():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(WORKSPACE_ROOT / ".opsora_env")
load_env_file(OPSORA_DIR / "qwen-code" / "secrets.env")

# ============================================================================
# Provider Configuration (Lazy Initialization)
# ============================================================================

# Provider clients are lazily initialized on first use
_nvidia_client: Optional[OpenAI] = None
_alibaba_client: Optional[OpenAI] = None
_model_studio_client: Optional[OpenAI] = None
_openai_client: Optional[OpenAI] = None
_tokenhub_client: Optional[OpenAI] = None
_opsora_api_client: Optional[OpenAI] = None


def get_nvidia_client() -> Optional[OpenAI]:
    global _nvidia_client
    if _nvidia_client is None:
        key = os.environ.get("NVIDIA_API_KEY")
        if key:
            _nvidia_client = OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1", timeout=get_resilience_config().timeout_seconds)
    return _nvidia_client


def get_alibaba_client() -> Optional[OpenAI]:
    global _alibaba_client
    if _alibaba_client is None:
        key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            url = os.environ.get("ALIBABA_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            _alibaba_client = OpenAI(api_key=key, base_url=url, timeout=get_resilience_config().timeout_seconds)
    return _alibaba_client


def get_model_studio_client() -> Optional[OpenAI]:
    global _model_studio_client
    if _model_studio_client is None:
        key = os.environ.get("DASHSCOPE_API_KEY")
        if key:
            _model_studio_client = OpenAI(
                api_key=key,
                base_url="https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
                timeout=get_resilience_config().timeout_seconds
            )
    return _model_studio_client


def get_openai_client() -> Optional[OpenAI]:
    global _openai_client
    if _openai_client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            _openai_client = OpenAI(api_key=key, timeout=get_resilience_config().timeout_seconds)
    return _openai_client


def get_tokenhub_client() -> Optional[OpenAI]:
    global _tokenhub_client
    if _tokenhub_client is None:
        key = os.environ.get("TOKENHUB_API_KEY", "")
        if key:
            _tokenhub_client = OpenAI(
                api_key=key,
                base_url="https://tokenhub.tencentmaas.com/v1",
                timeout=get_resilience_config().timeout_seconds
            )
    return _tokenhub_client


def get_opsora_api_client() -> Optional[OpenAI]:
    global _opsora_api_client
    if _opsora_api_client is None:
        url = os.environ.get("OPSORA_API_URL", "")
        token = os.environ.get("OPSORA_API_TOKEN", "")
        if url and token:
            _opsora_api_client = OpenAI(
                api_key=token,
                base_url=f"{url}/v1",
                timeout=get_resilience_config().opsora_api_timeout_seconds
            )
    return _opsora_api_client


def bedrock_available() -> bool:
    try:
        return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "default")).get_credentials() is not None
    except Exception:
        return False


def get_provider_order() -> list[str]:
    order = os.environ.get("OPSORA_PROVIDER_ORDER", "alibaba,nvidia,bedrock")
    return [p.strip() for p in order.split(",") if p.strip()]


# Provider clients (lazy - use getter functions)
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
nvidia_client = None  # Lazy initialization

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
ALIBABA_URL = os.environ.get("ALIBABA_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
alibaba_client = None  # Lazy initialization

MODEL_STUDIO_KEY = DASHSCOPE_API_KEY
MODEL_STUDIO_URL = "https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
model_studio_client = None  # Lazy initialization

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = None  # Lazy initialization

import boto3
from botocore.config import Config

AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

TOKENHUB_API_KEY = os.environ.get("TOKENHUB_API_KEY", "")
TOKENHUB_URL = "https://tokenhub.tencentmaas.com/v1"
tokenhub_client = None  # Lazy initialization

OPSORA_API_URL = os.environ.get("OPSORA_API_URL", "")
OPSORA_API_TOKEN = os.environ.get("OPSORA_API_TOKEN", "")
opsora_api_client = None  # Lazy initialization


PROVIDER_MODELS = {
    # Verified working models (2026-07-31) — 18 total across 2 providers
    "alibaba": "qwen3-coder-flash,qwen-plus,qwen-max,qwen3.7-flash,qwen3.7-plus,qwen3.7-max",
    "nvidia": (
        "nvidia/nemotron-3-ultra-550b-a55b,"           # 550B MoE monster (1.7s)
        "mistralai/mistral-medium-3.5-128b,"            # 128B Mistral (1.2s)
        "nvidia/nemotron-3-super-120b-a12b,"            # 120B MoE (1.1s)
        "meta/llama-3.1-70b-instruct,"                  # 70B reliable (1.1s)
        "nvidia/llama-3.3-nemotron-super-49b-v1.5,"    # 49B Nemotron (2.1s)
        "nvidia/nemotron-3-nano-30b-a3b,"               # 30B MoE, 3B active (1.5s)
        "nvidia/nvidia-nemotron-nano-9b-v2,"            # 9B nano (1.5s)
        "mistralai/mistral-nemotron,"                   # Mistral+NVIDIA collab (1.1s)
        "stepfun-ai/step-3.7-flash,"                    # StepFun flash (1.6s)
        "nvidia/nemotron-mini-4b-instruct,"             # 4B ultra-fast (1.1s)
        "meta/llama-3.1-8b-instruct"                    # 8B fastest (0.8s)
    ),
    # Legacy providers
    "model_studio": "qwen-plus,qwen-max",
    "openai": "gpt-4o,gpt-4o-mini",
    "bedrock": "amazon.nova-pro-v1:0,amazon.nova-lite-v1:0",
    "tokenhub": "hy3,kimi-k3,deepseek-v4-flash",
    "opsora_api": "opsora-fast,opsora-brain,opsora-code",
}

# Model routing tiers — auto_select_model uses these
POWER_MODELS = [
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),      # 120B MoE reasoning (1.1s) ✅
    ("nvidia", "meta/llama-3.1-70b-instruct"),            # 70B reliable (1.1s) ⚠️ timeout
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),      # 550B MoE (1.7s) ✅
    ("nvidia", "nvidia/nemotron-3-nano-30b-a3b"),         # 30B MoE (1.5s)
    ("nvidia", "mistralai/mistral-medium-3.5-128b"),      # 128B Mistral (1.2s)
    ("alibaba", "qwen-max"),                              # Best overall (1.2s) ⚠️ key invalid
    ("alibaba", "qwen3.7-max"),                           # Strong reasoning (3.1s) ⚠️ key invalid
]
FAST_MODELS = [
    ("nvidia", "meta/llama-3.1-8b-instruct"),             # 8B fastest (0.8s) ✅
    ("nvidia", "nvidia/nemotron-mini-4b-instruct"),       # 4B ultra-fast (1.1s) ✅
    ("nvidia", "nvidia/nvidia-nemotron-nano-9b-v2"),      # 9B nano (1.5s)
    ("nvidia", "mistralai/mistral-nemotron"),             # Mistral collab (1.1s)
    ("alibaba", "qwen3-coder-flash"),                     # Coding specialist (1.3s) ⚠️ key invalid
    ("alibaba", "qwen-plus"),                             # All-rounder (1.4s) ⚠️ key invalid
    ("alibaba", "qwen3.7-flash"),                         # Flash reasoning (1.9s) ⚠️ key invalid
]
REASONING_MODELS = [
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),      # 120B MoE (1.1s) ✅
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),      # 550B reasoning (1.7s) ✅
    ("nvidia", "nvidia/nemotron-3-nano-30b-a3b"),         # 30B MoE (1.5s)
    ("nvidia", "meta/llama-3.1-70b-instruct"),            # 70B reasoning (1.1s) ⚠️ timeout
    ("alibaba", "qwen3.7-max"),                           # Best reasoning (3.1s) ⚠️ key invalid
    ("alibaba", "qwen3.7-plus"),                          # Balanced (4.1s) ⚠️ key invalid
]
CODING_MODELS = [
    ("nvidia", "deepseek-ai/deepseek-v4-flash"),          # Code specialist (1.2s) ⚠️ 529 overloaded
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),      # 120B MoE good for code (1.1s) ✅
    ("nvidia", "meta/llama-3.1-70b-instruct"),            # 70B strong coding (1.1s) ⚠️ timeout
    ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"), # 49B coding (2.1s)
    ("nvidia", "mistralai/mistral-nemotron"),             # Mistral code (1.1s)
    ("alibaba", "qwen3-coder-flash"),                     # Code specialist (1.3s) ⚠️ key invalid
    ("alibaba", "qwen-plus"),                             # Good coding (1.4s) ⚠️ key invalid
]

# ============================================================================
# Model Selection & Routing
# ============================================================================


@dataclass
class Selection:
    provider: str
    model: str


_provider_health_cache = {}

def is_provider_available(provider: str) -> bool:
    # Check if client can be initialized (has API key)
    key_map = {
        "nvidia": "NVIDIA_API_KEY",
        "alibaba": "DASHSCOPE_API_KEY",
        "model_studio": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "bedrock": "AWS_PROFILE",
        "tokenhub": "TOKENHUB_API_KEY",
        "opsora_api": "OPSORA_API_TOKEN",
    }
    key = key_map.get(provider)
    if key is None:
        return False
    if key == "AWS_PROFILE":
        return bedrock_available()
    if not os.environ.get(key):
        return False

    # Cache health check for 60 seconds to avoid repeated API calls
    import time
    cache_key = f"{provider}_{key}"
    now = time.time()
    if cache_key in _provider_health_cache:
        cached_health, cached_time = _provider_health_cache[cache_key]
        if now - cached_time < 60:
            return cached_health

    # Quick health check for known providers
    healthy = _check_provider_health(provider, os.environ[key])
    _provider_health_cache[cache_key] = (healthy, now)
    return healthy


def _check_provider_health(provider: str, api_key: str) -> bool:
    """Quick health check for provider API key."""
    import requests
    try:
        if provider == "nvidia":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            # Quick models list call
            r = requests.get("https://integrate.api.nvidia.com/v1/models", headers=headers, timeout=5)
            return r.status_code == 200
        elif provider == "alibaba":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            data = {"model": "qwen3-coder-flash", "messages": [{"role": "user", "content": "test"}], "max_tokens": 1}
            r = requests.post("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", headers=headers, json=data, timeout=5)
            return r.status_code == 200
    except Exception:
        pass
    return False

def auto_select_model(prompt: str) -> Selection:
    """v3.2: Tier-based model routing using verified working models.

    Routes based on intent:
    - Code tasks → CODING_MODELS (qwen3-coder-flash first)
    - Analysis/reasoning → REASONING_MODELS (qwen3.7-max first)
    - Quick/simple → FAST_MODELS (qwen3-coder-flash first)
    - Complex/general → POWER_MODELS (qwen-max first)
    """
    from opsora_routing import IntentRouter
    router = IntentRouter()
    intent = router.classify(prompt)

    # Select tier based on intent
    tier_map = {
        "code": CODING_MODELS,
        "analysis": REASONING_MODELS,
        "quick": FAST_MODELS,
        "cloud": POWER_MODELS,
        "creative": POWER_MODELS,
        "general": POWER_MODELS,
    }
    tier = tier_map.get(intent, POWER_MODELS)

    # Try each model in the tier, checking availability
    for provider, model in tier:
        if is_provider_available(provider):
            return Selection(provider, model)

    # Fallback: any available model
    for provider, model in POWER_MODELS + FAST_MODELS:
        if is_provider_available(provider):
            return Selection(provider, model)

    # Last resort
    return Selection("alibaba", "qwen3-coder-flash")


# ============================================================================
# Tools
# ============================================================================

SAFE_TOOLS = [
    # --- EXPLORE (use these FIRST to understand codebase) ---
    {"type": "function", "function": {"name": "glob_search", "description": "Find files by pattern. USE FIRST to discover project structure. Examples: '**/*.py', '**/package.json', 'src/**/*.ts'. Returns file paths.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob pattern like **/*.py or src/**/*.{ts,tsx}"}, "base": {"type": "string", "description": "Base directory to search from"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read file contents. USE AFTER glob_search to understand code. Always read files before editing them. Returns full file content.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string", "description": "Absolute or relative file path"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "grep_search", "description": "Search file contents with regex/text. USE to find specific code, functions, or patterns across files. Returns matching lines with file paths and line numbers.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Search pattern (regex supported)"}, "path": {"type": "string", "description": "Directory to search in"}, "file_type": {"type": "string", "description": "Filter by extension: py, js, ts, etc"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "list_directory", "description": "List files and folders in a directory. USE for quick directory overview.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path to list"}}, "required": ["path"]}}},

    # --- CODE CHANGES (use after understanding the codebase) ---
    {"type": "function", "function": {"name": "write_file", "description": "Create a NEW file or completely overwrite an existing file. USE for new files. For modifying existing files, prefer edit_file instead.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string", "description": "File path to create/overwrite"}, "content": {"type": "string", "description": "Complete file content"}}, "required": ["filepath", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Edit existing file by replacing exact text match. USE for surgical changes to existing files. old_string must match EXACTLY what's in the file (read it first!).", "parameters": {"type": "object", "properties": {"filepath": {"type": "string", "description": "File to edit"}, "old_string": {"type": "string", "description": "Exact text to find (must match precisely)"}, "new_string": {"type": "string", "description": "Text to replace with"}}, "required": ["filepath", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Execute a command (run directly, NO shell: pipes/redirects/&& not supported). USE for: build, install, test, git operations, system commands. Timeout: 120s. Returns stdout+stderr.", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Command to execute, e.g. 'ls -la' or 'python3 -m pytest tests/ -q'"}}, "required": ["command"]}}},

    # --- VERIFY (use AFTER making changes) ---
    {"type": "function", "function": {"name": "run_tests", "description": "Auto-detect and run tests (pytest, jest, cargo test, go test, npm test). USE after code changes to verify correctness. Returns test output.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Project directory"}, "filter": {"type": "string", "description": "Test filter (e.g. test name pattern)"}}, "required": []}}},
    {"type": "function", "function": {"name": "lint_check", "description": "Run linter (ruff, flake8, eslint, pylint). USE after code changes to check code quality.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File or directory to lint"}, "fix": {"type": "boolean", "description": "Auto-fix issues if possible"}}, "required": []}}},

    # --- GIT ---
    {"type": "function", "function": {"name": "git_status", "description": "Show git working tree status. USE to see what files are modified/staged/untracked.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Git repo path"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_diff", "description": "Show git diff of changes. USE to review what changed before committing.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "staged": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_log", "description": "Show recent git commits. USE to understand project history.", "parameters": {"type": "object", "properties": {"count": {"type": "integer"}, "path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_commit", "description": "Stage all changes and commit. USE after completing a verified task.", "parameters": {"type": "object", "properties": {"message": {"type": "string", "description": "Descriptive commit message"}, "path": {"type": "string"}}, "required": ["message"]}}},

    # --- TASK TRACKING (use at START of complex tasks) ---
    {"type": "function", "function": {"name": "todo_write", "description": "Create/update task plan. CALL THIS FIRST for any task with >2 steps. Then update status as you work: pending→in_progress→completed. The system will auto-continue until all are done.", "parameters": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "content": {"type": "string", "description": "Specific, actionable task description"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "content", "status"]}}}, "required": ["todos"]}}},

    # --- RESEARCH ---
    {"type": "function", "function": {"name": "web_search", "description": "Search the web (DuckDuckGo). USE when you need current info, docs, or solutions not in the codebase. No API key needed.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "Fetch and read a URL's content (HTML stripped to text). USE after web_search to read specific pages.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "http_request", "description": "Make HTTP request (GET/POST/PUT/DELETE). USE for API testing and interaction. Returns status, headers, body.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string"}, "headers": {"type": "object"}, "body": {"type": "string"}}, "required": ["url"]}}},

    # --- DATABASE ---
    {"type": "function", "function": {"name": "db_query", "description": "Execute READ-ONLY SQLite query. USE to inspect workspace databases. Only SELECT allowed. Available DBs: /root/.opsora/memory.db, /root/.opsora/sessions.db", "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "SELECT query"}, "db_path": {"type": "string"}}, "required": ["sql"]}}},

    # --- MEMORY & CONTEXT ---
    {"type": "function", "function": {"name": "memory_add", "description": "Save important facts to persistent memory (survives across sessions). USE for key decisions, project facts, user preferences.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "source": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "memory_search", "description": "Search persistent memory for previously saved facts. USE when you need context from past sessions.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "graphify_query", "description": "Search project knowledge graph for context. USE to find related files, functions, and dependencies.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "workspace_status", "description": "Show workspace info: OS, Python version, disk space, active providers. USE to understand the environment.", "parameters": {"type": "object", "properties": {}}}},

    # --- UTILITY ---
    {"type": "function", "function": {"name": "image_read", "description": "Read image file metadata (dimensions, size, format). Supports PNG, JPG, GIF, SVG.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "pip_info", "description": "Show Python package info: version, location, dependencies.", "parameters": {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]}}},
]

# v3.1: Cost tracker + plugin manager (initialized once)
_cost_tracker = CostTracker()
_plugin_manager = PluginManager()
_plugin_manager.discover()

# Entry point — main() defined below in this file

# Add plugin tool schemas to SAFE_TOOLS
SAFE_TOOLS.extend(_plugin_manager.get_schemas())

TOOL_MAX_ROUNDS = 30
TOOL_MAX_OUTPUT = 30_000
SENSITIVE_PATHS = {".aws", ".ssh", ".gnupg", ".tccli"}
SENSITIVE_FILES = {"render.env", "secrets.env", ".opsora_env", "credentials", ".env",
                   "cloud-manager.sh", ".bash_history", ".netrc", ".pgpass"}
CREDENTIAL_KEYWORDS = ["api_key", "secret_key", "password", "token", "access_key"]


def execute_tool(name: str, args: dict[str, Any]) -> str:
    try:
        # --- Memory ---
        if name == "memory_add":
            from opsora_memory import add_memory
            return add_memory(args.get("text", ""), source=args.get("source", "cli"))
        if name == "memory_search":
            from opsora_memory import search_memory
            return json.dumps(search_memory(args.get("query", ""), args.get("limit", 5)), ensure_ascii=False)

        # --- Graphify / Workspace ---
        if name == "graphify_query":
            from opsora_graph_v2 import graph_query
            return json.dumps(graph_query(args.get("query", ""), depth=args.get("depth", 2)), ensure_ascii=False, default=str)
        if name == "workspace_status":
            from opsora_tools import workspace_status
            return workspace_status()

        # --- File Operations ---
        # SECURITY (Phase 1): every filepath is routed through _validate_path(),
        # which resolves symlinks and enforces the workspace boundary. The
        # sensitive-path blocklist below is kept as defense in depth.
        if name == "read_file":
            resolved = _validate_path(str(args["filepath"]))
            if SENSITIVE_PATHS & set(resolved.parts):
                return "BLOCKED: folder credential (.aws/.ssh/.gnupg) gak bisa dibaca."
            if resolved.name in SENSITIVE_FILES or resolved.name.startswith(".env"):
                return f"BLOCKED: {resolved.name} berisi credentials."
            if not resolved.exists():
                return f"ERROR: File not found: {resolved}"
            if needs_approval("read_file"):
                if not prompt_approval(f"Read {resolved}"):
                    return "Read cancelled."
            content = resolved.read_text(encoding="utf-8", errors="replace")[:TOOL_MAX_OUTPUT]
            return content

        if name == "write_file":
            fp = _validate_path(str(args["filepath"]))
            content = str(args.get("content", ""))
            if needs_approval("write_file"):
                preview = content[:500]
                if not prompt_approval(f"Write {fp}", preview):
                    return "Write cancelled."
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} chars to {fp}"

        if name == "edit_file":
            fp = _validate_path(str(args["filepath"]))
            if not fp.exists():
                return f"ERROR: File not found: {fp}"
            content = fp.read_text(encoding="utf-8")
            old_str, new_str = args["old_string"], args["new_string"]
            if old_str not in content:
                return f"ERROR: old_string not found in {fp}."
            if needs_approval("edit_file"):
                if not prompt_approval(f"Edit {fp}", f"- {old_str[:100]}\n+ {new_str[:100]}"):
                    return "Edit cancelled."
            new_content = content.replace(old_str, new_str, 1)
            fp.write_text(new_content, encoding="utf-8")
            return f"Edited {fp}: replaced {len(old_str)} → {len(new_str)} chars"

        # --- Shell ---
        if name == "run_command":
            cmd = str(args["command"])

            # Safety guard: check dangerous commands via NVIDIA AI (always active)
            _dangerous_patterns = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd",
                                   ":(){:|:&};:", "chmod -R 777 /", "curl|bash",
                                   "wget|sh", "format c:", "del /f /s"]
            if any(p in cmd.lower() for p in _dangerous_patterns):
                try:
                    from opsora_nvidia import check_command_safety
                    safety = check_command_safety(cmd)
                    if not safety.get("safe", True):
                        console.print(Text(f"  ⚠ BLOCKED: {safety.get('reason', 'Unsafe command')}", style="bold red"))
                        return f"BLOCKED by safety guard: {safety.get('reason', 'Unsafe command')}"
                except Exception:
                    pass  # If safety check fails, fall through to normal approval

            if needs_approval("run_command"):
                if not prompt_approval(f"Run command", cmd):
                    return "Command cancelled."
            # SECURITY (Phase 1): no shell=True — parse into an argv list so
            # metacharacters (; | && $ `` etc.) are passed through literally
            # and cannot inject extra commands. Shell features (pipes,
            # redirection) are no longer supported.
            try:
                cmd_args = shlex.split(cmd)
            except ValueError as e:
                return f"ERROR: Could not parse command: {e}"
            if not cmd_args:
                return "ERROR: Empty command."
            result = subprocess.run(
                cmd_args, capture_output=True, text=True, timeout=120,
                cwd=WORKSPACE_ROOT if WORKSPACE_ROOT.is_dir() else None,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output[:TOOL_MAX_OUTPUT] or f"Exit code {result.returncode}."

        # --- Search ---
        if name == "grep_search":
            pattern = args["pattern"]
            search_path = args.get("path", ".")
            if not Path(search_path).is_absolute():
                search_path = str(WORKSPACE_ROOT / search_path)
            file_type = args.get("file_type", "")
            cmd = ["grep", "-rn", "--color=never"]
            if file_type:
                cmd.extend([f"--include=*.{file_type}"])
            cmd.extend([pattern, search_path])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout
            if not output:
                return f"No matches for '{pattern}'"
            lines = output.strip().split("\n")
            if len(lines) > 200:
                output = "\n".join(lines[:200]) + f"\n… ({len(lines)} total)"
            return output[:TOOL_MAX_OUTPUT]

        if name == "glob_search":
            import glob as glob_mod
            base = args.get("base", "")
            pattern = args["pattern"]
            # If no base given, search across workspace + common project dirs
            if not base:
                search_roots = [
                    str(WORKSPACE_ROOT),
                    str(WORKSPACE_ROOT / "projects"),
                    str(WORKSPACE_ROOT / "opsora-cli"),
                ]
            else:
                p = Path(base)
                if not p.is_absolute():
                    p = WORKSPACE_ROOT / p
                search_roots = [str(p)]

            all_matches = []
            # Auto-add ** if pattern doesn't contain path separator (recursive by default)
            if "/" not in pattern and "**" not in pattern:
                pattern = f"**/{pattern}"

            # Directories/files to always skip
            _SKIP_DIRS = {"/.git/", "/__pycache__/", "/node_modules/", "/.cache/", "/.venv/", "/venv/", "/dist/", "/build/", "/.tox/"}
            _SKIP_EXTS = {".pyc", ".pyo", ".class", ".o", ".so", ".dylib"}

            for root in search_roots:
                full_pattern = os.path.join(root, pattern)
                matches = glob_mod.glob(full_pattern, recursive=True)
                for m in matches:
                    if not os.path.isfile(m):
                        continue
                    if any(skip in m for skip in _SKIP_DIRS):
                        continue
                    if any(m.endswith(ext) for ext in _SKIP_EXTS):
                        continue
                    try:
                        all_matches.append(str(Path(m).relative_to(WORKSPACE_ROOT)))
                    except ValueError:
                        all_matches.append(m)

            all_matches = sorted(set(all_matches))[:100]
            return json.dumps(all_matches, indent=2) if all_matches else f"Gak ada file matching '{args['pattern']}'"

        if name == "list_directory":
            target = Path(args["path"])
            if not target.is_absolute():
                target = WORKSPACE_ROOT / target
            if not target.is_dir():
                return f"ERROR: {target} is not a directory."
            entries = sorted(target.iterdir())[:100]
            lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]
            return "\n".join(lines) if lines else "Empty directory."

        # --- Web ---
        if name == "web_fetch":
            import re as re_mod
            url = args["url"]
            if not url.startswith(("http://", "https://")):
                return "ERROR: URL must start with http:// or https://"
            max_chars = int(args.get("max_chars", 50000))
            req = Request(url, headers={"User-Agent": "Opsora/3.0 Agent"})
            try:
                with urlopen(req, timeout=15) as resp:
                    raw = resp.read(max_chars * 2).decode("utf-8", errors="replace")
            except Exception as e:
                return f"ERROR: {e}"
            clean = re_mod.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re_mod.DOTALL)
            clean = re_mod.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re_mod.DOTALL)
            clean = re_mod.sub(r"<[^>]+>", " ", clean)
            clean = re_mod.sub(r"\s+", " ", clean).strip()
            return clean[:max_chars]

        # --- Git Tools ---
        # SECURITY (Phase 1): git tools run with argv lists + cwd (no shell=True),
        # so a user-controlled path cannot inject shell commands.
        if name == "git_diff":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            if not Path(repo_path).is_dir():
                return f"ERROR: Not a directory: {repo_path}"
            diff_cmd = ["git", "diff"] + (["--cached"] if args.get("staged") else [])
            stat_res = subprocess.run(
                diff_cmd + ["--stat"], capture_output=True, text=True, timeout=30, cwd=repo_path,
            )
            full_res = subprocess.run(
                diff_cmd, capture_output=True, text=True, timeout=30, cwd=repo_path,
            )
            stat_out = (stat_res.stdout or stat_res.stderr or "").strip()
            full_out = (full_res.stdout or full_res.stderr or "").strip()
            if not stat_out and not full_out:
                return "No changes."
            output = f"{stat_out}\n---FULL DIFF---\n{full_out}".strip()
            # Truncate large diffs
            if len(output) > 8000:
                lines = output.split("\n")
                stat_end = next((i for i, l in enumerate(lines) if "---FULL DIFF---" in l), 20)
                output = "\n".join(lines[:stat_end]) + f"\n… diff truncated ({len(output)} chars total)"
            return output

        if name == "git_status":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            if not Path(repo_path).is_dir():
                return f"ERROR: Not a directory: {repo_path}"
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10, cwd=repo_path,
            )
            output = (result.stdout or result.stderr or "Clean working tree.").strip()
            return output

        if name == "git_log":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            if not Path(repo_path).is_dir():
                return f"ERROR: Not a directory: {repo_path}"
            try:
                count = int(args.get("count", 10))
            except (TypeError, ValueError):
                return "ERROR: count must be an integer."
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{count}"],
                capture_output=True, text=True, timeout=10, cwd=repo_path,
            )
            return (result.stdout or result.stderr or "No commits found.").strip()

        if name == "run_tests":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            if not Path(repo_path).is_dir():
                return f"ERROR: Not a directory: {repo_path}"
            rp = Path(repo_path)

            # SECURITY (Phase 1): the filter is parsed into argv tokens and
            # validated — it is never interpolated into a shell string. Only
            # "-k <expr>" is accepted as an option (pytest keyword filter);
            # every other token must be a test path / node id. Anything else
            # (arbitrary options, shell metacharacters) is rejected.
            filter_args: list[str] = []
            test_filter = str(args.get("filter", "") or "").strip()
            if test_filter:
                try:
                    tokens = shlex.split(test_filter)
                except ValueError:
                    return f"ERROR: Could not parse test filter: {test_filter!r}"
                i = 0
                while i < len(tokens):
                    tok = tokens[i]
                    if tok == "-k":
                        expr = " ".join(tokens[i + 1:])
                        if not expr or not re.fullmatch(r"[A-Za-z0-9_ ./:\[\]=,~+()-]+", expr):
                            return f"ERROR: Invalid -k filter expression: {expr!r}"
                        filter_args.extend(["-k", expr])
                        break
                    if tok.startswith("-"):
                        return f"ERROR: Unsupported pytest option in filter: {tok}"
                    if not re.fullmatch(r"[A-Za-z0-9_./:\[\]=,~+-]+", tok):
                        return f"ERROR: Invalid test filter: {tok!r}"
                    filter_args.append(tok)
                    i += 1

            # Auto-detect test framework (argv lists + cwd, no shell=True)
            cmd: Optional[list[str]] = None
            if (rp / "pytest.ini").exists() or (rp / "pyproject.toml").exists() or (rp / "setup.py").exists() or list(rp.glob("**/test_*.py")):
                cmd = ["python3", "-m", "pytest", *filter_args, "-x", "-q", "--tb=short"]
            elif (rp / "package.json").exists():
                cmd = ["npm", "test"]
            elif (rp / "Cargo.toml").exists():
                cmd = ["cargo", "test"]
            elif (rp / "go.mod").exists():
                cmd = ["go", "test", "./..."]
            elif (rp / "Makefile").exists():
                cmd = ["make", "test"]
            else:
                return "No test framework detected. Supported: pytest, npm test, cargo test, go test, make test."

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=repo_path)
            output = (result.stdout or "") + (result.stderr or "")
            output = "\n".join(output.splitlines()[:100])  # was: | head -100
            return output.strip()[:TOOL_MAX_OUTPUT] or f"Tests exited with code {result.returncode}."

        if name == "git_commit":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            if not Path(repo_path).is_dir():
                return f"ERROR: Not a directory: {repo_path}"
            message = args.get("message", "auto-commit")
            if needs_approval("git_commit"):
                if not prompt_approval(f"git commit in {repo_path}", message):
                    return "Commit cancelled."
            add_res = subprocess.run(
                ["git", "add", "-A"], capture_output=True, text=True, timeout=30, cwd=repo_path,
            )
            if add_res.returncode != 0:
                return (add_res.stderr or add_res.stdout or "git add failed.").strip()
            result = subprocess.run(
                ["git", "commit", "-m", str(message)],
                capture_output=True, text=True, timeout=30, cwd=repo_path,
            )
            return (result.stdout or result.stderr or "Nothing to commit.").strip()

        if name == "lint_check":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            rp = Path(repo_path)
            # SECURITY (Phase 1): validate the target, then run the linter as
            # an argv list with cwd — the path is never put into a shell string.
            if rp.is_dir():
                lint_cwd, target = str(rp), "."
            elif rp.is_file():
                lint_cwd, target = str(rp.parent), str(rp)
            else:
                return f"ERROR: Not a file or directory: {repo_path}"
            fix = ["--fix"] if args.get("fix") else []

            # Auto-detect linter (argv lists + cwd, no shell=True)
            cmd: Optional[list[str]] = None
            if shutil.which("ruff"):
                cmd = ["ruff", "check", *fix, target]
            elif shutil.which("flake8"):
                cmd = ["flake8", target]
            elif Path(lint_cwd, "package.json").exists() and shutil.which("npx"):
                cmd = ["npx", "eslint", *fix, target]
            elif shutil.which("pylint"):
                cmd = ["pylint", target]
            else:
                return "No linter found. Install: ruff, flake8, eslint, or pylint."

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=lint_cwd)
            output = (result.stdout or result.stderr or "No issues found.").strip()
            output = "\n".join(output.splitlines()[:60])  # was: | head -60
            return output[:TOOL_MAX_OUTPUT]

        if name == "image_read":
            fp = _validate_path(str(args["filepath"]))
            if not fp.exists():
                return f"ERROR: File not found: {fp}"
            # Get image metadata using stdlib
            import struct
            suffix = fp.suffix.lower()
            size = fp.stat().st_size
            size_str = f"{size:,}B" if size < 1024 else f"{size // 1024}KB"
            info = f"File: {fp.name}  Size: {size_str}  Type: {suffix}"

            # Try to get dimensions for PNG
            if suffix == ".png" and size > 24:
                try:
                    with open(fp, "rb") as f:
                        f.read(16)  # skip PNG header
                        w = struct.unpack(">I", f.read(4))[0]
                        h = struct.unpack(">I", f.read(4))[0]
                        info += f"  Dimensions: {w}x{h}"
                except Exception:
                    pass
            elif suffix in (".jpg", ".jpeg") and size > 10:
                try:
                    with open(fp, "rb") as f:
                        f.read(2)
                        while True:
                            marker, = struct.unpack(">H", f.read(2))
                            if marker == 0xFFD9:  # EOI
                                break
                            if 0xFFC0 <= marker <= 0xFFC3:
                                f.read(3)
                                h = struct.unpack(">H", f.read(2))[0]
                                w = struct.unpack(">H", f.read(2))[0]
                                info += f"  Dimensions: {w}x{h}"
                                break
                            else:
                                length, = struct.unpack(">H", f.read(2))
                                f.read(length - 2)
                except Exception:
                    pass
            return info

        if name == "pip_info":
            pkg = str(args["package"])
            # SECURITY (Phase 1): argv list — no shell involved, so the
            # package name needs no quoting and cannot inject anything.
            result = subprocess.run(
                ["pip", "show", pkg],
                capture_output=True, text=True, timeout=15,
            )
            return (result.stdout or result.stderr or f"Package '{pkg}' not found.").strip()

        # --- Todo/Task Tracking ---
        if name == "todo_write":
            todos = args.get("todos", [])
            if not todos:
                return "No todos provided."
            # Store globally for display
            global _current_todos
            _current_todos = todos
            # Render the todo list
            lines = []
            for t in todos:
                status_icon = {"pending": "○", "in_progress": "●", "completed": "✓"}.get(t.get("status", "pending"), "○")
                lines.append(f"  {status_icon} [{t['id']}] {t['content']}")
            return "\n".join(lines)

        # --- v3.1 New Tools ---
        if name == "web_search":
            from opsora_new_tools import web_search
            return web_search(args.get("query", ""), args.get("max_results", 5))
        if name == "db_query":
            from opsora_new_tools import db_query
            return db_query(args.get("sql", ""), args.get("db_path", "/root/.opsora/memory.db"))
        if name == "http_request":
            from opsora_new_tools import http_request
            return http_request(args.get("url", ""), args.get("method", "GET"), args.get("headers"), args.get("body"))

        # --- Plugins ---
        if _plugin_manager and name in _plugin_manager.plugins:
            return _plugin_manager.execute(name, args)

        # --- MCP ---
        if name.startswith("mcp__"):
            return _mcp_client.call_tool_full(name, args) if _mcp_client else f"MCP not initialized."

        return f"Unknown tool: {name}"
    except Exception as e:
        # SECURITY (Phase 1): tool exceptions can carry provider/network
        # details (URLs, headers) — redact before the text reaches the UI.
        return f"Tool error: {redact_display(str(e))}"


# ============================================================================
# Provider Invocation
# ============================================================================

SYSTEM_PROMPT = (
    "You are Opsora — a fully autonomous agentic coding assistant running in a terminal.\n"
    "You solve problems end-to-end without asking for permission or clarification.\n\n"

    "## CORE BEHAVIOR (FOLLOW ALWAYS):\n"
    "1. **UNDERSTAND** — Read the request. Identify what needs to be done.\n"
    "2. **PLAN** — For tasks with >2 steps, call `todo_write` to create a plan FIRST.\n"
    "3. **EXPLORE** — Use `read_file`, `grep_search`, `glob_search`, `list_directory` to understand the codebase BEFORE making changes.\n"
    "4. **EXECUTE** — Do the work. Write code, run commands, create files. Update todos as you go.\n"
    "5. **VERIFY** — After each change, verify it works:\n"
    "   - Code written → `read_file` to confirm + `run_tests` if tests exist\n"
    "   - Command run → check exit code and output\n"
    "   - File edited → `git_diff` to confirm changes\n"
    "6. **FIX** — If verification fails, fix immediately. Try different approaches (max 3 attempts).\n"
    "7. **REPORT** — When ALL done, give a concise summary (1-3 sentences).\n\n"

    "## TOOL PRIORITY (use in this order):\n"
    "- **Explore first:** `glob_search` → `read_file` → `grep_search` (understand before acting)\n"
    "- **Code changes:** `write_file` (new files) → `edit_file` (modify existing) → `run_command` (build/test)\n"
    "- **Verify:** `read_file` (confirm content) → `run_tests` (check correctness) → `git_diff` (review changes)\n"
    "- **Research:** `web_search` (find info) → `web_fetch` (read pages) → `http_request` (API calls)\n"
    "- **Database:** `db_query` (read-only SQL)\n"
    "- **Git:** `git_status` → `git_diff` → `git_log` → `git_commit`\n\n"

    "## ABSOLUTE RULES:\n"
    "- NEVER narrate ('Let me check...', 'I will now...'). Just DO it.\n"
    "- NEVER ask back ('Which approach?', 'Should I?'). Decide and execute.\n"
    "- NEVER stop mid-task. If something fails, try a different approach.\n"
    "- NEVER say 'I cannot' — find another way.\n"
    "- Be concise. 1-3 sentences per response unless detail is requested.\n"
    "- Match the user's language.\n"
    "- If search returns empty, try different patterns or paths. Don't give up.\n"
    "- After writing/editing code, ALWAYS read the file back to confirm.\n"
    "- After running tests, fix ALL failures before reporting done.\n"
    "- Workspace: /root/projects/ (repos), /root/opsora-cli/ (CLI code), /root (home).\n\n"

    "## ERROR HANDLING:\n"
    "- Command fails → read error, try fix, retry with different approach\n"
    "- File not found → use glob_search to find it\n"
    "- Permission denied → try alternative path or method\n"
    "- Import error → pip install the package\n"
    "- Test fails → read the test, understand the failure, fix the code\n\n"

    "## EXAMPLE FLOW:\n"
    "User: 'bikin REST API dengan auth'\n"
    "→ todo_write: [1. Explore project structure, 2. Setup framework, 3. Create auth module, 4. Create endpoints, 5. Add tests, 6. Verify]\n"
    "→ glob_search('**/*.py') → read_file('requirements.txt')  # explore\n"
    "→ write_file('app/main.py', ...)  # create\n"
    "→ read_file('app/main.py')  # verify\n"
    "→ run_command('python -m pytest')  # test\n"
    "→ Fix any failures\n"
    "→ todo_write: all completed\n"
    "→ 'REST API dibuat di app/ dengan JWT auth, 5 endpoints, dan 12 passing tests.'\n"
)

_mcp_client: Optional[MCPClient_v2] = None
_current_todos: list[dict] = []
_project_context: str = ""


def reset_globals() -> None:
    """Reset all module-level mutable globals to their import-time state.

    Phase 1 (architect task 8): lazily-created provider clients, the health
    cache, cost/plugin singletons, and session state persist across unit
    tests and pollute results (e.g. a client created against one patched
    environment leaks into the next test). Tests should call this from an
    autouse fixture — see tests/test_v2_core.py (the fixture should move to
    tests/conftest.py so it applies to the whole suite).

    Note: SAFE_TOOLS is intentionally NOT reset — plugin schemas are appended
    to it exactly once at import time, and re-appending would duplicate them.
    """
    global _nvidia_client, _alibaba_client, _model_studio_client
    global _openai_client, _tokenhub_client, _opsora_api_client
    global _provider_health_cache, _cost_tracker, _plugin_manager
    global _mcp_client, _current_todos, _project_context
    _nvidia_client = None
    _alibaba_client = None
    _model_studio_client = None
    _openai_client = None
    _tokenhub_client = None
    _opsora_api_client = None
    _provider_health_cache = {}
    _cost_tracker = CostTracker()
    _plugin_manager = PluginManager()
    _plugin_manager.discover()
    _mcp_client = None
    _current_todos = []
    _project_context = ""


def load_project_context() -> str:
    """Load opsora.md from workspace root or current project dir."""
    global _project_context
    candidates = [
        WORKSPACE_ROOT / "opsora.md",
        WORKSPACE_ROOT / ".opsora" / "opsora.md",
        WORKSPACE_ROOT / "OPSORA.md",
    ]
    for path in candidates:
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                _project_context = content[:3000]  # Cap at 3000 chars
                return _project_context
    return ""


def invoke_provider(provider: str, model: str, messages: list[dict], use_tools: bool = True) -> Any:
    """Invoke a provider — THE choke point for provider-call resilience.

    Phase 1 (tasks 16-18): every provider call flows through here, so this is
    the single place where the circuit breaker gates the call, transient
    errors are retried with exponential backoff + jitter, and structured log
    events are emitted. Fatal errors (4xx auth/validation, unknown provider)
    are never retried and never trip the breaker.
    """
    slog = get_structured_logger()
    breaker = get_breaker(provider)
    if not breaker.allow_request():
        status = breaker.status()
        slog.warning(
            "provider_call_rejected",
            provider=provider, model=model, reason="circuit_open",
            retry_after_seconds=status["retry_after_seconds"],
        )
        raise CircuitOpenError(provider, retry_after=status["retry_after_seconds"])

    all_tools = list(SAFE_TOOLS)
    if _mcp_client:
        all_tools.extend(_mcp_client.to_openai_tools())

    def _call_openai(client, max_tokens=4096):
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        if use_tools and all_tools:
            kwargs["tools"] = all_tools
            kwargs["tool_choice"] = "auto"

        def _attempt():
            return client.chat.completions.create(**kwargs)

        # Task 17: retry transient failures (5xx/429/connection) with
        # exponential backoff + jitter. Fatal 4xx raise on first occurrence.
        return retry_with_backoff(
            _attempt,
            on_retry=lambda attempt, exc, delay: slog.warning(
                "provider_call_retry",
                provider=provider, model=model, attempt=attempt,
                delay_seconds=round(delay, 2), error=str(exc)[:200],
            ),
        )

    def _dispatch() -> Any:
        if provider == "nvidia" and get_nvidia_client():
            return _call_openai(get_nvidia_client())
        if provider == "alibaba" and get_alibaba_client():
            return _call_openai(get_alibaba_client(), max_tokens=8192)
        if provider == "model_studio" and get_model_studio_client():
            return _call_openai(get_model_studio_client(), max_tokens=8192)
        if provider == "openai" and get_openai_client():
            return _call_openai(get_openai_client())
        if provider == "tokenhub" and get_tokenhub_client():
            return _call_openai(get_tokenhub_client(), max_tokens=8192)
        if provider == "opsora_api" and get_opsora_api_client():
            return _call_openai(get_opsora_api_client(), max_tokens=8192)
        if provider == "bedrock" and bedrock_available():
            runtime = boto3.Session(profile_name=AWS_PROFILE).client(
                "bedrock-runtime", region_name=AWS_REGION,
                config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
            )
            converted = [{"role": m["role"], "content": [{"text": str(m.get("content", ""))}]} for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
            if not converted:
                converted = [{"role": "user", "content": [{"text": "Hello"}]}]
            resp = runtime.converse(modelId=model, system=[{"text": SYSTEM_PROMPT}], messages=converted, inferenceConfig={"maxTokens": 4096, "temperature": 0.2})
            text = resp["output"]["message"]["content"][0]["text"]

            class _BR:
                def __init__(self, t):
                    self.content = t
                    self.tool_calls = None
                    self.role = "assistant"

            return type("R", (), {"choices": [type("C", (), {"message": _BR(text)})()]})()

        raise RuntimeError(f"Provider '{provider}' not available")

    # Task 18: a half-open breaker admits exactly one probe; its outcome is
    # decisive regardless of error class (even a fatal 4xx from the probe
    # re-opens the circuit, otherwise the breaker would stick half-open).
    _was_probe = breaker.state == "half-open"
    _started = time.time()
    slog.info("provider_call_start", provider=provider, model=model)
    try:
        result = _dispatch()
    except Exception as exc:
        _elapsed_ms = int((time.time() - _started) * 1000)
        transient = is_transient_error(exc)
        if transient or _was_probe:
            breaker.record_failure()
        slog.error(
            "provider_call_failed",
            provider=provider, model=model, error=str(exc)[:300],
            elapsed_ms=_elapsed_ms, transient=transient,
            breaker_state=breaker.state,
        )
        raise
    breaker.record_success()
    slog.info(
        "provider_call_success",
        provider=provider, model=model,
        elapsed_ms=int((time.time() - _started) * 1000),
    )
    return result


def call_with_fallback(messages: list[dict], selection: Selection, use_tools: bool = True) -> tuple[Any, Selection]:
    errors = []
    candidates = [selection]
    
    # Add alternative models from the same tier based on intent
    from opsora_routing import IntentRouter
    router = IntentRouter()
    intent = router.classify(messages[-1].get("content", "") if messages else "")
    
    tier_map = {
        "code": CODING_MODELS,
        "analysis": REASONING_MODELS,
        "quick": FAST_MODELS,
        "cloud": POWER_MODELS,
        "creative": POWER_MODELS,
        "general": POWER_MODELS,
    }
    tier = tier_map.get(intent, POWER_MODELS)
    
    # Add other models from the same tier
    for provider, model in tier:
        if provider == selection.provider and model == selection.model:
            continue
        if is_provider_available(provider):
            candidates.append(Selection(provider, model))
    
    # Also add first model from other available providers
    for prov in get_provider_order():
        if prov == selection.provider:
            continue
        if is_provider_available(prov):
            models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
            if models:
                candidates.append(Selection(prov, models[0]))

    slog = get_structured_logger()
    for c in candidates:
        try:
            result = invoke_provider(c.provider, c.model, messages, use_tools)
            if c.provider != selection.provider or c.model != selection.model:
                # Task 16/18: visible trail when the fallback chain kicked in
                # (e.g. because a tripped breaker failed fast upstream).
                slog.info(
                    "provider_fallback_used",
                    requested_provider=selection.provider, requested_model=selection.model,
                    fallback_provider=c.provider, fallback_model=c.model,
                )
            return result, c
        except Exception as e:
            errors.append(f"{c.provider}:{c.model} → {str(e)[:120]}")
    slog.error("all_providers_failed", errors=errors[:3])
    raise RuntimeError(f"All providers failed: {'; '.join(errors[:3])}")


# ============================================================================
# Agent Loop — ReAct with Self-Reflection
# ============================================================================


# ============================================================================
# Context Compression — summarize old messages when context > 70%
# ============================================================================

def compress_context(messages: list[dict], selection: Selection) -> list[dict]:
    """Compress context using smart module (LLM-powered) with naive fallback."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    estimated_tokens = total_chars // 4

    # Use model-aware context window
    _ctx_windows = {
        "qwen-plus": 800_000, "qwen-turbo": 800_000, "qwen-max": 800_000,
        "qwen3-coder-plus": 800_000, "qwen3-coder-flash": 800_000,
        "meta/llama-3.1-70b-instruct": 100_000, "meta/llama-3.1-8b-instruct": 100_000,
        "deepseek-ai/deepseek-v4-flash": 100_000, "hy3": 100_000, "kimi-k3": 100_000,
    }
    context_total = _ctx_windows.get(selection.model, 131_072)

    if estimated_tokens / context_total < 0.7:
        return messages  # No compression needed

    # Try LLM-powered compression from module
    try:
        from opsora_compression import compress
        token_budget = int(context_total * 0.75)
        result = compress(messages, token_budget=token_budget)
        if result and len(result) < len(messages):
            return result
    except Exception:
        pass  # Fall through to naive compression

    # Naive fallback: truncate old tool results
    system_msgs = [m for m in messages if m.get("role") == "system"]
    recent = messages[-6:]
    compressed = list(system_msgs)
    summary_parts = []
    for m in messages:
        if m in recent or m in system_msgs:
            continue
        role = m.get("role", "")
        content = str(m.get("content", ""))
        if role == "tool" and len(content) > 200:
            summary_parts.append(f"[{m.get('name', 'tool')}: {content[:100]}…]")
        elif role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                summary_parts.append(f"[called {fn.get('name', '?')}]")
        elif role == "assistant" and content:
            compressed.append(m)
        elif role == "user" and content:
            # Phase 1: keep old user turns — dropping them silently loses
            # conversation intent (they are short relative to tool output).
            compressed.append(m)
    if summary_parts:
        compressed.append({
            "role": "system",
            "content": "Previous actions (compressed): " + "; ".join(summary_parts[:20]),
        })
    compressed.extend(recent)
    return compressed


# ============================================================================
# Token & Cost Tracking
# ============================================================================

# Phase 1: pricing table de-duplicated. MODEL_COSTS and _DEFAULT_COST are
# imported from opsora_cost (config/model_costs.json + built-in fallback) —
# do NOT add a local copy here.

def estimate_cost(model: str, input_chars: int, output_chars: int) -> tuple[int, float]:
    """Return (total_tokens, cost_usd) for a response."""
    input_tokens = input_chars // 4
    output_tokens = output_chars // 4
    total = input_tokens + output_tokens
    costs = MODEL_COSTS.get(model, _DEFAULT_COST)
    cost = (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000
    return total, cost


# ============================================================================
# Input Validation — Security helpers
# ============================================================================

def _validate_path(path: str, base: Optional[Path] = None) -> Path:
    """Resolve path (following symlinks) and ensure it's within base directory.

    SECURITY (Phase 1): base is read at call time so tests/patches of
    WORKSPACE_ROOT apply, symlinks are fully resolved before the boundary
    check, and containment uses is_relative_to (string startswith could be
    bypassed by sibling dirs like /root-evil for base /root).
    Raises ValueError if the path is invalid or escapes the workspace.
    """
    if base is None:
        base = WORKSPACE_ROOT
    if not path or not str(path).strip():
        raise ValueError(f"Invalid path: {path!r}")
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    try:
        resolved = p.resolve()
        base_resolved = base.resolve()
    except (OSError, RuntimeError, ValueError) as e:
        raise ValueError(f"Invalid path: {path}") from e
    if not resolved.is_relative_to(base_resolved):
        raise ValueError(f"Path traversal attempt blocked: {path}")
    return resolved


def _validate_command(cmd: str) -> str:
    """Basic command validation - block dangerous patterns."""
    dangerous = [
        "rm -rf /", "mkfs", "dd if=", "> /dev/sd",
        ":(){:|:&};:", "chmod -R 777 /", "curl|bash",
        "wget|sh", "format c:", "del /f /s",
    ]
    cmd_lower = cmd.lower()
    for d in dangerous:
        if d in cmd_lower:
            raise ValueError(f"Dangerous command blocked: {d}")
    return cmd


# ============================================================================
# Error Recovery — auto-retry failed commands
# ============================================================================

# Allowed packages for auto-install (security: prevent supply chain attacks)
_AUTO_INSTALL_ALLOWLIST = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "requests": "requests",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "pydantic": "pydantic",
    "click": "click",
    "rich": "rich",
    "prompt-toolkit": "prompt-toolkit",
    "boto3": "boto3",
    "pytest": "pytest",
    "ruff": "ruff",
    "mypy": "mypy",
    "sqlparse": "sqlparse",
    "tiktoken": "tiktoken",
    "python-dotenv": "python-dotenv",
}


def _try_error_recovery(name: str, args: dict, output: str, history: list[dict], selection: Selection) -> str:
    """If a command failed, try to recover by asking the model for a fix."""
    if name != "run_command":
        return output

    # Detect failure patterns
    error_patterns = [
        "command not found", "no such file", "module not found",
        "importerror", "modulenotfounderror", "permission denied",
        "error:", "traceback", "errno", "failed",
    ]
    output_lower = output.lower()
    if not any(p in output_lower for p in error_patterns):
        return output

    # Auto-install: detect missing Python package
    if "modulenotfounderror" in output_lower or "importerror" in output_lower:
        import re
        match = re.search(r"No module named '(\w+)'", output) or re.search(r"cannot import name.*from '(\w+)'", output)
        if match:
            pkg = match.group(1)
            # Map common import names to pip package names
            pkg_map = {
                "cv2": "opencv-python", "PIL": "Pillow", "sklearn": "scikit-learn", 
                "yaml": "pyyaml", "bs4": "beautifulsoup4", "dotenv": "python-dotenv",
            }
            pip_pkg = pkg_map.get(pkg, pkg)
            
            # SECURITY: Only allow pre-approved packages
            if pip_pkg not in _AUTO_INSTALL_ALLOWLIST:
                console.print(f"  [dim red]⚠ Auto-install blocked: '{pip_pkg}' not in allowlist[/dim]")
                return output
            
            console.print(f"  [dim cyan]⚡ auto-install: pip install {pip_pkg}[/dim]")
            # SECURITY (Phase 1): argv list, and pip_pkg is allowlist-gated
            # above — no shell involved.
            install_result = subprocess.run(
                ["pip", "install", "--no-cache-dir", pip_pkg],
                capture_output=True, text=True, timeout=120,
            )
            if install_result.returncode == 0:
                # Retry the original command (SECURITY: argv list, no shell=True)
                try:
                    retry_args = shlex.split(str(args["command"]))
                except ValueError:
                    return output
                retry = subprocess.run(
                    retry_args, capture_output=True, text=True, timeout=120,
                    cwd=WORKSPACE_ROOT if WORKSPACE_ROOT.is_dir() else None,
                )
                retry_output = (retry.stdout or "") + (retry.stderr or "")
                console.print(f"  [dim green]✓ {pip_pkg} installed, command retried[/dim]")
                return retry_output[:TOOL_MAX_OUTPUT] or f"Retry exit code {retry.returncode}."

    return output


# ============================================================================
# Auto-Diff — show diff after edit_file
# ============================================================================

def _auto_diff_after_edit(name: str, args: dict) -> None:
    """After edit_file, show a compact diff of what changed."""
    if name != "edit_file":
        return
    old_str = args.get("old_string", "")
    new_str = args.get("new_string", "")
    filepath = args.get("filepath", "")
    if old_str and new_str and old_str != new_str:
        render_file_edit(filepath, old_str, new_str)


# ============================================================================
# Session Auto-Title
# ============================================================================

def generate_session_title(history: list[dict], selection: Selection) -> str:
    """Generate a concise session title from the first user message."""
    for msg in history:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if len(content) <= 50:
                return content
            # Ask model for a short title
            try:
                resp, _ = call_with_fallback(
                    [{"role": "system", "content": "Generate a 3-6 word title for this conversation. Only output the title, nothing else."},
                     {"role": "user", "content": content[:500]}],
                    selection, use_tools=False,
                )
                msg_obj = resp.choices[0].message if hasattr(resp, "choices") else resp
                title = (getattr(msg_obj, "content", "") or "").strip().strip('"').strip("'")
                if title and len(title) < 60:
                    return title
            except Exception:
                pass
            return content[:50]
    return "untitled"


# ============================================================================
# Agent Loop — ReAct with Activity Trail, Auto-Recovery, Compression
# ============================================================================

def run_agent_turn(history: list[dict], selection: Selection, status_bar: StatusBar) -> tuple[list[dict], Selection]:
    total_rounds = TOOL_MAX_ROUNDS
    total_input_chars = 0
    total_output_chars = 0

    # Turn separator — visual break between conversation turns
    _turn_num = sum(1 for m in history if m.get("role") == "user") + 1
    model_short = selection.model.split("/")[-1] if "/" in selection.model else selection.model
    console.print(Text(f"  ── #{_turn_num} {model_short} ", style="dim") + Text("─" * max(5, 30 - len(str(_turn_num)) - len(model_short)), style="#2a2a3a"))

    for round_idx in range(total_rounds):
        # Build system prompt with optional project context
        sys_prompt = SYSTEM_PROMPT
        if _project_context:
            sys_prompt += f"\n\n## PROJECT CONTEXT (from opsora.md):\n{_project_context}\n"
        messages = [{"role": "system", "content": sys_prompt}, *history]

        # Context compression when > 70%
        messages = compress_context(messages, selection)

        # Update context estimate
        status_bar.context_used = sum(len(str(m.get("content", ""))) for m in messages) // 4
        status_bar.provider = selection.provider
        status_bar.model = selection.model
        
        try:
            # Retry with exponential backoff on transient errors
            _max_retries = 3
            _retry_delay = 2.0
            for _retry in range(_max_retries):
                try:
                    with Live(
                        Spinner("dots", text=f"[cyan]{selection.model}…[/cyan]", style="cyan"),
                        refresh_per_second=15, transient=True,
                    ):
                        response, selection = call_with_fallback(messages, selection, use_tools=True)
                    break  # Success
                except (URLError, ConnectionError, TimeoutError, OSError) as e:
                    if _retry < _max_retries - 1:
                        console.print(Text(f"  ↻ Retry {_retry+1}/{_max_retries} ({_retry_delay:.0f}s): {str(e)[:50]}", style="dim"))
                        time.sleep(_retry_delay)
                        _retry_delay *= 2  # Exponential backoff
                    else:
                        raise

            msg = response.choices[0].message if hasattr(response, "choices") else response
            msg_dict = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else {"role": "assistant", "content": getattr(msg, "content", "")}
            history.append(msg_dict)

            content = getattr(msg, "content", None) or ""
            tool_calls = getattr(msg, "tool_calls", None)

            # Track tokens (real from API response + char fallback)
            total_input_chars += sum(len(str(m.get("content", ""))) for m in messages)
            total_output_chars += len(content)
            _cost_tracker.record(selection.model, extract_usage(response))

            # Update activity based on what we're doing
            if tool_calls:
                # Activity will be set inside the tool loop for each tool execution
                pass  # Activity is set per-tool in the execution loop below
            else:
                status_bar.current_activity = "Berpikir..."

            # Stream text response
            if content:
                console.print()
                stream_markdown(content)

            # Handle tool calls
            if tool_calls:
                for ti, tc in enumerate(tool_calls, 1):
                    fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
                    name = fn.name if hasattr(fn, "name") else fn.get("name", "")
                    args_raw = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", "{}")
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                    # Update activity based on current task with specific details
                    activity_map = {
                        "read_file": f"Membaca file: {args.get('file_path', 'unknown')}",
                        "write_file": f"Menulis file: {args.get('file_path', 'unknown')}",
                        "edit_file": f"Mengedit file: {args.get('file_path', 'unknown')}",
                        "run_command": f"Menjalankan: {args.get('command', '').split()[0] if args.get('command') else 'command'}",
                        "glob_search": f"Mencari file: {args.get('pattern', '*')}",
                        "grep_search": f"Mencari pola: {args.get('pattern', '')[:20]}{'...' if len(args.get('pattern', '')) > 20 else ''}",
                        "list_directory": f"Membaca direktori: {args.get('path', '.')}",
                        "web_search": f"Mencari di web: {args.get('query', '')[:20]}{'...' if len(args.get('query', '')) > 20 else ''}",
                        "web_fetch": f"Mengambil halaman web: {args.get('url', '')[:30]}{'...' if len(args.get('url', '')) > 30 else ''}",
                        "memory_add": "Menambah ke memori",
                        "memory_search": "Mencari di memori",
                        "graphify_query": "Query knowledge graph",
                        "db_query": "Query database",
                        "aws_command": "Perintah AWS",
                        "todo_write": "Memperbarui todo"
                    }
                    # Truncate long paths for display
                    activity_text = activity_map.get(name, f"Menggunakan {name}")
                    if len(activity_text) > 60:
                        activity_text = activity_text[:57] + "..."
                    status_bar.current_activity = activity_text

                    # Safety reflection before dangerous tools
                    if name in ("run_command", "write_file", "edit_file"):
                        try:
                            from opsora_reflect_v2 import reflect
                            _tc_list = [{"name": name, "arguments": args}]
                            _safety = reflect(
                                user_input=history[-1].get("content", "") if history else "",
                                tool_calls=_tc_list,
                                history=history[-6:],
                            )
                            if not _safety.get("safe", True):
                                risks = ", ".join(_safety.get("risks", [])[:2])
                                console.print(Text(f"  ⚠ Safety: {risks}", style="bold yellow"))
                                if get_approval_mode() != ApprovalMode.FULL_AUTO:
                                    if not prompt_approval(f"⚠ {risks}", _safety.get("improvement", "")):
                                        output = "BLOCKED by safety check."
                                        tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                                        history.append({"role": "tool", "tool_call_id": tc_id, "content": output})
                                        continue
                        except Exception:
                            pass  # Don't block on reflection errors

                    # Execute tool with timing
                    _tool_start = time.time()
                    output = execute_tool(name, args)

                    # Auto-recovery for failed commands
                    output = _try_error_recovery(name, args, output, history, selection)

                    # Render tool output with elapsed time
                    _tool_elapsed = time.time() - _tool_start
                    render_tool_call(name, args, output, elapsed=_tool_elapsed)
                    total_output_chars += len(output)

                    # Auto-diff after file edits
                    _auto_diff_after_edit(name, args)

                    tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                    history.append({"role": "tool", "tool_call_id": tc_id, "content": output})

                # Show progress bar if todos exist
                if _current_todos:
                    done = sum(1 for t in _current_todos if t.get("status") == "completed")
                    total = len(_current_todos)
                    bar_len = 12
                    filled = int(bar_len * done / total) if total > 0 else 0
                    bar = "█" * filled + "░" * (bar_len - filled)
                    console.print(Text(f"  [{bar}] {done}/{total}", style="dim"))

                continue  # next round for tool results
            else:
                # --- SMART AUTO-CONTINUE ---
                # 1. Check pending todos
                has_pending = any(t.get("status") in ("pending", "in_progress") for t in _current_todos)
                if has_pending and round_idx < total_rounds - 2:
                    pending = [t["content"] for t in _current_todos if t.get("status") == "pending"]
                    in_progress = [t["content"] for t in _current_todos if t.get("status") == "in_progress"]
                    next_steps = in_progress + pending
                    if next_steps:
                        history.append({"role": "user", "content": (
                            f"Continue with the next step: {next_steps[0]}. "
                            f"Update todo_write status to in_progress, execute it, then update to completed. "
                            f"If it fails, try a different approach."
                        )})
                        continue

                # 2. Detect incomplete responses (hedging, planning without doing)
                _incomplete_signals = [
                    "i need", "let me", "i should", "i will", "we should",
                    "saya akan", "mari", "selanjutnya", "berikutnya", "langkah berikutnya",
                    "need to", "should also", "could also", "one more thing",
                    "first,", "next,", "then,", "after that",
                ]
                _is_hedging = content and len(content) < 200 and any(kw in content.lower() for kw in _incomplete_signals)
                if _is_hedging and round_idx < total_rounds - 3:
                    history.append({"role": "user", "content": (
                        "Don't plan or narrate — just execute the next step now. "
                        "Use tools to do the work directly."
                    )})
                    continue

                # 3. Detect unfinished multi-step work (response mentions files/code not yet created)
                _todo_count = len(_current_todos)
                _done_count = sum(1 for t in _current_todos if t.get("status") == "completed")
                if _todo_count > 0 and _done_count < _todo_count and round_idx < total_rounds - 2:
                    remaining = [t["content"] for t in _current_todos if t.get("status") != "completed"]
                    history.append({"role": "user", "content": (
                        f"There are still {_todo_count - _done_count} unfinished tasks: {remaining[0]}. "
                        f"Execute it now using tools. Don't just describe what to do — DO it."
                    )})
                    continue

                # 4. All done — break
                break

        except Exception as e:
            # SECURITY (Phase 1): provider/network errors can echo URLs,
            # headers or key fragments — redact before display.
            console.print(Text(f"✗ {redact_display(str(e))}", style="red"))
            break

    # Token/cost summary (v3.1: real tracking from API)
    cost_summary = _cost_tracker.session_total()
    real_tok = cost_summary["total_tokens"]
    real_cost = cost_summary["total_cost"]
    if real_tok == 0:
        real_tok, real_cost = estimate_cost(selection.model, total_input_chars, total_output_chars)
    console.print(f"  [dim]{status_bar.context_pct}% ctx · {real_tok:,} tok · ${real_cost:.4f} · {get_approval_mode().value}[/dim]")

    return history, selection


# ============================================================================
# Subagent Entry Point
# ============================================================================


def run_subagent(goal: str, selection: Selection) -> str:
    """Spawn sub-agents to handle a complex goal."""
    orchestrator = SubagentOrchestrator(
        invoke_fn=invoke_provider,
        tools=SAFE_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        max_workers=3,
    )
    orchestrator.plan_tasks(goal, selection.provider, selection.model)
    results = orchestrator.execute_all(selection.provider, selection.model)
    return orchestrator.synthesize(results, selection.provider, selection.model)


# ============================================================================
# Slash Commands
# ============================================================================


def handle_command(value: str, history: list[dict], selection: Selection, status_bar: StatusBar, session_id: str) -> tuple[bool, Optional[Selection], Optional[str]]:
    parts = shlex.split(value)
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit", "/q"):
        return False, None, None

    if cmd == "/help":
        render_help()
        return True, None, None

    if cmd == "/status":
        _show_status(selection, status_bar)
        return True, None, None

    if cmd == "/models":
        _show_models()
        return True, None, None

    if cmd == "/tools":
        _show_tools()
        return True, None, None

    if cmd == "/mode":
        new_mode = cycle_approval_mode()
        set_approval_mode(new_mode)
        status_bar.approval_mode = new_mode
        console.print(Text(f"  mode: {new_mode.value}", style="cyan"))
        return True, None, None

    if cmd == "/model":
        if len(parts) >= 2:
            prov = parts[1]
            if is_provider_available(prov):
                models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
                model = parts[2] if len(parts) > 2 else (models[0] if models else None)
                if model:
                    console.print(Text(f"  ✓ {prov}:{model}", style="green"))
                    return True, Selection(prov, model), None
            console.print(Text(f"  ✗ {prov} not available", style="red"))
        return True, None, None

    if cmd == "/tree":
        path = parts[1] if len(parts) > 1 else str(WORKSPACE_ROOT)
        render_file_tree(path)
        return True, None, None

    if cmd == "/sessions":
        sessions = list_sessions()
        if not sessions:
            console.print(Text("  no sessions.", style="dim"))
            return True, None, None
        console.print()
        for s in sessions:
            updated = datetime.fromtimestamp(s["updated_at"]).strftime("%m/%d %H:%M")
            console.print(
                Text(f"  {s['id'][:8]}", style="cyan"),
                Text(f"  {s['title'][:30]}", style=""),
                Text(f"  {s['model']}  {updated}", style="dim"),
            )
        console.print()
        return True, None, None

    if cmd == "/resume":
        if len(parts) < 2:
            console.print("[dim]Usage: /resume <session-id>[/dim]")
            return True, None, None
        sid = parts[1]
        # Try partial match
        if len(sid) < 12:
            all_sessions = list_sessions(50)
            matches = [s for s in all_sessions if s["id"].startswith(sid)]
            if matches:
                sid = matches[0]["id"]
        session = load_session(sid)
        if session:
            console.print(f"[green]✓[/green] Resumed session [bold]{session.title or session.id[:8]}[/bold] ({len(session.messages)} messages)")
            return True, Selection(session.provider, session.model), session.id
        console.print(f"[red]✗ Session '{sid}' not found[/red]")
        return True, None, None

    if cmd == "/save":
        title = " ".join(parts[1:]) if len(parts) > 1 else history[0].get("content", "untitled")[:40] if history else "untitled"
        sid = save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)
        console.print(f"[green]✓[/green] Session saved: [bold]{sid[:8]}[/bold] — {title}")
        return True, None, None

    if cmd == "/delete":
        if len(parts) < 2:
            console.print("[dim]Usage: /delete <session-id>[/dim]")
            return True, None, None
        if delete_session(parts[1]):
            console.print(f"[green]✓[/green] Session deleted")
        else:
            console.print(f"[red]✗ Not found[/red]")
        return True, None, None

    if cmd == "/new":
        history.clear()
        console.print("[green]✓[/green] New session started.")
        return True, None, None

    if cmd == "/clear":
        console.clear()
        print_welcome(selection.model, len(SAFE_TOOLS), get_approval_mode())
        return True, None, None

    if cmd == "/run":
        if len(parts) < 2:
            console.print(Text("  usage: /run <command>", style="dim"))
            return True, None, None
        cmd_str = " ".join(parts[1:])
        try:
            _validate_command(cmd_str)
        except ValueError as e:
            console.print(Text(f"  ✗ {e}", style="red"))
            return True, None, None
        output = execute_tool("run_command", {"command": cmd_str})
        console.print(Text(f"  ▶ {cmd_str}", style="bold dim"))
        console.print(Text(f"    {output[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/read":
        if len(parts) < 2:
            console.print(Text("  usage: /read <filepath>", style="dim"))
            return True, None, None
        try:
            _validate_path(parts[1])
        except ValueError as e:
            console.print(Text(f"  ✗ {e}", style="red"))
            return True, None, None
        output = execute_tool("read_file", {"filepath": parts[1]})
        lang = "python" if parts[1].endswith(".py") else "text"
        console.print(Text(f"  📄 {parts[1]}", style="bold dim"))
        console.print(Syntax(output[:5000], lang, theme="monokai", word_wrap=True))
        return True, None, None

    if cmd == "/diff":
        if len(parts) < 3:
            console.print(Text("  usage: /diff <file1> <file2>", style="dim"))
            return True, None, None
        try:
            _validate_path(parts[1])
            _validate_path(parts[2])
        except ValueError as e:
            console.print(Text(f"  ✗ {e}", style="red"))
            return True, None, None
        try:
            t1 = Path(parts[1]).read_text(encoding="utf-8")
            t2 = Path(parts[2]).read_text(encoding="utf-8")
            render_file_edit(parts[1], t1, t2)
        except Exception as e:
            console.print(Text(f"  ✗ {e}", style="red"))
        return True, None, None

    if cmd == "/memory":
        query = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not query:
            console.print(Text("  usage: /memory <query>", style="dim"))
            return True, None, None
        result = execute_tool("memory_search", {"query": query})
        console.print(Text(f"  🔍 {query}", style="bold dim"))
        console.print(Text(f"    {result[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/mcp":
        if _mcp_client:
            console.print(_mcp_client.render_status())
        else:
            console.print("[dim]MCP not configured. Create ~/.opsora/mcp.json[/dim]")
        return True, None, None

    if cmd == "/agent" or cmd == "/subagent":
        goal = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not goal:
            console.print("[dim]Usage: /agent <complex goal>[/dim]")
            return True, None, None
        console.print(f"[cyan]🤖 Spawning sub-agents for:[/cyan] {goal}")
        result = run_subagent(goal, selection)
        console.print()
        stream_markdown(result)
        return True, None, None

    # --- Phase 3: Skills (slash commands) ---
    if cmd == "/review":
        path = parts[1] if len(parts) > 1 else str(WORKSPACE_ROOT)
        console.print(Text("  📝 Reviewing changes…", style="cyan"))
        diff_output = execute_tool("git_diff", {"path": path})
        status_output = execute_tool("git_status", {"path": path})
        if "No changes" in diff_output and "Clean" in status_output:
            console.print(Text("  No changes to review.", style="dim"))
            return True, None, None
        # Inject review prompt into history
        review_prompt = (
            f"Review these code changes for correctness, security, and quality:\n\n"
            f"## Git Status:\n{status_output}\n\n## Diff:\n{diff_output[:8000]}\n\n"
            f"Provide a concise review with: ✓ good parts, ⚠ warnings, ✗ issues."
        )
        history.append({"role": "user", "content": review_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/deploy":
        target = parts[1] if len(parts) > 1 else "render"
        console.print(Text(f"  🚀 Deploying to {target}…", style="cyan"))
        deploy_prompt = f"Deploy the current project to {target}. Check git status first, push if needed, then trigger deployment."
        history.append({"role": "user", "content": deploy_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/explain":
        filepath = parts[1] if len(parts) > 1 else ""
        if not filepath:
            console.print(Text("  usage: /explain <filepath> [function]", style="dim"))
            return True, None, None
        try:
            _validate_path(filepath)
        except ValueError as e:
            console.print(Text(f"  ✗ {e}", style="red"))
            return True, None, None
        func_name = parts[2] if len(parts) > 2 else ""
        content = execute_tool("read_file", {"filepath": filepath})
        explain_prompt = f"Explain this code{'  specifically the function/class: ' + func_name if func_name else ''}:\n\nFile: {filepath}\n```\n{content[:6000]}\n```"
        history.append({"role": "user", "content": explain_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/refactor":
        filepath = parts[1] if len(parts) > 1 else ""
        if not filepath:
            console.print(Text("  usage: /refactor <filepath>", style="dim"))
            return True, None, None
        try:
            _validate_path(filepath)
        except ValueError as e:
            console.print(Text(f"  ✗ {e}", style="red"))
            return True, None, None
        content = execute_tool("read_file", {"filepath": filepath})
        refactor_prompt = (
            f"Refactor this code for better readability, performance, and maintainability. "
            f"Apply changes directly using edit_file:\n\nFile: {filepath}\n```\n{content[:6000]}\n```"
        )
        history.append({"role": "user", "content": refactor_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/test":
        filepath = parts[1] if len(parts) > 1 else ""
        target = filepath if filepath else str(WORKSPACE_ROOT)
        console.print(Text("  🧪 Generating tests…", style="cyan"))
        test_prompt = (
            f"Generate tests for {'the file: ' + filepath if filepath else 'the project'}. "
            f"Read the source code first, then create test files with good coverage. "
            f"Use the project's existing test framework."
        )
        history.append({"role": "user", "content": test_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/fix-ci":
        console.print(Text("  🔧 Analyzing CI failures…", style="cyan"))
        ci_prompt = (
            "Check for CI/CD failures. Look at recent git log, check if tests pass, "
            "review any lint errors, and fix the issues."
        )
        history.append({"role": "user", "content": ci_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    # --- Phase 4: Polish ---
    if cmd == "/copy":
        # Copy last assistant response to clipboard
        for msg in reversed(history):
            if msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                try:
                    subprocess.run(["termux-clipboard-set"], input=content, text=True, timeout=5)
                    console.print(Text(f"  ✓ Copied {len(content)} chars to clipboard", style="green"))
                except Exception:
                    console.print(Text("  ✗ termux-clipboard-set not available", style="red"))
                return True, None, None
        console.print(Text("  No response to copy.", style="dim"))
        return True, None, None

    if cmd == "/fork":
        # Fork current session — save and start fresh with context
        if history:
            title = generate_session_title(history[:4], selection)
            fork_id = save_session(session_id, f"fork: {title}", selection.provider, selection.model, get_approval_mode().value, history)
            console.print(Text(f"  ✓ Session forked: {fork_id[:8]}", style="green"))
            history.clear()
            _current_todos.clear()
        return True, None, None

    if cmd == "/solve":
        # Problem solver terstruktur — THINK → PLAN → ACT → VERIFY → REPORT
        problem_text = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not problem_text:
            console.print(Text("  usage: /solve <deskripsi masalah>", style="dim"))
            return True, None, None
        
        # Show progress header
        console.print()
        console.print(Text("  🔍 Memecahkan masalah dengan sistem THINK→PLAN→ACT→VERIFY→REPORT", style="bold cyan"))
        console.print()
        
        try:
            result = solve_problem(problem_text)
            
            # THINK phase
            console.print(Text("  💭 THINK: Memahami masalah", style="bold blue"))
            think_content = result.get("think", "")
            if think_content:
                # Truncate and format think content
                think_lines = think_content.split('\n')
                for line in think_lines[:3]:  # Show first 3 lines
                    if line.strip():
                        console.print(Text(f"     {line.strip()}", style="dim blue"))
            console.print()
            
            # PLAN phase
            console.print(Text("  📋 PLAN: Merencanakan langkah-langkah", style="bold blue"))
            plan_lines = result.get("plan", [])
            if plan_lines:
                for i, line in enumerate(plan_lines, 1):
                    clean_line = line.replace("PLAN: ", "")
                    console.print(Text(f"     {i}. {clean_line}", style="dim"))
            console.print()
            
            # ACT phase
            console.print(Text("  ⚡ ACTION: Menjalankan langkah pertama", style="bold blue"))
            act = result.get("act", {})
            act_text = f"Langkah {act.get('step', '?')}: {act.get('action', '')}"
            output = act.get('output', '')
            if output:
                # For read_file, show file info instead of content
                if "Membaca file yang ditemukan:" in act.get('action', ''):
                    # Extract file path from action
                    import re
                    match = re.search(r"file yang ditemukan: ([^\s]+)", act.get('action', ''))
                    if match:
                        filepath = match.group(1)
                        if os.path.exists(filepath):
                            try:
                                size = os.path.getsize(filepath)
                                lines = sum(1 for _ in open(filepath, 'r', encoding='utf-8', errors='ignore'))
                                act_text += f"\n     File: {filepath} ({size} bytes, {lines} lines)"
                            except:
                                act_text += f"\n     File: {filepath}"
                else:
                    # Show first line of output
                    first_line = output.strip().split('\n')[0][:60]
                    act_text += f"\n     Hasil: {first_line}"
            if act.get("details"):
                act_text += f"\n     Detail: {act['details'][:100]}"
            console.print(Text(act_text, style="dim"))
            console.print()
            
            # VERIFY phase
            console.print(Text("  ✅ VERIFY: Memverifikasi hasil", style="bold blue"))
            verify_text = result.get("verify", "")
            if verify_text:
                # Extract key verification info
                if "Tindakan berhasil menghasilkan output" in verify_text:
                    verify_text = "✓ Tindakan berhasil menghasilkan output yang dapat dianalisis"
                elif "Terdapat kesalahan" in verify_text:
                    verify_text = "⚠ Terdapat kesalahan atau pemblokiran saat menjalankan tindakan"
                elif "Tindakan tidak menghasilkan hasil yang diharapkan" in verify_text:
                    verify_text = "⚠ Tindakan tidak menghasilkan hasil yang diharapkan"
                else:
                    verify_text = verify_text.replace("VERIFY: ", "")
            console.print(Text(f"     {verify_text}", style="dim"))
            console.print()
            
            # REPORT phase
            console.print(Text("  📊 LAPORAN: Ringkasan dan langkah selanjutnya", style="bold blue"))
            report_text = result.get("report", "")
            if report_text:
                # Clean up report text for better display
                report_text = report_text.replace("REPORT: ", "")
                # Split into sentences for better readability
                sentences = report_text.split('. ')
                for sentence in sentences[:2]:  # Show first 2 sentences
                    if sentence.strip():
                        console.print(Text(f"     {sentence.strip()}", style="dim"))
            console.print()
            
            # Status and next step
            status = result.get("status", "unknown")
            next_step = result.get("next_step", "")
            status_style = "green" if status == "completed" else "yellow" if status == "failed" else "dim"
            console.print(Text(f"  Status: {status} | Langkah selanjutnya: {next_step}", style=status_style))
            console.print()
            
        except Exception as e:
            # SECURITY (Phase 1): solver errors can carry provider details.
            console.print(Text(f"  ✗ Gagal menjalankan solver: {redact_display(str(e))}", style="red"))
        return True, None, None

    # --- Autonomous Agent commands ---
    if cmd == "/auto":
        task = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not task:
            console.print(Text("  usage: /auto <complex task description>", style="dim"))
            console.print(Text("  contoh: /auto bikin REST API dengan auth, CRUD, dan testing", style="dim"))
            return True, None, None
        console.print(Text(f"  🤖 Autonomous mode: {task[:80]}", style="bold cyan"))
        console.print(Text("  Agent akan breakdown, kerjain, dan verifikasi sampai selesai.", style="dim"))
        console.print(Text("  Ketik /abort untuk stop.", style="dim"))
        console.print()
        try:
            agent = AutonomousAgent(
                invoke_fn=invoke_provider,
                execute_tool_fn=execute_tool,
                tools=SAFE_TOOLS,
                system_prompt=SYSTEM_PROMPT,
                max_subtask_rounds=8,
                render_fn=render_tool_call,
            )
            result = agent.run(task, selection.provider, selection.model, history)
            console.print()
            if result.success:
                console.print(Text(f"  ✅ {result.summary}", style="bold green"))
            else:
                console.print(Text(f"  ⚠ {result.summary}", style="yellow"))
            console.print(Text(f"  {result.subtasks_completed}/{result.subtasks_total} done · {result.total_rounds} rounds", style="dim"))
        except KeyboardInterrupt:
            abort_agent()
            console.print(Text("\n  ⏹ Aborted.", style="yellow"))
        except Exception as e:
            # SECURITY (Phase 1): agent errors can carry provider details.
            console.print(Text(f"  ✗ Agent error: {redact_display(str(e))}", style="red"))
        return True, None, None

    if cmd == "/abort":
        abort_agent()
        console.print(Text("  ⏹ Abort signal sent. Agent akan stop setelah step saat ini.", style="yellow"))
        return True, None, None

    if cmd == "/loop":
        task = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not task:
            console.print(Text("  usage: /loop <task to retry until success>", style="dim"))
            return True, None, None
        max_loops = 5
        console.print(Text(f"  🔄 Loop mode (max {max_loops}x): {task[:80]}", style="bold cyan"))
        for loop_idx in range(1, max_loops + 1):
            if is_aborted():
                break
            console.print(Text(f"\n  ═══ Loop {loop_idx}/{max_loops} ═══", style="cyan"))
            history.append({"role": "user", "content": f"[Loop {loop_idx}] {task}"})
            history, selection = run_agent_turn(history, selection, status_bar)
            # Check if it seems done
            last_content = ""
            for msg in reversed(history):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_content = msg["content"]
                    break
            if last_content and not any(kw in last_content.lower() for kw in ["error", "failed", "gagal", "tidak bisa", "couldn't"]):
                console.print(Text(f"\n  ✓ Succeeded on loop {loop_idx}.", style="green"))
                break
            if loop_idx == max_loops:
                console.print(Text(f"\n  ⚠ Max loops reached ({max_loops}).", style="yellow"))
        return True, None, None

    # --- v3.1: New slash commands ---
    if cmd == "/search":
        query = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not query:
            console.print(Text("  usage: /search <query>", style="dim"))
            return True, None, None
        result = web_search(query)
        console.print(Text(f"  🌐 {query}", style="bold dim"))
        console.print(Text(f"    {result[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/query":
        sql = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not sql:
            console.print(Text("  usage: /query <SQL>", style="dim"))
            return True, None, None
        result = db_query(sql)
        console.print(Text(f"  🗄 {sql[:60]}", style="bold dim"))
        console.print(Text(f"    {result[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/theme":
        if len(parts) > 1 and parts[1] in list_themes():
            theme_name = parts[1]
            save_theme_preference(theme_name)
            theme = get_theme(theme_name)
            # Apply colors to TUI
            set_theme_colors({
                "accent": theme.get("accent", "#5fb8c0"),
                "success": theme.get("success", "#6abf69"),
                "warning": theme.get("warning", "#d4a843"),
                "error": theme.get("error", "#d45555"),
                "dim": theme.get("dim", "#6a6a7a"),
                "border": theme.get("border", "#3a3a4a"),
                "prompt": theme.get("prompt", "#5fb8c0"),
            })
            console.print(Text(f"  ✓ Theme applied: {theme_name} — {theme.get('name', '')}", style="green"))
        else:
            for t in list_themes():
                theme = get_theme(t)
                marker = "●" if t == load_theme_preference() else "○"
                console.print(Text(f"  {marker} {t:<10}", style="cyan"), Text(f"  {theme.get('name', '')}", style="dim"))
            console.print(Text("  usage: /theme <dark|light|cyber|warm>", style="dim"))
        return True, None, None

    if cmd == "/verbose":
        new_state = toggle_verbose()
        console.print(Text(f"  verbose: {'ON' if new_state else 'OFF'}", style="cyan"))
        if new_state:
            console.print(Text("  THINK/ACT/PLAN logs akan ditampilkan", style="dim"))
        else:
            console.print(Text("  THINK/ACT/PLAN logs disembunyikan", style="dim"))
        return True, None, None

    if cmd == "/plugins":
        status = _plugin_manager.status() if _plugin_manager else {}
        if not status:
            console.print(Text("  no plugins loaded. Add .py files to ~/.opsora/plugins/", style="dim"))
        else:
            for name, info in status.items():
                console.print(Text(f"  ● {name}", style="cyan"), Text(f"  {info.get('description', '')}", style="dim"))
        return True, None, None

    if cmd == "/cost":
        # v3.1: real cost tracking
        cost_summary = _cost_tracker.session_total()
        console.print()
        console.print(Text(f"  Session: {len(history)} messages", style="dim"))
        console.print(Text(f"  Tokens:  {cost_summary['total_tokens']:,}", style="dim"))
        console.print(Text(f"  Cost:    ${cost_summary['total_cost']:.4f}", style="cyan"))
        console.print(Text(f"  Model:   {selection.provider}:{selection.model}", style="dim"))
        by_model = cost_summary.get("by_model", {})
        if by_model:
            console.print(Text(f"  Breakdown:", style="dim"))
            for m, data in by_model.items():
                console.print(Text(f"    {m}: {data['tokens']:,} tok · ${data['cost']:.4f}", style="dim"))
        console.print()
        return True, None, None

    # --- NVIDIA Services (NIM) ---
    if cmd == "/translate":
        text = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not text:
            console.print(Text("  usage: /translate <text to Indonesian>", style="dim"))
            console.print(Text("  usage: /translate en <Indonesian text>", style="dim"))
            return True, None, None
        # Detect if translating TO English
        target = "Indonesian"
        if parts[1].lower() == "en":
            target = "English"
            text = " ".join(parts[2:])
        console.print(Text(f"  🌐 Translating to {target}…", style="dim"))
        result = translate_text(text, target)
        console.print(Text(f"  → {result}", style="cyan"))
        return True, None, None

    if cmd == "/vision":
        path = parts[1] if len(parts) > 1 else ""
        prompt = " ".join(parts[2:]) if len(parts) > 2 else "Describe this image in detail. What do you see?"
        console.print(Text("  👁️ Analyzing…", style="dim"))
        if path:
            result = analyze_image(path, prompt)
        else:
            result = analyze_screenshot(prompt)
        console.print(Text(f"  {result[:3000]}", style="dim"))
        return True, None, None

    if cmd == "/safety":
        command = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not command:
            console.print(Text("  usage: /safety <shell command to check>", style="dim"))
            return True, None, None
        console.print(Text(f"  🛡️ Checking: {command[:60]}", style="dim"))
        result = check_command_safety(command)
        if result["safe"]:
            console.print(Text(f"  ✓ SAFE — {result['reason']}", style="green"))
        else:
            console.print(Text(f"  ✗ UNSAFE — {result['reason']}", style="red"))
        console.print(Text(f"  (checked by {result['model']})", style="dim"))
        return True, None, None

    if cmd == "/embed":
        text = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not text:
            console.print(Text("  usage: /embed <text to generate embedding>", style="dim"))
            return True, None, None
        console.print(Text("  🔍 Generating embedding…", style="dim"))
        vec = generate_embedding(text)
        if vec:
            console.print(Text(f"  ✓ Embedding: dim={len(vec)}, first 5: {vec[:5]}", style="green"))
        else:
            console.print(Text("  ✗ Embedding generation failed", style="red"))
        return True, None, None

    console.print(Text(f"  Unknown: {cmd}. Type /help", style="red"))
    return True, None, None


def _show_status(selection: Selection, status_bar: StatusBar) -> None:
    console.print()
    for prov in ["nvidia", "alibaba", "model_studio", "openai", "bedrock", "tokenhub", "opsora_api", "local"]:
        avail = is_provider_available(prov)
        icon = "●" if avail else "○"
        style = "green" if avail else "red dim"
        console.print(Text(f"  {icon} {prov}", style=style))
    console.print(Text(f"  mode: {get_approval_mode().value}  tools: {len(SAFE_TOOLS)}  ctx: {status_bar.context_pct}%", style="dim"))
    if _mcp_client:
        mcp_count = len(_mcp_client.get_all_tools())
        console.print(Text(f"  mcp: {mcp_count} tools", style="dim"))
    console.print()


def _show_models() -> None:
    console.print()
    for prov in ["nvidia", "alibaba", "model_studio", "openai", "bedrock", "tokenhub", "opsora_api", "local"]:
        models = PROVIDER_MODELS.get(prov, "")
        avail = is_provider_available(prov)
        icon = "●" if avail else "○"
        style = "green" if avail else "red dim"
        console.print(Text(f"  {icon} {prov}", style=style), Text(f"  {models}", style="dim"))
    console.print()


def _show_tools() -> None:
    console.print()
    for t in SAFE_TOOLS:
        name = t["function"]["name"]
        desc = t["function"]["description"][:50]
        console.print(Text(f"  {name}", style="cyan"), Text(f"  {desc}", style="dim"))
    if _mcp_client:
        for mt in _mcp_client.get_all_tools():
            console.print(Text(f"  {mt.name}", style="cyan"), Text(f"  mcp: {mt.description[:40]}", style="dim"))
    console.print()


# ============================================================================
# Slash-command completion
# ============================================================================

# Phase 1: moved out of main() to module level so the REPL's "/"
# autocomplete is importable/patchable (it was accidentally nested).
_SLASH_COMMANDS = [
    ("/help", "tampilin commands"),
    ("/status", "provider & tools"),
    ("/model", "ganti model"),
    ("/models", "list semua model"),
    ("/tools", "daftar tools"),
    ("/mode", "ganti approval mode"),
    ("/tree", "struktur folder"),
    ("/sessions", "list session"),
    ("/resume", "lanjutin session"),
    ("/save", "simpan session"),
    ("/new", "obrolan baru"),
    ("/run", "jalankan command"),
    ("/read", "baca file"),
    ("/diff", "bandingin 2 file"),
    ("/memory", "cari di memory"),
    ("/mcp", "MCP server status"),
    ("/agent", "spawn sub-agents"),
    ("/auto", "autonomous agent"),
    ("/loop", "retry sampai sukses"),
    ("/abort", "stop agent"),
    ("/solve", "problem solver"),
    ("/search", "web search"),
    ("/query", "SQLite query"),
    ("/theme", "ganti warna"),
    ("/plugins", "list plugins"),
    ("/cost", "session cost"),
    ("/verbose", "toggle verbose"),
    ("/review", "review code"),
    ("/deploy", "deploy project"),
    ("/explain", "explain code"),
    ("/refactor", "refactor code"),
    ("/test", "generate & run tests"),
    ("/fix-ci", "fix CI failures"),
    ("/translate", "translate EN↔ID"),
    ("/vision", "analyze screenshot"),
    ("/safety", "check command safety"),
    ("/embed", "generate embedding"),
    ("/copy", "copy ke clipboard"),
    ("/fork", "fork session"),
    ("/clear", "bersihin layar"),
    ("/exit", "keluar"),
]


def _available_model_completions() -> list[tuple[str, str]]:
    """Live list of (provider/model, provider) pairs for completion."""
    models = []
    for prov in ("alibaba", "nvidia", "tokenhub", "model_studio", "openai", "local"):
        if is_provider_available(prov):
            for m in PROVIDER_MODELS.get(prov, "").split(","):
                m = m.strip()
                if m:
                    models.append((f"{prov}/{m}", prov))
    return models


class SlashCompleter(Completer):
    """Smart auto-complete for slash commands, models, and themes."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        # Model sub-completion: "/model " shows providers, "/model alibaba/" shows models
        if text.lower().startswith("/model "):
            available_models = _available_model_completions()
            after = text[7:]  # after "/model "
            if "/" in after:
                # Show models for specific provider: "/model alibaba/"
                prov = after.split("/")[0]
                partial = after.split("/", 1)[1].lower() if len(after.split("/")) > 1 else ""
                for full, p in available_models:
                    if p == prov:
                        model_name = full.split("/", 1)[1]
                        if model_name.lower().startswith(partial):
                            yield Completion(
                                f"/model {full}",
                                start_position=-len(text),
                                display_meta=p,
                            )
            else:
                # Show providers: "/model "
                seen = set()
                for full, prov in available_models:
                    if prov not in seen and prov.startswith(after.lower()):
                        seen.add(prov)
                        yield Completion(
                            f"/model {prov}/",
                            start_position=-len(text),
                            display_meta=f"{len([m for m, p in available_models if p == prov])} models",
                        )
            return

        # Theme sub-completion: "/theme " shows theme names
        if text.lower().startswith("/theme "):
            after = text[7:].lower()
            for t in list_themes():
                if t.startswith(after):
                    theme = get_theme(t)
                    yield Completion(
                        f"/theme {t}",
                        start_position=-len(text),
                        display_meta=theme.get("name", ""),
                    )
            return

        # Default: command completion
        word = text.lower()
        for cmd, desc in _SLASH_COMMANDS:
            if cmd.startswith(word) or word == "/":
                yield Completion(
                    cmd,
                    start_position=-len(word),
                    display_meta=desc,
                )


# ============================================================================
# Main
# ============================================================================


def generate_session_id() -> str:
    """Generate a unique session id: 12 lowercase hex chars (uuid4-based).

    Phase 1 bugfix: the previous implementation hashed ``time.time()``, so two
    sessions started within the same clock tick produced identical ids.
    The 12-char hex format is kept for compatibility with ``sessions.id``.
    """
    return uuid.uuid4().hex[:12]


def main():
    global _mcp_client, selection

    # Load project context (opsora.md) at startup
    load_project_context()

    # --- Pipe input support: cat file.txt | opsora "analyze this" ---
    piped_input = ""
    if not sys.stdin.isatty():
        try:
            piped_input = sys.stdin.read().strip()[:10000]  # Cap at 10K chars
        except Exception:
            pass

    # --- Non-interactive mode: reuse full agent loop ---
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        if piped_input:
            prompt = f"{prompt}\n\n---\nInput from stdin:\n```\n{piped_input}\n```"
        selection = auto_select_model(prompt)
        history = [{"role": "user", "content": prompt}]
        status_bar = StatusBar(
            provider=selection.provider,
            model=selection.model,
            approval_mode=get_approval_mode(),
            cwd=str(WORKSPACE_ROOT),
            current_activity="Memproses permintaan..."
        )

        try:
            history, selection = run_agent_turn(history, selection, status_bar)
        except Exception as e:
            # SECURITY (Phase 1): redact provider/network error details.
            console.print(Text(f"Error: {redact_display(str(e))}", style="red"))
        return

    # --- Interactive mode ---
    console.clear()

    # Init MCP (lazy - only connect when needed)
    _mcp_client = MCPClient_v2()
    _mcp_client.load_config()
    # Don't auto-connect on startup - connect lazily when tools are needed
    # _mcp_client.connect_all()  # Commented out for faster startup

    # Initial state
    selection = Selection("alibaba", "qwen-plus")
    for prov in get_provider_order():
        if is_provider_available(prov):
            models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
            if models:
                selection = Selection(prov, models[0])
                break

    approval_mode = get_approval_mode()
    status_bar = StatusBar(
        provider=selection.provider,
        model=selection.model,
        approval_mode=approval_mode,
        cwd=str(WORKSPACE_ROOT),
        current_activity="Siap"
    )

    # Apply saved theme
    _saved_theme = load_theme_preference()
    if _saved_theme and _saved_theme != "dark":
        _td = get_theme(_saved_theme)
        set_theme_colors({
            "accent": _td.get("accent", "#5fb8c0"),
            "success": _td.get("success", "#6abf69"),
            "warning": _td.get("warning", "#d4a843"),
            "error": _td.get("error", "#d45555"),
            "dim": _td.get("dim", "#6a6a7a"),
            "border": _td.get("border", "#3a3a4a"),
        })

    # Welcome
    print_welcome(f"{selection.provider}:{selection.model}", len(SAFE_TOOLS), approval_mode)

    # Session (uuid4-based id — no timestamp collisions, Phase 1 bugfix)
    session_id = generate_session_id()
    history: list[dict] = []

    # Custom completer with descriptions — shows on "/"
    # (SlashCompleter lives at module level since Phase 1.)
    completer = SlashCompleter()

    while True:
        try:
            # Codex-style bordered input box
            prompt_text = codex_prompt(
                provider=selection.provider,
                model=selection.model,
                approval=get_approval_mode().value,
                ctx_pct=status_bar.context_pct,
                tokens=status_bar.session_tokens,
                completer=completer,
            ).strip()

            # Handle special results
            if prompt_text == "__INTERRUPT__":
                console.print(Text("\n  /exit untuk keluar", style="dim"))
                continue
            if prompt_text == "__EXIT__":
                break
            if not prompt_text:
                continue

            # Slash commands
            if prompt_text.startswith("/"):
                cont, new_sel, resume_id = handle_command(prompt_text, history, selection, status_bar, session_id)
                if new_sel:
                    selection = new_sel
                    status_bar.provider = new_sel.provider
                    status_bar.model = new_sel.model
                if resume_id:
                    session_data = load_session(resume_id)
                    if session_data:
                        history = session_data.messages
                        session_id = resume_id
                if not cont:
                    break
                continue

            # Agent turn
            history.append({"role": "user", "content": prompt_text})
            selection = auto_select_model(prompt_text)
            status_bar.provider = selection.provider
            status_bar.model = selection.model

            history, selection = run_agent_turn(history, selection, status_bar)

            # Auto-save session with AI-generated title
            if len(history) > 2:
                title = generate_session_title(history[:4], selection)
                save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)

            status_bar.session_tokens = sum(len(str(m.get("content", ""))) for m in history) // 4

        except KeyboardInterrupt:
            console.print("\n[dim]/exit untuk keluar[/dim]")
            continue
        except EOFError:
            break
        except Exception as e:
            # SECURITY (Phase 1): redact provider/network error details.
            console.print(Text(f"✗ {redact_display(str(e))}", style="red"))

    # Cleanup
    if _mcp_client:
        _mcp_client.disconnect_all()

    # Final save with auto-title
    if history:
        title = generate_session_title(history[:4], selection)
        save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)

    console.print("\n[dim]Dah.[/dim]")


if __name__ == "__main__":
    main()
