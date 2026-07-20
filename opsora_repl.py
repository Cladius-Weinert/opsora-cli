#!/usr/bin/env python3
import time
import sys
import subprocess
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.spinner import Spinner
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings

console = Console()

MODELS = ["nvidia:meta/llama-3.1-70b-instruct", "aws:bedrock/claude-3.5-sonnet", "ollama:local/llama-3"]
current_model_idx = 0

bindings = KeyBindings()

@bindings.add('c-t')
def _(event):
    " Toggle model on Ctrl-T "
    global current_model_idx
    current_model_idx = (current_model_idx + 1) % len(MODELS)
    print_header()
    event.app.invalidate()

style = Style.from_dict({
    'prompt': 'bold #00ffff',
    'toolbar': 'bg:#2a2a2a #dddddd',
})

def bottom_toolbar():
    return [('class:toolbar', f' [Ctrl+T] Switch Model: {MODELS[current_model_idx]}  |  [Ctrl+C] Cancel  |  [Ctrl+D] Exit ')]

def print_header():
    console.clear()
    
    title = Text("Opsora", style="bold cyan")
    title.append("   local operations assistant", style="dim white")
    console.print(title)
    
    header_text = (
        f"[bold cyan]{MODELS[current_model_idx]}[/]  ·  [green]connected[/] ·           \n"
        f"profile=default · account=••••••••7746 · region=us-east-1    \n"
        f"Ask a question, or use /help for commands. Ctrl-C exits."
    )
    console.print(Panel(header_text, expand=False, border_style="cyan", padding=(0, 2)))

def get_prompt_text():
    return f"opsora [{MODELS[current_model_idx]}] › "

def execute_llm_task(prompt_text):
    active_model = MODELS[current_model_idx]
    
    # 1. Menampilkan model ketika berpikir (Thinking Phase)
    with Live(Spinner("dots", text=f"{active_model} is thinking...", style="cyan"), refresh_per_second=15, transient=True):
        time.sleep(1.0)
    
    # Deteksi operasi eksekusi (Real Execution Phase)
    cmd_to_run = None
    response_text = ""
    
    prompt_lower = prompt_text.lower()
    
    if "memori" in prompt_lower or "workspace" in prompt_lower or "halo" in prompt_lower:
        cmd_to_run = "ls -lh /home/ubuntu/opsora_memory.db 2>/dev/null || echo 'Database not found'"
        tool_name = "workspace_status"
    elif "disk" in prompt_lower or "df" in prompt_lower:
        cmd_to_run = "df -h /"
        tool_name = "check_disk_space"
    elif "model" in prompt_lower or "list" in prompt_lower:
        cmd_to_run = "ls -1 /home/ubuntu | grep -i agent"
        tool_name = "list_agents"
    elif prompt_lower.startswith("run ") or prompt_lower.startswith("exec "):
        cmd_to_run = prompt_text[4:].strip()
        tool_name = f"shell_exec"
    else:
        # Default mock response jika bukan perintah eksekusi
        tool_name = "chat_completion"

    # 2. Menampilkan status eksekusi secara real-time
    with Live(Spinner("dots", text=f"{active_model} is executing tool: [bold yellow]{tool_name}[/]...", style="yellow"), refresh_per_second=15, transient=True):
        time.sleep(0.8) # Simulasi jeda tool calling
        
        if cmd_to_run:
            try:
                res = subprocess.run(cmd_to_run, shell=True, capture_output=True, text=True, timeout=10)
                cmd_output = res.stdout.strip()
                if not cmd_output:
                    cmd_output = res.stderr.strip()
                
                response_text = f"**Eksekusi Selesai.**\n\nHasil dari tool `{tool_name}`:\n```bash\n{cmd_output}\n```"
            except Exception as e:
                response_text = f"Terjadi kesalahan saat mengeksekusi tool: {e}"
        else:
            response_text = f"Membalas sebagai `{active_model}`.\n\nSaya mengerti maksud Anda terkait **'{prompt_text}'**. Anda dapat mengetikkan `run <command>` untuk memerintahkan saya mengeksekusi *bash script* secara langsung."

    # Print nama tool yang dipanggil
    console.print(f"  [dim yellow]↳ {tool_name}[/]")
    time.sleep(0.3)

    # 3. Streaming jawaban hasil eksekusi ke layar
    words = response_text.split(" ")
    out_text = ""
    with Live(refresh_per_second=20, auto_refresh=True) as live:
        for word in words:
            if "\n" in word:
                out_text += word + " "
            else:
                out_text += word + " "
            live.update(Markdown(out_text))
            time.sleep(0.02)
    console.print()

def main():
    print_header()
    
    session = PromptSession(bottom_toolbar=bottom_toolbar, style=style, key_bindings=bindings)
    
    while True:
        try:
            text = session.prompt(get_prompt_text)
            if text.strip().lower() in ['exit', 'quit']:
                break
            if text.strip():
                execute_llm_task(text)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
            
    console.print("\n[dim]Meninggalkan Opsora CLI...[/dim]")

if __name__ == '__main__':
    main()
