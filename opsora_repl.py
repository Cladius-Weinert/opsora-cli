#!/usr/bin/env python3
"""Opsora REPL — Interactive terminal AI assistant with real LLM provider calls."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

try:
    from openai import OpenAI
except (ImportError, Exception):
    from openai_lite import OpenAI
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings

console = Console()

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

_SECRETS_ENV = Path("/root/.opsora/qwen-code/secrets.env")
if _SECRETS_ENV.is_file():
    for raw in _SECRETS_ENV.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY")
DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY")

MODELS = []
_clients: dict[str, OpenAI] = {}

if NVIDIA_KEY:
    MODELS.append(("nvidia", "meta/llama-3.1-70b-instruct"))
    _clients["nvidia"] = OpenAI(api_key=NVIDIA_KEY, base_url="https://integrate.api.nvidia.com/v1", timeout=40)

if DASHSCOPE_KEY:
    MODELS.append(("alibaba", "qwen-plus"))
    _clients["alibaba"] = OpenAI(
        api_key=DASHSCOPE_KEY,
        base_url=os.environ.get("ALIBABA_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        timeout=40,
    )

if not MODELS:
    console.print("[red]No API keys found. Set NVIDIA_API_KEY or DASHSCOPE_API_KEY.[/red]")
    sys.exit(1)

current_model_idx = 0

# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------

bindings = KeyBindings()


@bindings.add("c-t")
def _(event):
    global current_model_idx
    current_model_idx = (current_model_idx + 1) % len(MODELS)
    print_header()
    event.app.invalidate()


style = Style.from_dict({
    "prompt": "bold #00ffff",
    "toolbar": "bg:#2a2a2a #dddddd",
})


def bottom_toolbar():
    provider, model = MODELS[current_model_idx]
    return [("class:toolbar", f" [Ctrl+T] Switch Model: {provider}/{model}  |  [Ctrl+C] Cancel  |  [Ctrl+D] Exit ")]


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def print_header():
    console.clear()
    title = Text("Opsora", style="bold cyan")
    title.append("   local operations assistant", style="dim white")
    console.print(title)

    provider, model = MODELS[current_model_idx]
    providers_status = "  ".join(
        f"[green]●[/green] {p}" if p == provider else f"[dim]○ {p}[/dim]" for p, _ in MODELS
    )
    header_text = (
        f"[bold cyan]{provider}/{model}[/]  ·  [green]connected[/green]\n"
        f"{providers_status}\n"
        f"Ask a question, or use /help for commands. Ctrl-C exits."
    )
    console.print(Panel(header_text, expand=False, border_style="cyan", padding=(0, 2)))


def get_prompt_text():
    provider, model = MODELS[current_model_idx]
    return f"opsora [{provider}/{model}] › "


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file.",
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string"}},
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]

TOOL_MAX_OUTPUT = 15_000
TOOL_MAX_ROUNDS = 5

SENSITIVE_PATHS = {".aws", ".ssh", ".gnupg"}


def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "run_command":
            cmd = args["command"]
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd="/root")
            output = (result.stdout or "") + (result.stderr or "")
            return output[:TOOL_MAX_OUTPUT] or f"Command exited with code {result.returncode}."

        if name == "read_file":
            fp = Path(args["filepath"])
            if not fp.is_absolute():
                fp = Path("/root") / fp
            resolved = fp.resolve()
            if SENSITIVE_PATHS & set(resolved.parts):
                return "ERROR: Access to credential directories is blocked."
            return resolved.read_text(encoding="utf-8", errors="replace")[:TOOL_MAX_OUTPUT]

        if name == "list_files":
            target = Path(args["path"])
            if not target.is_absolute():
                target = Path("/root") / target
            if not target.is_dir():
                return f"ERROR: {target} is not a directory."
            entries = sorted(target.iterdir())[:100]
            lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]
            return "\n".join(lines) if lines else "Empty directory."

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error: {e}"


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Opsora, a concise terminal assistant. Answer in Indonesian unless asked otherwise. "
    "Be direct and precise. Use tools when they help answer the question."
)


def chat_with_llm(history: list[dict]) -> None:
    provider, model = MODELS[current_model_idx]
    client = _clients.get(provider)
    if not client:
        console.print(f"[red]Provider {provider} is not available.[/red]")
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

    for round_idx in range(TOOL_MAX_ROUNDS):
        try:
            with Live(
                Spinner("dots", text=f"{provider}/{model} thinking…", style="cyan"),
                refresh_per_second=15,
                transient=True,
            ):
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    tools=TOOLS,
                    tool_choice="auto",
                )

            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if msg.content:
                words = (msg.content or "").split(" ")
                out_text = ""
                with Live(refresh_per_second=25, auto_refresh=True) as live:
                    for word in words:
                        out_text += word + " "
                        live.update(Markdown(out_text))
                        time.sleep(0.015)
                console.print()

            tool_calls = msg.tool_calls
            if not tool_calls:
                return

            for tc in tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                console.print(f"  [dim yellow]⚙ {name}({json.dumps(args, ensure_ascii=False)[:80]})[/]")

                with Live(
                    Spinner("dots", text=f"Executing {name}…", style="yellow"),
                    refresh_per_second=15,
                    transient=True,
                ):
                    output = execute_tool(name, args)

                if len(output) > 500:
                    console.print(Panel(output[:500] + "\n…", title=f"↳ {name}", border_style="dim yellow"))
                else:
                    console.print(Panel(output, title=f"↳ {name}", border_style="dim yellow"))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    console.print("[yellow]Tool-call limit reached.[/yellow]")


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def handle_command(text: str, history: list[dict]) -> bool:
    cmd = text.strip().lower()
    if cmd in ("/exit", "/quit", "/q"):
        return False
    if cmd == "/help":
        console.print(Panel(
            "[bold]/help[/bold]     Show commands\n"
            "[bold]/new[/bold]      Clear conversation\n"
            "[bold]/clear[/bold]    Redraw screen\n"
            "[bold]/status[/bold]   Provider status\n"
            "[bold]/exit[/bold]     Exit",
            title="Commands",
            border_style="cyan",
        ))
        return True
    if cmd == "/new":
        history.clear()
        console.print("[green]✓[/green] Conversation cleared.")
        return True
    if cmd == "/clear":
        print_header()
        return True
    if cmd == "/status":
        for p, m in MODELS:
            c = _clients.get(p)
            status = "[green]● ready[/green]" if c else "[red]○ offline[/red]"
            console.print(f"  {status}  {p}/{m}")
        return True
    console.print(f"[red]Unknown command:[/red] {cmd}")
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    print_header()
    session = PromptSession(bottom_toolbar=bottom_toolbar, style=style, key_bindings=bindings)
    history: list[dict] = []

    while True:
        try:
            text = session.prompt(get_prompt_text).strip()
            if not text:
                continue
            if text.startswith("/"):
                if not handle_command(text, history):
                    break
                continue
            history.append({"role": "user", "content": text})
            chat_with_llm(history)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

    console.print("\n[dim]Meninggalkan Opsora CLI…[/dim]")


if __name__ == "__main__":
    main()
