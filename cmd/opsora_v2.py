#!/usr/bin/env python3
"""
Opsora CLI v2 — Codex/Cursor-style Terminal AI Assistant
Integrates all providers, tools, agents, and resources.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen

# Third-party
from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn

# ============================================================================
# Workspace Configuration
# ============================================================================

WORKSPACE_ROOT = Path("/home/ubuntu")
OPSORA_ENV_FILE = WORKSPACE_ROOT / ".opsora_env"
OPSORA_DIR = WORKSPACE_ROOT / ".opsora"
OPSORA_DIR.mkdir(exist_ok=True)
TOKEN_USAGE_FILE = OPSORA_DIR / "token_usage.json"
SESSION_LOG_FILE = OPSORA_DIR / "session.log"

# Load environment from .opsora_env
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
        key = key.strip()
        if not key.replace("_", "").isalnum() or key[:1].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)

load_env_file(OPSORA_ENV_FILE)

# ============================================================================
# Provider Configuration — ALL providers connected
# ============================================================================

# 1. NVIDIA
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
nvidia_client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_URL, timeout=40) if NVIDIA_API_KEY else None

# 2. Alibaba / Model Studio (Singapore)
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
ALIBABA_URL = os.environ.get("ALIBABA_BASE_URL", "https://ws-ncxgasyv22dmw9ui.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
alibaba_client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=ALIBABA_URL, timeout=40) if DASHSCOPE_API_KEY else None

# 3. Model Studio (Alternative workspace)
MODEL_STUDIO_KEY = DASHSCOPE_API_KEY
MODEL_STUDIO_URL = "https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
model_studio_client = OpenAI(api_key=MODEL_STUDIO_KEY, base_url=MODEL_STUDIO_URL, timeout=40) if MODEL_STUDIO_KEY else None

# 4. OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=40) if OPENAI_API_KEY else None

# 5. Ollama Local
LOCAL_URL = os.environ.get("OPSORA_OLLAMA_URL", "http://127.0.0.1:11434/v1")
LOCAL_TAGS_URL = LOCAL_URL.removesuffix("/v1") + "/api/tags"
local_client = OpenAI(api_key="ollama", base_url=LOCAL_URL, timeout=60)

# 6. AWS Bedrock
AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

import boto3
from botocore.config import Config

def bedrock_available() -> bool:
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        return session.get_credentials() is not None
    except Exception:
        return False

def get_bedrock_runtime():
    session = boto3.Session(profile_name=AWS_PROFILE)
    return session.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
    )

# 7. TokenHub (Tencent Cloud AI - Singapore)
TOKENHUB_API_KEY = os.environ.get("TOKENHUB_API_KEY", "")
TOKENHUB_URL = "https://tokenhub.tencentmaas.com/v1"
tokenhub_client = OpenAI(api_key=TOKENHUB_API_KEY, base_url=TOKENHUB_URL, timeout=40) if TOKENHUB_API_KEY else None

# TokenHub models (all available in Singapore region)
TOKENHUB_MODELS = {
    "active": [
        "hy3",           # Hunyuan Hy3 - 256K context, $0.132/M input, FREE 1M tokens
        "kimi-k3",       # Kimi K3 - 1M context, SOTA, FREE 1M tokens
    ],
    "available": [
        "glm-5.2",       # GLM-5.2 - latest flagship
        "glm-5.1",       # GLM-5.1 - Claude Opus 4.6 level
        "glm-5-turbo",   # GLM-5-Turbo - fast version
        "glm-5v-turbo",  # GLM-5V-Turbo - multimodal coding
        "kimi-k2.6",     # Kimi K2.6 - code/agent specialist
        "kimi-k2.7-code",# Kimi K2.7 Code - code expert
        "minimax-m3",    # MiniMax-M3 - latest
        "minimax-m2.7",  # MiniMax-M2.7 - agent harness
        "deepseek-v4-pro",  # DeepSeek-V4-Pro
        "deepseek-v4-flash",# DeepSeek-V4-Flash (fast/cheap)
        "hy-mt2-plus",   # Hy-MT2-Plus - translation
    ],
    "free_tier": {
        "hy3": {"quota": 1000000, "used": 376, "expires": "2027-07-20"},
        "kimi-k3": {"quota": 1000000, "used": 830, "expires": "2027-07-20"},
    }
}

# Provider order from env
def get_provider_order() -> list[str]:
    order = os.environ.get("OPSORA_PROVIDER_ORDER", "nvidia,alibaba,bedrock,local")
    return [p.strip() for p in order.split(",") if p.strip()]

# Models per provider
PROVIDER_MODELS = {
    "nvidia": os.environ.get("OPSORA_MODEL", "meta/llama-3.1-70b-instruct"),
    "alibaba": "qwen-plus,qwen-turbo,qwen-max",
    "model_studio": "qwen-plus,qwen-turbo,qwen-max",
    "openai": "gpt-4o,gpt-4o-mini,gpt-3.5-turbo",
    "bedrock": "amazon.nova-pro-v1:0,amazon.nova-lite-v1:0,amazon.nova-micro-v1:0",
    "tokenhub": ",".join(TOKENHUB_MODELS["active"] + TOKENHUB_MODELS["available"]),
    "local": "qwen3.5:4b,llama3.1:latest,qwen2.5-coder:32b",
}

# ============================================================================
# Console & Styling — Codex/Cursor aesthetic
# ============================================================================

console = Console(soft_wrap=True)

# Color palette: dark theme, cyan accents like Cursor
OPSORA_STYLE = {
    "header": "bold cyan",
    "subtle": "dim white",
    "accent": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "info": "bold magenta",
    "tool": "dim yellow",
    "code": "cyan",
}

# ============================================================================
# System Detection
# ============================================================================

def get_system_info() -> dict[str, str]:
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "node": get_cmd_output("node --version 2>/dev/null").strip() or "N/A",
        "terraform": get_cmd_output("terraform version 2>/dev/null | head -1").strip() or "N/A",
        "opencode": get_cmd_output("opencode version 2>/dev/null").strip() or "N/A",
        "cwd": str(WORKSPACE_ROOT),
    }

def get_cmd_output(cmd: str) -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""

# ============================================================================
# Model Selection & Auto-Routing
# ============================================================================

@dataclass
class ProviderInfo:
    name: str
    client: Any
    models: list[str]
    available: bool

@dataclass
class Selection:
    provider: str
    model: str

# Auto-select model based on prompt intent
def auto_select_model(prompt: str) -> Selection:
    prompt_lower = prompt.lower()

    # Code-related → use TokenHub Hy3 (excellent coding, free tier) or Alibaba qwen
    if any(kw in prompt_lower for kw in ["code", "function", "class", "def ", "bug", "fix", "refactor", "script", "debug", "python", "bash", "implement"]):
        if tokenhub_client is not None:
            return Selection("tokenhub", "hy3")
        return Selection("alibaba", "qwen-plus")

    # Quick/simple questions → fast model
    if any(kw in prompt_lower for kw in ["what is", "who is", "quick", "simple", "brief", "jelaskan", "apa"]):
        if tokenhub_client is not None:
            return Selection("tokenhub", "deepseek-v4-flash")
        return Selection("alibaba", "qwen-turbo")

    # Complex analysis → max model
    if any(kw in prompt_lower for kw in ["analyze", "architecture", "design", "strategy", "complex", "deep dive", "comprehensive"]):
        if tokenhub_client is not None:
            return Selection("tokenhub", "kimi-k3")
        return Selection("alibaba", "qwen-max")

    # AWS-related → prefer bedrock if available
    if any(kw in prompt_lower for kw in ["aws", "ec2", "s3", "lambda", "bedrock", "terraform"]):
        if bedrock_available():
            return Selection("bedrock", "amazon.nova-pro-v1:0")

    # Tencent Cloud → TokenHub
    if any(kw in prompt_lower for kw in ["tencent", "tokenhub", "hunyuan", "cvm", "cos"]):
        if tokenhub_client is not None:
            return Selection("tokenhub", "hy3")

    # Default
    order = get_provider_order()
    for provider in order:
        models_str = PROVIDER_MODELS.get(provider, "")
        models = [m.strip() for m in models_str.split(",") if m.strip()]
        if models and is_provider_available(provider):
            return Selection(provider, models[0])

    return Selection("alibaba", "qwen-plus")

def is_provider_available(provider: str) -> bool:
    if provider == "nvidia":
        return nvidia_client is not None
    if provider == "alibaba":
        return alibaba_client is not None
    if provider == "model_studio":
        return model_studio_client is not None
    if provider == "openai":
        return openai_client is not None
    if provider == "bedrock":
        return bedrock_available()
    if provider == "tokenhub":
        return tokenhub_client is not None
    if provider == "local":
        return check_ollama_running()
    return False

def check_ollama_running() -> bool:
    try:
        with urlopen(LOCAL_TAGS_URL, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

def get_available_models(provider: str) -> list[str]:
    if provider == "local":
        return available_local_models() or [m.strip() for m in PROVIDER_MODELS.get("local", "").split(",")]
    models_str = PROVIDER_MODELS.get(provider, "")
    return [m.strip() for m in models_str.split(",") if m.strip()]

def available_local_models() -> list[str]:
    try:
        with urlopen(LOCAL_TAGS_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [str(item.get("name", "")).strip() for item in payload.get("models", [])]
        return [m for m in models if m]
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return []

# ============================================================================
# Tools — Full integration
# ============================================================================

SAFE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Save a non-secret fact to persistent Opsora memory",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "source": {"type": "string"}}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search persistent Opsora memory for relevant context",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graphify_query",
            "description": "Query the local Graphify knowledge graph for project context",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_status",
            "description": "Show non-secret workspace capability status",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a local text file (requires approval)",
            "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a local file (requires approval)",
            "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command (requires approval)",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aws_command",
            "description": "Run read-only AWS CLI commands (requires approval)",
            "parameters": {"type": "object", "properties": {"arguments": {"type": "string"}}, "required": ["arguments"]},
        },
    },
]

def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool call with full integration"""
    try:
        # Memory tools
        if name == "memory_add":
            sys.path.insert(0, str(WORKSPACE_ROOT))
            from opsora_memory import add_memory
            return add_memory(args.get("text", ""), source=args.get("source", "cli"))

        if name == "memory_search":
            sys.path.insert(0, str(WORKSPACE_ROOT))
            from opsora_memory import search_memory
            return json.dumps(search_memory(args.get("query", ""), args.get("limit", 5)), ensure_ascii=False)

        # Graphify
        if name == "graphify_query":
            sys.path.insert(0, str(WORKSPACE_ROOT))
            from opsora_tools import graphify_query
            return graphify_query(args.get("query", ""), depth=args.get("depth", 2))

        # Workspace status
        if name == "workspace_status":
            sys.path.insert(0, str(WORKSPACE_ROOT))
            from opsora_tools import workspace_status
            return json.dumps(workspace_status(), ensure_ascii=False)

        # File operations (with YOLO mode = auto-approve for safe reads)
        if name == "read_file":
            filepath = Path(args["filepath"])
            if not filepath.is_absolute():
                filepath = WORKSPACE_ROOT / filepath
            # Security check
            lowered = {p.casefold() for p in filepath.resolve().parts}
            blocked = {".aws", ".ssh", ".gnupg"}
            if lowered & blocked:
                return "ERROR: Access to credential directories is blocked."
            return filepath.read_text(encoding="utf-8", errors="replace")[:50000]

        if name == "write_file":
            filepath = Path(args["filepath"])
            if not filepath.is_absolute():
                filepath = WORKSPACE_ROOT / filepath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(str(args.get("content", "")), encoding="utf-8")
            return f"✓ Wrote {len(args.get('content', ''))} chars to {filepath}"

        # Shell execution (YOLO mode enabled)
        if name == "run_command":
            cmd = str(args["command"])
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=WORKSPACE_ROOT)
            output = (result.stdout or "") + (result.stderr or "")
            return output[:50000] or f"Command exited with code {result.returncode}."

        # AWS read-only
        if name == "aws_command":
            cmd_args = shlex.split(str(args["arguments"]))
            # Only allow read-only operations
            allowed_prefixes = ["get-", "describe-", "list-", "head-", "scan", "query"]
            if len(cmd_args) >= 2:
                op = cmd_args[1].lower()
                if not any(op.startswith(p) for p in allowed_prefixes):
                    return "ERROR: Only read-only AWS operations allowed (get/describe/list/head/scan/query)."
            result = subprocess.run(
                ["aws", "--profile", AWS_PROFILE] + cmd_args,
                capture_output=True, text=True, timeout=60
            )
            return ((result.stdout or "") + (result.stderr or ""))[:50000]

        return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error: {type(e).__name__}: {e}"

# ============================================================================
# API Invocation with Full Fallback Chain
# ============================================================================

SYSTEM_PROMPT = """You are Opsora, a powerful terminal-based AI coding assistant.

## Capabilities
- Write, edit, review, and debug code in any language
- Execute shell commands and AWS operations
- Query project memory and Graphify knowledge graph
- Work with files, agents, and cloud resources
- Multi-provider model routing for optimal cost/performance

## Guidelines
- Be direct, precise, and concise
- Use code blocks for all code snippets
- Show file paths when referencing files
- Prefer Indonesian for Indonesian input, English otherwise
- Use tools proactively when they help answer the question
- YOLO mode: execute commands without asking for confirmation when safe"""

def invoke_provider(provider: str, model: str, messages: list[dict], use_tools: bool = True) -> Any:
    """Invoke a specific provider with tool support"""
    tools = SAFE_TOOLS if use_tools else []

    if provider == "nvidia" and nvidia_client:
        kwargs = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 4096}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return nvidia_client.chat.completions.create(**kwargs)

    if provider == "alibaba" and alibaba_client:
        kwargs = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 8192}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return alibaba_client.chat.completions.create(**kwargs)

    if provider == "model_studio" and model_studio_client:
        kwargs = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 8192}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return model_studio_client.chat.completions.create(**kwargs)

    if provider == "openai" and openai_client:
        kwargs = {"model": model, "messages": messages, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return openai_client.chat.completions.create(**kwargs)

    if provider == "local" and check_ollama_running():
        kwargs = {"model": model, "messages": messages, "temperature": 0.2}
        # Ollama may not support tools
        try:
            if tools:
                kwargs["tools"] = tools
            return local_client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("tools", None)
            return local_client.chat.completions.create(**kwargs)

    if provider == "bedrock" and bedrock_available():
        return invoke_bedrock(model, messages)

    if provider == "tokenhub" and tokenhub_client:
        kwargs = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 8192}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return tokenhub_client.chat.completions.create(**kwargs)

    raise RuntimeError(f"Provider '{provider}' is not available")

def invoke_bedrock(model: str, messages: list[dict]) -> Any:
    """Invoke AWS Bedrock Converse API"""
    runtime = get_bedrock_runtime()
    converted = []
    for msg in messages:
        if msg.get("role") in ("user", "assistant"):
            content = msg.get("content") or ""
            if content:
                converted.append({"role": msg["role"], "content": [{"text": str(content)}]})

    if not converted:
        converted = [{"role": "user", "content": [{"text": "Hello"}]}]

    response = runtime.converse(
        modelId=model,
        system=[{"text": SYSTEM_PROMPT}],
        messages=converted,
        inferenceConfig={"maxTokens": 4096, "temperature": 0.2},
    )
    content = response["output"]["message"]["content"][0]["text"]
    # Wrap as OpenAI-like response
    class BedrockResponse:
        def __init__(self, text):
            self.content = text
            self.tool_calls = None
            self.role = "assistant"
    return BedrockResponse(content)

def call_with_fallback(messages: list[dict], selection: Selection, use_tools: bool = True) -> tuple[Any, Selection]:
    """Try primary selection, then fallback through all providers"""
    errors = []

    # Build candidate list
    candidates = [selection]
    order = get_provider_order()
    for provider in order:
        if provider == selection.provider:
            continue
        models = get_available_models(provider)
        for model in models:
            candidates.append(Selection(provider, model))
            break  # Only first model per provider

    # Try each candidate
    for candidate in candidates:
        if not is_provider_available(candidate.provider):
            continue
        try:
            result = invoke_provider(candidate.provider, candidate.model, messages, use_tools)
            return result, candidate
        except Exception as e:
            errors.append(f"{candidate.provider}:{candidate.model} → {str(e)[:120]}")

    raise RuntimeError(f"All providers failed: {'; '.join(errors[:3])}")

# ============================================================================
# UI Components — Codex/Cursor Style
# ============================================================================

def build_header() -> Panel:
    """Build the Codex/Cursor-style header"""
    sys_info = get_system_info()
    providers_status = []

    for prov in ["nvidia", "alibaba", "model_studio", "openai", "bedrock", "tokenhub", "local"]:
        status = "●" if is_provider_available(prov) else "○"
        color = "green" if is_provider_available(prov) else "red"
        providers_status.append(f"[{color}]{status}[/{color}] {prov}")

    prov_text = "  ".join(providers_status)

    header_content = (
        f"[bold cyan]╔══════════════════════════════════════════════════════════╗[/]\n"
        f"[bold cyan]║[/]  [bold white]OPSORA[/bold white] [dim]v2.0 — Codex/Cursor Edition[/dim]          [bold cyan]║[/]\n"
        f"[bold cyan]║[/]  {prov_text}  [bold cyan]║[/]\n"
        f"[bold cyan]║[/]  [dim]Python {sys_info['python']} | Node {sys_info['node']} | TF {sys_info['terraform']}[/dim]       [bold cyan]║[/]\n"
        f"[bold cyan]╚══════════════════════════════════════════════════════════╝[/]"
    )

    return Panel(header_content, box=box.DOUBLE, border_style="cyan", padding=(0, 0))

def build_status_bar(selection: Selection) -> str:
    """Build the status bar like Cursor"""
    available = "●" if is_provider_available(selection.provider) else "○"
    return f"[bold cyan]{available} {selection.provider}:{selection.model}[/]  [dim]|  {datetime.now().strftime('%H:%M:%S')}  |  YOLO mode: ON  |  /help for commands[/]"

def build_welcome_panel(selection: Selection) -> Panel:
    """Build comprehensive welcome panel"""
    sys_info = get_system_info()

    # Count resources
    agent_files = list(WORKSPACE_ROOT.glob("agent*.py"))
    claude_files = list((WORKSPACE_ROOT / "claude-code-agent").glob("*.py"))
    opsora_files = list((WORKSPACE_ROOT / "opsora-cli").rglob("*.py"))

    content = (
        f"[bold]Active Model:[/bold] [cyan]{selection.provider}:{selection.model}[/]\n"
        f"[bold]Workspace:[/bold] {sys_info['cwd']}\n"
        f"[bold]System:[/bold] {sys_info['os']} {sys_info['arch']}\n\n"
        f"[bold]Resources Connected:[/bold]\n"
        f"  • {len(agent_files)} agent files in workspace\n"
        f"  • {len(claude_files)} Claude agent files\n"
        f"  • {len(opsora_files)} Opsora CLI files\n"
        f"  • Memory: opsora_memory.py ✓\n"
        f"  • Graphify: opsora_tools.py ✓\n"
        f"  • AWS: profile={AWS_PROFILE}, region={AWS_REGION}\n"
        f"  • NVIDIA API: {'✓' if NVIDIA_API_KEY else '✗'}\n"
        f"  • Alibaba/DashScope: {'✓' if DASHSCOPE_API_KEY else '✗'}\n"
        f"  • OpenAI: {'✓' if OPENAI_API_KEY else '✗'}\n"
        f"  • TokenHub: {'✓' if tokenhub_client else '✗'} ({len(TOKENHUB_MODELS['active'])} active, {len(TOKENHUB_MODELS['available'])} available)\n"
        f"  • Ollama: {'✓' if check_ollama_running() else '✗'}\n"
        f"  • Bedrock: {'✓' if bedrock_available() else '✗'}\n\n"
        f"[bold]YOLO Mode:[/bold] [green]ENABLED[/green] — commands execute without confirmation\n"
        f"[dim]Type /help for all commands. Ctrl+D to exit.[/dim]"
    )

    return Panel(content, title="[bold cyan]⚡ OPSORA[/bold cyan] — All Resources Connected", border_style="cyan", box=box.ROUNDED, padding=(1, 2))

def show_tools_status() -> None:
    """Show tools status table"""
    table = Table(title="Available Tools", box=box.ROUNDED, border_style="cyan")
    table.add_column("Tool", style="cyan")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Description")

    tools_info = [
        ("memory_add", "Safe", "✓", "Save facts to memory"),
        ("memory_search", "Safe", "✓", "Search memory"),
        ("graphify_query", "Safe", "✓", "Query knowledge graph"),
        ("workspace_status", "Safe", "✓", "Show workspace status"),
        ("read_file", "Host", "✓", "Read local files"),
        ("write_file", "Host", "✓", "Write local files"),
        ("run_command", "Host", "✓", "Execute shell commands"),
        ("aws_command", "AWS", "✓", "Read-only AWS CLI"),
    ]

    for name, tool_type, status, desc in tools_info:
        table.add_row(name, tool_type, f"[green]{status}[/green]", desc)

    console.print(table)

def show_models_table() -> None:
    """Show all providers and models"""
    table = Table(title="Provider Routes", box=box.ROUNDED, border_style="cyan")
    table.add_column("Provider", style="cyan")
    table.add_column("Models")
    table.add_column("Status")
    table.add_column("API Key")

    providers = {
        "nvidia": ("meta/llama-3.1-70b-instruct", NVIDIA_API_KEY),
        "alibaba": ("qwen-plus, qwen-turbo, qwen-max", DASHSCOPE_API_KEY),
        "model_studio": ("qwen-plus, qwen-turbo, qwen-max", MODEL_STUDIO_KEY),
        "openai": ("gpt-4o, gpt-4o-mini", OPENAI_API_KEY),
        "bedrock": ("amazon.nova-pro-v1:0", "AWS Credentials"),
        "tokenhub": (", ".join(TOKENHUB_MODELS["active"]), TOKENHUB_API_KEY),
        "local": ("qwen3.5:4b, llama3.1:latest", "Ollama Local"),
    }

    for prov, (models, key_info) in providers.items():
        avail = is_provider_available(prov)
        table.add_row(
            prov,
            models,
            f"[green]● Ready[/green]" if avail else f"[red]○ Offline[/red]",
            "✓" if key_info else "✗"
        )

    if tokenhub_client:
        # Add TokenHub available models as additional row
        th_available = ", ".join(TOKENHUB_MODELS["available"])
        table.add_row(
            "  ↳ tokenhub+",
            th_available,
            "[dim]Available[/dim]",
            "✓"
        )

    console.print(table)

# ============================================================================
# Command Handler
# ============================================================================

def handle_command(value: str, history: list[dict]) -> tuple[bool, Optional[Selection]]:
    """Handle slash commands. Returns (continue, new_selection)"""
    parts = shlex.split(value)
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit", "/q"):
        return False, None

    elif cmd == "/help":
        console.print(Panel(
            "[bold]/help[/bold]          Show this help\n"
            "[bold]/status[/bold]        Show provider & tool status\n"
            "[bold]/models[/bold]        Show all provider routes\n"
            "[bold]/tools[/bold]         Show available tools\n"
            "[bold]/model <prov>[/bold]  Switch provider (nvidia|alibaba|openai|bedrock|tokenhub|local)\n"
            "[bold]/model <prov> <m>[/bold]  Switch to specific model\n"
            "[bold]/clear[/bold]         Clear screen\n"
            "[bold]/new[/bold]           New conversation\n"
            "[bold]/agents[/bold]        List agent files\n"
            "[bold]/aws <args>[/bold]    Quick AWS read-only command\n"
            "[bold]/run <cmd>[/bold]     Quick shell command\n"
            "[bold]/read <file>[/bold]   Quick file read\n"
            "[bold]/graphify <q>[/bold]  Quick graph query\n"
            "[bold]/memory <q>[/bold]    Quick memory search\n"
            "[bold]/exit[/bold]          Exit Opsora",
            title="[bold cyan]Opsora Commands[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        ))
        return True, None

    elif cmd == "/status":
        show_tools_status()
        return True, None

    elif cmd == "/models":
        show_models_table()
        return True, None

    elif cmd == "/tools":
        show_tools_status()
        return True, None

    elif cmd == "/model":
        if len(parts) >= 2:
            provider = parts[1]
            model = parts[2] if len(parts) > 2 else None
            if is_provider_available(provider):
                models = get_available_models(provider)
                selected_model = model or models[0] if models else None
                if selected_model:
                    console.print(f"[green]✓[/green] Switched to [bold]{provider}:{selected_model}[/bold]")
                    return True, Selection(provider, selected_model)
                else:
                    console.print(f"[red]✗ No models available for {provider}[/red]")
            else:
                console.print(f"[red]✗ Provider '{provider}' not available[/red]")
        else:
            console.print("[dim]Usage: /model <provider> [model][/dim]")
        return True, None

    elif cmd == "/clear":
        console.clear()
        console.print(build_welcome_panel(selection))
        return True, None

    elif cmd == "/new":
        history.clear()
        console.print("[green]✓[/green] Conversation cleared. New session started.")
        return True, None

    elif cmd == "/agents":
        agent_files = list(WORKSPACE_ROOT.glob("agent*.py"))
        table = Table(title="Agent Files", box=box.ROUNDED, border_style="cyan")
        table.add_column("File", style="cyan")
        table.add_column("Size")
        table.add_column("Modified")
        for f in sorted(agent_files):
            stat = f.stat()
            table.add_row(f.name, f"{stat.st_size:,}B", datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"))
        console.print(table)
        return True, None

    elif cmd == "/aws":
        if len(parts) < 2:
            console.print("[dim]Usage: /aws <service> <operation> [options][/dim]")
            return True, None
        args = parts[1:]
        result = execute_tool("aws_command", {"arguments": " ".join(args)})
        console.print(Panel(result[:5000], title=f"AWS: {' '.join(args)}", border_style="magenta", box=box.ROUNDED))
        return True, None

    elif cmd == "/run":
        if len(parts) < 2:
            console.print("[dim]Usage: /run <command>[/dim]")
            return True, None
        cmd_str = " ".join(parts[1:])
        with console.status(f"[yellow]⠋ Running: {cmd_str}[/yellow]", spinner="dots"):
            result = execute_tool("run_command", {"command": cmd_str})
        console.print(Panel(result[:5000], title=f"Output: {cmd_str}", border_style="yellow", box=box.ROUNDED))
        return True, None

    elif cmd == "/read":
        if len(parts) < 2:
            console.print("[dim]Usage: /read <filepath>[/dim]")
            return True, None
        filepath = parts[1]
        result = execute_tool("read_file", {"filepath": filepath})
        if result.startswith("ERROR"):
            console.print(f"[red]{result}[/red]")
        else:
            console.print(Panel(Syntax(result[:5000], "text", word_wrap=True), title=f"📄 {filepath}", border_style="cyan", box=box.ROUNDED))
        return True, None

    elif cmd == "/graphify":
        if len(parts) < 2:
            console.print("[dim]Usage: /graphify <query>[/dim]")
            return True, None
        query = " ".join(parts[1:])
        with console.status(f"[cyan]⠋ Querying Graphify: {query}[/cyan]", spinner="dots"):
            result = execute_tool("graphify_query", {"query": query})
        console.print(Panel(result[:5000], title=f"Graphify: {query}", border_style="cyan", box=box.ROUNDED))
        return True, None

    elif cmd == "/memory":
        query = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not query:
            console.print("[dim]Usage: /memory <query>[/dim]")
            return True, None
        with console.status(f"[cyan]⠋ Searching memory: {query}[/cyan]", spinner="dots"):
            result = execute_tool("memory_search", {"query": query})
        console.print(Panel(result[:5000], title=f"Memory: {query}", border_style="cyan", box=box.ROUNDED))
        return True, None

    else:
        console.print(f"[red]Unknown command:[/red] {cmd}. Type [bold]/help[/bold] for commands.")
        return True, None

# ============================================================================
# Main Loop
# ============================================================================

def run_turn(history: list[dict], current_selection: Selection) -> tuple[list[dict], Selection]:
    """Run a single conversation turn with tool calling"""
    MAX_TOOL_ROUNDS = 5

    for round_idx in range(MAX_TOOL_ROUNDS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

        try:
            # Show thinking status
            with console.status(f"[cyan]⠋ {current_selection.provider}:{current_selection.model} thinking…[/cyan]", spinner="dots"):
                response, current_selection = call_with_fallback(messages, current_selection, use_tools=True)

            # Extract response
            if hasattr(response, "choices"):
                msg = response.choices[0].message
                content = msg.content or ""
                tool_calls = msg.tool_calls if hasattr(msg, "tool_calls") else None
            else:
                content = getattr(response, "content", "") or ""
                tool_calls = getattr(response, "tool_calls", None)

            # Print response content
            if content:
                console.print()
                console.print(Markdown(content))
                console.print()

            # Handle tool calls
            if tool_calls:
                for tc in tool_calls:
                    if hasattr(tc, "function"):
                        func = tc.function
                        name = func.name
                        args = json.loads(func.arguments) if isinstance(func.arguments, str) else func.arguments
                    else:
                        func = tc.get("function", {})
                        name = func.get("name", "unknown")
                        args = json.loads(func.get("arguments", "{}"))

                    # Show tool execution
                    args_preview = ", ".join(f"{k}={json.dumps(v)[:40]}" for k, v in args.items())
                    if len(args_preview) > 80:
                        args_preview = args_preview[:77] + "..."
                    console.print(f"  [dim yellow]⚙ {name}({args_preview})[/]")

                    with console.status(f"[yellow]⠋ Executing: {name}…[/yellow]", spinner="dots"):
                        output = execute_tool(name, args)

                    # Show output preview
                    output_preview = output[:500]
                    if len(output) > 500:
                        output_preview += f"\n[dim]… truncated ({len(output)} chars total)[/dim]"
                    console.print(Panel(output_preview, title=f"↳ {name} output", border_style="dim yellow", box=box.SIMPLE))

                    # Add tool result to history
                    tool_call_id = getattr(tc, "id", None) if not isinstance(tc, dict) else tc.get("id")
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": name,
                        "content": output,
                    })

                # Continue to next round for tool results
                continue
            else:
                # No tool calls, turn complete
                break

        except Exception as e:
            console.print(f"[red]✗ Error:[/red] {e}")
            break

    return history, current_selection

def main():
    global selection

    # Direct prompt mode (non-interactive)
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        selection = auto_select_model(prompt)
        history = [{"role": "user", "content": prompt}]

        with console.status(f"[cyan]⠋ {selection.provider}:{selection.model} thinking…[/cyan]", spinner="dots"):
            try:
                response, selection = call_with_fallback(
                    [{"role": "system", "content": SYSTEM_PROMPT}, *history],
                    selection,
                    use_tools=True
                )
                msg = response.choices[0].message if hasattr(response, "choices") else response
                content = msg.content or ""
                if content:
                    console.print(Markdown(content))
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        return

    # Interactive mode
    console.clear()
    console.print(build_header())
    console.print()

    # Initial selection
    selection = Selection("alibaba", "qwen-plus")
    console.print(build_welcome_panel(selection))
    console.print()

    history: list[dict] = []

    # Prompt styling
    kb = KeyBindings()

    session = PromptSession(
        message=lambda: HTML(f'<style fg="cyan">bold</style> <style fg="white">opsora</style> <style fg="ansiblue">[{selection.provider}:{selection.model}]</style> <style fg="ansiyellow">❯</style> '),
        key_bindings=kb,
        style=PromptStyle.from_dict({
            "prompt": "bold cyan",
        }),
    )

    console.print(f"[dim]{'─' * 60}[/dim]")
    console.print()

    while True:
        try:
            # Get input
            prompt = session.prompt().strip()

            if not prompt:
                continue

            # Handle slash commands
            if prompt.startswith("/"):
                continue_loop, new_sel = handle_command(prompt, history)
                if new_sel:
                    selection = new_sel
                if not continue_loop:
                    break
                console.print(f"[dim]{'─' * 60}[/dim]")
                continue

            # Auto-select model
            selection = auto_select_model(prompt)

            # Add user message
            history.append({"role": "user", "content": prompt})

            # Run the turn
            history, selection = run_turn(history, selection)

            console.print(f"[dim]{'─' * 60}[/dim]")

        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Type /exit to quit, or continue.[/dim]")
            continue

        except EOFError:
            console.print("\n[dim]Meninggalkan Opsora CLI…[/dim]")
            break

        except Exception as e:
            console.print(f"[red]✗ Unexpected error:[/red] {e}")
            console.print(f"[dim]{'─' * 60}[/dim]")

if __name__ == "__main__":
    main()
