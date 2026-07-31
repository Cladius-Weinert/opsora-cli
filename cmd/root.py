#!/usr/bin/env python3
"""Terminal-first Opsora client with safe tools and provider fallback."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import boto3
from botocore.config import Config
try:
    from openai import OpenAI
except (ImportError, Exception):
    from openai_lite import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


WORKSPACE_ROOT = Path("/root")
_CMD_DIR = str(Path(__file__).resolve().parent)
if _CMD_DIR not in sys.path:
    sys.path.insert(0, _CMD_DIR)
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from opsora_memory import add_memory, memory_stats, search_memory
from opsora_tools import graphify_query, workspace_status


console = Console()
OPSORA_ENV = WORKSPACE_ROOT / ".opsora_env"
LOCAL_URL = os.environ.get("OPSORA_OLLAMA_URL", "http://127.0.0.1:11434/v1")
LOCAL_TAGS_URL = LOCAL_URL.removesuffix("/v1") + "/api/tags"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
ALIBABA_URL_DEFAULT = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
MAX_TOOL_ROUNDS = 4
MAX_TOOL_OUTPUT = 12_000
SECRET_ENV_NAMES = (
    "NVIDIA_API_KEY",
    "DASHSCOPE_API_KEY",
    "ALIBABA_API_KEY",
    "ALIYUN_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "OPENAI_API_KEY",
)
SENSITIVE_PATH_PARTS = {".aws", ".ssh", ".gnupg", ".config/gcloud"}
SENSITIVE_FILE_NAMES = {".env", ".opsora_env", "credentials", "id_rsa", "id_ed25519"}
SENSITIVE_FILE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
AWS_READ_ONLY_PREFIXES = ("get-", "describe-", "list-", "head-", "batch-get-", "scan", "query", "lookup-")
AWS_READ_ONLY_SPECIAL_CASES = {("s3", "ls")}
AWS_READ_ONLY_DENYLIST = {"get-object", "select-object-content"}
AWS_BLOCKED_GLOBAL_OPTIONS = {"--profile", "--endpoint-url", "--no-sign-request", "--cli-auto-prompt"}


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


def unique_models(models: list[str]) -> list[str]:
    return list(dict.fromkeys(model for model in models if model))


def configured_cloud_models() -> list[str]:
    explicit = os.environ.get("OPSORA_CLOUD_MODELS")
    if explicit:
        return unique_models(csv_env("OPSORA_CLOUD_MODELS", ""))
    primary = os.environ.get("OPSORA_MODEL")
    defaults = csv_env(
        "OPSORA_NVIDIA_DEFAULT_MODELS",
        "meta/llama-3.1-70b-instruct,meta/llama-3.3-70b-instruct,"
        "mistralai/ministral-14b-instruct-2512,deepseek-ai/deepseek-v4-flash",
    )
    return unique_models(([primary] if primary else []) + defaults)


load_export_file(OPSORA_ENV)

NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY")
ALIBABA_KEY = (
    os.environ.get("DASHSCOPE_API_KEY")
    or os.environ.get("ALIBABA_API_KEY")
    or os.environ.get("ALIYUN_API_KEY")
)
ALIBABA_URL = os.environ.get("ALIBABA_BASE_URL", ALIBABA_URL_DEFAULT)
NVIDIA_MODELS = configured_cloud_models()
ALIBABA_MODELS = csv_env("ALIBABA_MODELS", "qwen-plus,qwen-turbo")
BEDROCK_MODELS = csv_env(
    "OPSORA_BEDROCK_MODELS",
    "amazon.nova-lite-v1:0,amazon.nova-micro-v1:0,amazon.nova-pro-v1:0",
)
LOCAL_FALLBACK_MODELS = csv_env(
    "OPSORA_LOCAL_MODELS", "qwen3.5:4b,llama3.1:latest,qwen2.5-coder:32b"
)
AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("BEDROCK_REGION", "us-east-1"))

nvidia_client = OpenAI(api_key=NVIDIA_KEY, base_url=NVIDIA_URL, timeout=35) if NVIDIA_KEY else None
alibaba_client = OpenAI(api_key=ALIBABA_KEY, base_url=ALIBABA_URL, timeout=35) if ALIBABA_KEY else None
local_client = OpenAI(api_key="ollama", base_url=LOCAL_URL, timeout=45)


@dataclass
class Selection:
    provider: str
    model: str


def available_local_models() -> list[str]:
    try:
        with urlopen(LOCAL_TAGS_URL, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [str(item.get("name", "")).strip() for item in payload.get("models", [])]
        return [model for model in models if model]
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return []


def configured_provider_order() -> list[str]:
    return [
        provider
        for provider in (part.strip().lower() for part in os.environ.get("OPSORA_PROVIDER_ORDER", "").split(","))
        if provider in {"nvidia", "alibaba", "bedrock", "local"}
    ]


def provider_available(provider: str) -> bool:
    if provider == "nvidia":
        return nvidia_client is not None
    if provider == "alibaba":
        return alibaba_client is not None
    if provider == "bedrock":
        try:
            return boto3.Session(profile_name=AWS_PROFILE).get_credentials() is not None
        except Exception:
            return False
    if provider == "local":
        return bool(available_local_models())
    return False


def configured_models(provider: str) -> list[str]:
    if provider == "nvidia":
        return NVIDIA_MODELS
    if provider == "alibaba":
        return ALIBABA_MODELS
    if provider == "bedrock":
        return BEDROCK_MODELS
    if provider == "local":
        return available_local_models() or LOCAL_FALLBACK_MODELS
    return []


def initial_selection() -> Selection:
    requested = configured_provider_order()
    # Bedrock remains an explicit route. A running Ollama is selected only when
    # no configured cloud route is ready, not as a cloud failure fallback.
    order = requested or ["nvidia", "alibaba", "local"]
    for provider in order:
        models = configured_models(provider)
        if models and provider_available(provider):
            return Selection(provider, models[0])
    return Selection("local", LOCAL_FALLBACK_MODELS[0])


selection = initial_selection()
safe_tools_enabled = os.environ.get("OPSORA_ENABLE_CLI_SAFE_TOOLS", "true").lower() == "true"
host_tools_enabled = os.environ.get("OPSORA_ENABLE_CLI_HOST_TOOLS", "").lower() == "true"
subagents_enabled = os.environ.get("OPSORA_ENABLE_CLI_SUBAGENTS", "").lower() == "true"
allow_local_fallback = os.environ.get("OPSORA_ALLOW_LOCAL_FALLBACK", "").lower() == "true"


SAFE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "Save a concise non-secret fact in persistent Opsora local memory.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "source": {"type": "string"}}, "required": ["text"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search persistent Opsora local memory for relevant prior context.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "graphify_query",
            "description": "Run a bounded read-only query against the local Graphify knowledge graph.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_status",
            "description": "Show non-secret Opsora workspace capability status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

HOST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a local text file after interactive operator approval.",
            "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a local file after interactive operator approval.",
            "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a host shell command after interactive operator approval.",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aws_command",
            "description": "Run read-only AWS CLI arguments after interactive operator approval.",
            "parameters": {"type": "object", "properties": {"arguments": {"type": "string"}}, "required": ["arguments"]},
        },
    },
]


def active_tools() -> list[dict[str, Any]]:
    result = list(SAFE_TOOLS) if safe_tools_enabled else []
    if host_tools_enabled:
        result.extend(HOST_TOOLS)
    return result


def truncate(value: str, maximum: int = MAX_TOOL_OUTPUT) -> str:
    if len(value) <= maximum:
        return value
    return value[:maximum] + f"\n… truncated ({len(value) - maximum} characters omitted)"


def redact_secrets(value: str) -> str:
    result = value
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and len(secret) >= 8:
            result = result.replace(secret, "[REDACTED]")
    return result


def tool_output(value: str) -> str:
    return truncate(redact_secrets(value))


def validate_host_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    lowered_parts = {part.casefold() for part in resolved.parts}
    name = resolved.name.casefold()
    if SENSITIVE_PATH_PARTS & lowered_parts:
        raise PermissionError("Access to credential directories is blocked.")
    if ".config" in lowered_parts and "gcloud" in lowered_parts:
        raise PermissionError("Access to credential directories is blocked.")
    if name in SENSITIVE_FILE_NAMES or name.startswith(".env.") or resolved.suffix.casefold() in SENSITIVE_FILE_SUFFIXES:
        raise PermissionError("Access to secret-bearing files is blocked.")
    return resolved


def validate_aws_read_only(arguments: list[str]) -> None:
    if len(arguments) < 2 or arguments[0].startswith("-") or arguments[1].startswith("-"):
        raise ValueError("Use AWS arguments as: <service> <read-only-operation> [options].")
    if any(argument in AWS_BLOCKED_GLOBAL_OPTIONS for argument in arguments):
        raise ValueError("Changing AWS profile or endpoint is not allowed through aws_command.")
    service, operation = arguments[0].casefold(), arguments[1].casefold()
    if operation in AWS_READ_ONLY_DENYLIST:
        raise ValueError("This AWS operation can write a local output file and is blocked.")
    if (service, operation) in AWS_READ_ONLY_SPECIAL_CASES:
        return
    if operation.startswith(AWS_READ_ONLY_PREFIXES):
        return
    raise ValueError("aws_command permits only read-only get/describe/list/head/batch-get/scan/query/lookup operations.")


def confirm(action: str) -> bool:
    answer = console.input(f"[bold yellow]Approve {action}? [y/N] [/bold yellow]").strip().lower()
    return answer in {"y", "yes"}


def execute_tool(name: str, args: dict[str, Any]) -> str:
    try:
        if name == "memory_add":
            return add_memory(args.get("text"), source=args.get("source", "cli"))
        if name == "memory_search":
            return json.dumps(search_memory(args.get("query"), args.get("limit", 5)), ensure_ascii=False)
        if name == "graphify_query":
            return graphify_query(args.get("query"), depth=args.get("depth", 2))
        if name == "workspace_status":
            return json.dumps(workspace_status(), ensure_ascii=False)
        if not host_tools_enabled:
            return "Host tools are disabled. Run /tools host on to enable interactive approvals."
        if name == "read_file":
            path = validate_host_path(Path(str(args["filepath"])))
            if not confirm(f"read {path}"):
                return "Read cancelled by operator."
            return tool_output(path.read_text(encoding="utf-8"))
        if name == "write_file":
            path = validate_host_path(Path(str(args["filepath"])))
            content = str(args["content"])
            preview = tool_output(content[:2_000])
            console.print(Panel(Syntax(preview, "text", word_wrap=True), title=f"Write preview · {path}", border_style="yellow"))
            if not confirm(f"write {path}"):
                return "Write cancelled by operator."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} characters to {path}."
        if name == "run_command":
            command = str(args["command"])
            console.print(Panel(command, title="Command request", border_style="red"))
            if not confirm("host command"):
                return "Command cancelled by operator."
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=180)
            output = result.stdout + result.stderr
            return tool_output(output or f"Command exited with code {result.returncode}.")
        if name == "aws_command":
            arguments = shlex.split(str(args["arguments"]))
            validate_aws_read_only(arguments)
            command = ["aws", "--profile", AWS_PROFILE, *arguments]
            console.print(Panel(" ".join(shlex.quote(part) for part in command), title="AWS request", border_style="magenta"))
            if not confirm("AWS CLI command"):
                return "AWS command cancelled by operator."
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            output = result.stdout + result.stderr
            return tool_output(output or f"AWS command exited with code {result.returncode}.")
        return f"Unknown tool: {name}."
    except Exception as exc:
        return f"Tool error: {exc}"


def message_dict(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    if isinstance(message, dict):
        return message
    return {"role": getattr(message, "role", "assistant"), "content": getattr(message, "content", "")}


def create_openai_completion(client: OpenAI, model: str, messages: list[dict[str, Any]], use_tools: bool) -> Any:
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
    tools = active_tools() if use_tools else []
    if tools:
        kwargs.update({"tools": tools, "tool_choice": "auto", "parallel_tool_calls": False})
    try:
        return client.chat.completions.create(**kwargs).choices[0].message
    except Exception:
        if not tools:
            raise
        # Several OpenAI-compatible providers accept chat but reject tool schema.
        fallback = {key: value for key, value in kwargs.items() if key not in {"tools", "tool_choice", "parallel_tool_calls"}}
        return client.chat.completions.create(**fallback).choices[0].message


def bedrock_message(messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
    session = boto3.Session(profile_name=AWS_PROFILE)
    runtime = session.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        config=Config(connect_timeout=5, read_timeout=35, retries={"max_attempts": 1}),
    )
    converted = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content") or ""
        if content:
            converted.append({"role": message["role"], "content": [{"text": str(content)}]})
    if not converted:
        converted = [{"role": "user", "content": [{"text": "Halo Opsora"}]}]
    response = runtime.converse(
        modelId=model,
        system=[{"text": "You are Opsora, a concise operational assistant. Answer in Indonesian unless asked otherwise."}],
        messages=converted,
        inferenceConfig={"maxTokens": 1200, "temperature": 0.2},
    )
    return {"role": "assistant", "content": response["output"]["message"]["content"][0]["text"]}


def invoke(provider: str, model: str, messages: list[dict[str, Any]], use_tools: bool = True) -> Any:
    if provider == "nvidia" and nvidia_client:
        return create_openai_completion(nvidia_client, model, messages, use_tools)
    if provider == "alibaba" and alibaba_client:
        return create_openai_completion(alibaba_client, model, messages, use_tools)
    if provider == "local":
        return create_openai_completion(local_client, model, messages, use_tools)
    if provider == "bedrock":
        return bedrock_message(messages, model)
    raise RuntimeError(f"Provider {provider} is not configured.")


def candidate_selections() -> list[Selection]:
    preferred = [selection]
    requested = configured_provider_order()
    if requested:
        providers = requested
    else:
        providers = [selection.provider]
        if selection.provider == "nvidia" and alibaba_client:
            providers.append("alibaba")
        if allow_local_fallback and "local" not in providers:
            providers.append("local")
    for provider in providers:
        for model in configured_models(provider):
            candidate = Selection(provider, model)
            if candidate not in preferred and provider_available(provider):
                preferred.append(candidate)
    return preferred


def call_with_fallback(messages: list[dict[str, Any]], use_tools: bool = True) -> tuple[Any, Selection]:
    errors = []
    for candidate in candidate_selections():
        try:
            return invoke(candidate.provider, candidate.model, messages, use_tools), candidate
        except Exception as exc:
            errors.append(f"{candidate.provider}:{candidate.model} ({str(exc)[:160]})")
    raise RuntimeError("All configured model attempts failed: " + "; ".join(errors))


SYSTEM_PROMPT = """You are Opsora, an operational assistant working in a local terminal.
Answer in Indonesian unless the user asks otherwise. Be direct and precise.
Use the Graphify and memory tools for local project context. Store only deliberate non-secret facts.
Host tools require an operator confirmation for every request."""


def run_turn(history: list[dict[str, Any]]) -> None:
    global selection
    for _ in range(MAX_TOOL_ROUNDS):
        with console.status(f"[cyan]⠹ {selection.provider}:{selection.model} is thinking…[/cyan]", spinner="dots"):
            message, used = call_with_fallback(
                [{"role": "system", "content": SYSTEM_PROMPT}, *history],
                use_tools=used_tools_allowed(),
            )
        selection = used
        record = message_dict(message)
        history.append(record)
        content = record.get("content") or ""
        if content:
            console.print()
            console.print(Markdown(content))
            console.print()

        tool_calls = record.get("tool_calls") if isinstance(record, dict) else getattr(message, "tool_calls", None)
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
            with console.status(f"[yellow]⠹ {selection.provider}:{selection.model} is executing tool: {name}…[/yellow]", spinner="dots"):
                output = execute_tool(name, args)
            
            # Render tool parameters elegantly
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            if len(args_str) > 60:
                args_str = args_str[:57] + "..."
            console.print(f"  [dim yellow]⚙ {name}({args_str})[/]")
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else tool_call.id
            history.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": output})
    console.print("[yellow]Tool-call limit reached; start a new request if more work is needed.[/yellow]")


def used_tools_allowed() -> bool:
    return safe_tools_enabled or host_tools_enabled


def aws_status() -> str:
    try:
        identity = boto3.Session(profile_name=AWS_PROFILE).client(
            "sts",
            region_name=AWS_REGION,
            config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
        ).get_caller_identity()
        account = identity.get("Account", "unknown")
        return f"connected · profile={AWS_PROFILE} · account={account[-4:].rjust(len(account), '•')} · region={AWS_REGION}"
    except Exception:
        return f"not verified · profile={AWS_PROFILE} · region={AWS_REGION}"


def print_welcome() -> None:
    console.print()
    title = Text("Opsora", style="bold cyan")
    title.append("   local operations assistant", style="dim white")
    console.print(title)
    console.print(Panel(
        f"[bold cyan]{selection.provider}:{selection.model}[/]  ·  {aws_status()}\n"
        "Ask a question, or use [bold]/help[/bold] for commands. [dim]Ctrl-C exits.[/dim]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 2),
    ))


def show_models() -> None:
    table = Table(title="Configured model routes", box=box.SIMPLE_HEAVY, border_style="bright_black")
    table.add_column("Provider", style="cyan")
    table.add_column("Models")
    table.add_column("Status")
    for provider in ("nvidia", "alibaba", "bedrock", "local"):
        status = "ready" if provider_available(provider) else "not configured / unavailable"
        table.add_row(provider, "\n".join(configured_models(provider)), status)
    console.print(table)
    console.print(
        "[dim]Use /model <nvidia|alibaba|bedrock|local> [model]. "
        "Ollama is used only when selected or OPSORA_ALLOW_LOCAL_FALLBACK=true. "
        "Bedrock is an explicit route and still validates on invocation.[/dim]"
    )


def show_tools() -> None:
    table = Table(title="Opsora tools", box=box.SIMPLE_HEAVY, border_style="bright_black")
    table.add_column("Tool", style="cyan")
    table.add_column("Mode")
    table.add_column("Description")
    for tool in SAFE_TOOLS:
        table.add_row(tool["function"]["name"], "enabled" if safe_tools_enabled else "disabled", tool["function"]["description"])
    for tool in HOST_TOOLS:
        table.add_row(tool["function"]["name"], "enabled + confirmation" if host_tools_enabled else "disabled", tool["function"]["description"])
    console.print(table)
    console.print("[dim]Use /tools safe on|off or /tools host on|off. Host operations always request confirmation.[/dim]")


def show_help() -> None:
    console.print(Panel(
        "[bold]/help[/bold]  commands\n"
        "[bold]/status[/bold]  provider, memory, Graphify, AWS status\n"
        "[bold]/models[/bold]  configured model routes\n"
        "[bold]/model[/bold] [provider] [model]  inspect or switch route\n"
        "[bold]/tools[/bold] [safe|host] [on|off]  inspect or toggle tools\n"
        "[bold]/new[/bold]  clear conversation · [bold]/clear[/bold]  redraw · [bold]/exit[/bold]  leave",
        title="Opsora commands",
        border_style="bright_black",
    ))


def handle_command(value: str, history: list[dict[str, Any]]) -> bool:
    global selection, safe_tools_enabled, host_tools_enabled
    parts = shlex.split(value)
    command = parts[0].lower()
    if command in {"/exit", "/quit"}:
        return False
    if command == "/help":
        show_help()
    elif command == "/clear":
        console.clear()
        print_welcome()
    elif command == "/new":
        history.clear()
        console.print("[dim]Started a new conversation.[/dim]")
    elif command == "/status":
        status = workspace_status()
        console.print(Panel(
            f"route: [cyan]{selection.provider}:{selection.model}[/cyan]\n"
            f"AWS: {aws_status()}\n"
            f"memory records: {status['memory']['count']}\n"
            f"Graphify: {'available' if status['graphify_global_graph'] else 'not available'}\n"
            f"tools: safe={'on' if safe_tools_enabled else 'off'}, host={'on' if host_tools_enabled else 'off'}\n"
            f"local fallback: {'on' if allow_local_fallback else 'off (cloud-first)'}",
            title="Opsora status",
            border_style="bright_black",
        ))
    elif command in {"/models", "/model"}:
        if command == "/models" or len(parts) == 1:
            show_models()
        else:
            provider = parts[1].lower()
            aliases = {"cloud": "nvidia", "ollama": "local"}
            provider = aliases.get(provider, provider)
            if provider not in {"nvidia", "alibaba", "bedrock", "local"}:
                console.print("[red]Unknown provider. Use nvidia, alibaba, bedrock, or local.[/red]")
            else:
                model = parts[2] if len(parts) > 2 else (configured_models(provider) or [""])[0]
                if not model:
                    console.print(f"[red]No configured model for {provider}.[/red]")
                else:
                    selection = Selection(provider, model)
                    console.print(f"[green]Route set to {provider}:{model}.[/green]")
    elif command == "/tools":
        if len(parts) == 1:
            show_tools()
        elif len(parts) == 3 and parts[1] in {"safe", "host"} and parts[2] in {"on", "off"}:
            enabled = parts[2] == "on"
            if parts[1] == "safe":
                safe_tools_enabled = enabled
            else:
                host_tools_enabled = enabled
            console.print(f"[green]{parts[1]} tools {'enabled' if enabled else 'disabled'}.[/green]")
        else:
            console.print("[red]Use /tools safe on|off or /tools host on|off.[/red]")
    else:
        console.print(f"[red]Unknown command: {command}. Use /help.[/red]")
    return True


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h"}:
        print("Usage: opsora [prompt]\nRun an interactive Opsora terminal session, or send one prompt directly. Type /help after launch.")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print("opsora-cli 3.1")
        return

    print_welcome()
    if len(sys.argv) > 1:
        history = [{"role": "user", "content": " ".join(sys.argv[1:])}]
        try:
            run_turn(history)
        except Exception as exc:
            console.print(Panel(str(exc), title="Model error", border_style="red"))
        return

    history: list[dict[str, Any]] = []
    def bottom_toolbar():
        return [
            ("class:toolbar_bg", f" [Ctrl+C] Cancel | [Ctrl+D] Exit | Mode: Interactive | Model: {selection.provider}:{selection.model} ")
        ]

    session = PromptSession(
        completer=WordCompleter(["/help", "/status", "/models", "/model", "/tools", "/new", "/clear", "/exit"], ignore_case=True),
        bottom_toolbar=bottom_toolbar,
        style=PromptStyle.from_dict({
            "prompt_main": "ansibrightcyan bold",
            "prompt_model": "ansibrightblack",
            "prompt_arrow": "ansigreen bold",
            "toolbar_bg": "bg:#2b2b2b #ffffff",
        }),
    )
    while True:
        try:
            # Meniru input box bergaya Codex CLI
            prompt_elements = [
                ("class:prompt_main", f"┌─ opsora "),
                ("class:prompt_model", f"[{selection.provider}:{selection.model}]\n"),
                ("class:prompt_arrow", "└─❯ ")
            ]
            value = session.prompt(prompt_elements).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session ended.[/dim]")
            return
        if not value:
            continue
        if value.startswith("/"):
            if not handle_command(value, history):
                console.print("[dim]Session ended.[/dim]")
                return
            continue
        
        # Add a subtle separator before AI response (Top border of AI response box)
        console.print("[cyan]╭──────────────────────────────────────────────────────────────╮[/cyan]")
        
        history.append({"role": "user", "content": value})
        try:
            run_turn(history)
            console.print("[cyan]╰──────────────────────────────────────────────────────────────╯[/cyan]\n")
        except Exception as exc:
            console.print(Panel(str(exc), title="Model error", border_style="red"))


if __name__ == "__main__":
    main()
