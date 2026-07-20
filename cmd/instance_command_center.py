#!/usr/bin/env python3
"""
Opsora Instance Command Center v2 — Unified Data Access
Manage ALL instances + access ALL data from ONE place.

Instances:
  - opsora-brain (us-east-1) — THIS machine, Linux, r5.2xlarge
  - rdp-windows-prod (us-west-2) — Windows, m5zn.2xlarge, SSM Online
  - pw-agent-vps (us-east-1) — stopped, Linux
  - cloudpc-ec2-win (us-east-1) — stopped, Windows
  - my-termux-vm (us-east-1) — stopped, Linux
  - opsora-model-vps (us-east-1) — stopped, Linux
"""

import subprocess
import json
import sys
import os
from dataclasses import dataclass
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich import box

console = Console()

# ============================================================================
# Instance Registry
# ============================================================================

PROFILES = ["default", "cladius"]
REGIONS = ["us-east-1", "us-west-2"]

@dataclass
class Instance:
    instance_id: str
    name: str
    instance_type: str
    state: str
    public_ip: str
    private_ip: str
    region: str
    profile: str
    platform: str = "Linux"
    ssm_online: bool = False

def discover_instances() -> list[Instance]:
    instances = []
    seen = set()
    for profile in PROFILES:
        for region in REGIONS:
            try:
                result = subprocess.run(
                    [
                        "aws", "ec2", "describe-instances",
                        "--profile", profile, "--region", region,
                        "--query", (
                            'Reservations[].Instances[]'
                            '[InstanceId,InstanceType,State.Name,'
                            'Tags[?Key==`Name`].Value|[0],'
                            'PublicIpAddress,PrivateIpAddress,'
                            'PlatformDetails]'
                        ),
                        "--output", "json",
                    ],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    for raw in json.loads(result.stdout):
                        if raw and raw[0] and raw[0] not in seen:
                            seen.add(raw[0])
                            instances.append(Instance(
                                instance_id=raw[0],
                                instance_type=raw[1] or "unknown",
                                state=raw[2] or "unknown",
                                name=raw[3] or "(untagged)",
                                public_ip=raw[4] or "None",
                                private_ip=raw[5] or "None",
                                region=region,
                                profile=profile,
                                platform="Windows" if "Windows" in (raw[6] or "") else "Linux",
                            ))
            except Exception:
                pass

    # Check SSM status
    for region in REGIONS:
        try:
            result = subprocess.run(
                ["aws", "ssm", "describe-instance-information",
                 "--profile", "default", "--region", region,
                 "--query", "InstanceInformationList[].InstanceId",
                 "--output", "json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                ssm_ids = set(json.loads(result.stdout))
                for inst in instances:
                    if inst.instance_id in ssm_ids:
                        inst.ssm_online = True
        except Exception:
            pass

    return instances

# ============================================================================
# SSM Remote Data Access
# ============================================================================

def ssm_run_powershell(instance: Instance, commands: list[str]) -> str:
    """Run PowerShell commands on Windows instance via SSM"""
    # Send command
    cmds_json = json.dumps(commands)
    result = subprocess.run(
        [
            "aws", "ssm", "send-command",
            "--profile", "default",
            "--region", instance.region,
            "--instance-ids", instance.instance_id,
            "--document-name", "AWS-RunPowerShellScript",
            "--parameters", f"commands={cmds_json}",
            "--output", "json",
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    cmd_data = json.loads(result.stdout)
    command_id = cmd_data["Command"]["CommandId"]

    # Wait and get result
    import time
    time.sleep(10)
    result = subprocess.run(
        [
            "aws", "ssm", "get-command-invocation",
            "--profile", "default",
            "--region", instance.region,
            "--command-id", command_id,
            "--instance-id", instance.instance_id,
            "--output", "json",
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    invocation = json.loads(result.stdout)
    return invocation.get("StandardOutputContent", "No output")

def ssm_run_shell(instance: Instance, command: str) -> str:
    """Run shell command on Linux instance via SSM"""
    result = subprocess.run(
        [
            "aws", "ssm", "send-command",
            "--profile", "default",
            "--region", instance.region,
            "--instance-ids", instance.instance_id,
            "--document-name", "AWS-RunShellScript",
            "--parameters", f"commands={json.dumps([command])}",
            "--output", "json",
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    cmd_data = json.loads(result.stdout)
    command_id = cmd_data["Command"]["CommandId"]

    import time
    time.sleep(10)
    result = subprocess.run(
        [
            "aws", "ssm", "get-command-invocation",
            "--profile", "default",
            "--region", instance.region,
            "--command-id", command_id,
            "--instance-id", instance.instance_id,
            "--output", "json",
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    invocation = json.loads(result.stdout)
    return invocation.get("StandardOutputContent", "No output")

# ============================================================================
# Data Collection Templates
# ============================================================================

WIN_DATA_SCRIPTS = {
    "disk": [
        'Get-Volume | Select-Object DriveLetter,FileSystemLabel,Size,SizeRemaining,HealthStatus | Format-Table -AutoSize',
        'Get-PSDrive | Where-Object {$_.Used -gt 0} | Select-Object Name,Used,Free,Provider | Format-Table -AutoSize',
    ],
    "services": [
        'Get-Service | Where-Object {$_.Status -eq "Running"} | Select-Object Name,DisplayName,StartType | Format-Table -AutoSize',
    ],
    "network": [
        'Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notlike "Loopback*"} | Select-Object InterfaceAlias,IPAddress,PrefixOrigin | Format-Table -AutoSize',
    ],
    "processes": [
        'Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name,Id,WorkingSet64,CPU | Format-Table -AutoSize',
    ],
    "users": [
        'Get-LocalUser | Select-Object Name,Enabled,LastLogon | Format-Table -AutoSize',
    ],
    "apps": [
        'Get-ItemProperty HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName,DisplayVersion,Publisher | Format-Table -AutoSize',
        'Get-ItemProperty HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* | Select-Object DisplayName,DisplayVersion,Publisher | Format-Table -AutoSize',
    ],
    "files": [
        'Get-ChildItem C:\\ -Directory -Depth 0 | Select-Object Name,LastWriteTime | Format-Table -AutoSize',
        'Get-ChildItem C:\\terraform-aws -Recurse -File | Select-Object FullName,Length | Format-Table -AutoSize',
    ],
}

LINUX_DATA_SCRIPTS = {
    "disk": "df -h && echo '---' && du -sh /home/ubuntu/* 2>/dev/null | sort -rh | head -20",
    "services": "systemctl list-units --type=service --state=running --no-pager 2>/dev/null || service --status-all 2>/dev/null",
    "network": "ip addr show && echo '---' && ss -tlnp",
    "processes": "ps aux --sort=-%mem | head -20",
    "docker": "docker ps -a 2>/dev/null && echo '---' && docker images 2>/dev/null",
}

# ============================================================================
# Display
# ============================================================================

def show_instance_table(instances: list[Instance]) -> None:
    table = Table(
        title="🏠 Opsora Unified Instance Command Center",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
    )
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Platform")
    table.add_column("Public IP")
    table.add_column("Region")
    table.add_column("SSM")

    for inst in instances:
        state_color = "green" if inst.state == "running" else "red"
        ssm_icon = "✓" if inst.ssm_online else "✗"
        table.add_row(
            inst.instance_id[-8:],
            inst.name,
            inst.instance_type,
            f"[{state_color}]{inst.state}[/{state_color}]",
            inst.platform,
            inst.public_ip,
            inst.region,
            f"[{'green' if inst.ssm_online else 'red'}]{ssm_icon}[/]",
        )

    console.print(table)
    running = sum(1 for i in instances if i.state == "running")
    ssm_count = sum(1 for i in instances if i.ssm_online)
    console.print()
    console.print(Panel(
        f"[green]● Running: {running}[/green]  "
        f"[red]● Stopped: {len(instances) - running}[/red]  "
        f"SSM Online: {ssm_count}  "
        f"Regions: {', '.join(REGIONS)}",
        border_style="cyan", box=box.ROUNDED,
    ))

def show_data_menu(instance: Instance) -> None:
    """Show available data categories for an instance"""
    if instance.platform == "Windows":
        categories = list(WIN_DATA_SCRIPTS.keys())
    else:
        categories = list(LINUX_DATA_SCRIPTS.keys())

    console.print(Panel(
        f"[bold]{instance.name}[/bold] ({instance.instance_id[-8:]})\n"
        f"Platform: {instance.platform}  |  State: {instance.state}  |  SSM: {'✓ Online' if instance.ssm_online else '✗ Offline'}\n\n"
        f"[bold]Available Data Categories:[/bold]\n"
        + "\n".join(f"  • {cat}" for cat in categories)
        + "\n\n[dim]Type category name to fetch, 'back' to return[/dim]",
        border_style="cyan", box=box.ROUNDED,
    ))

def fetch_instance_data(instance: Instance, category: str) -> str:
    """Fetch data from an instance"""
    if instance.platform == "Windows":
        if category in WIN_DATA_SCRIPTS:
            return ssm_run_powershell(instance, WIN_DATA_SCRIPTS[category])
        return f"Unknown category: {category}"
    else:
        if category in LINUX_DATA_SCRIPTS:
            return ssm_run_shell(instance, LINUX_DATA_SCRIPTS[category])
        return f"Unknown category: {category}"

# ============================================================================
# Local Data Catalog (opsora-brain - THIS machine)
# ============================================================================

def catalog_local_data() -> dict:
    """Catalog all data on THIS machine (opsora-brain)"""
    data = {}

    # Projects
    projects = []
    for item in Path("/home/ubuntu").iterdir():
        if item.is_dir() and not item.name.startswith("."):
            files = list(item.rglob("*.py")) + list(item.rglob("*.tf")) + list(item.rglob("*.sh"))
            projects.append({
                "name": item.name,
                "files": len(files),
                "size_mb": sum(f.stat().st_size for f in item.rglob("*") if f.is_file()) / 1024 / 1024,
            })

    data["projects"] = sorted(projects, key=lambda x: x["size_mb"], reverse=True)[:15]

    # Agent files
    data["agent_files"] = [str(f.name) for f in Path("/home/ubuntu").glob("agent*.py")]

    # Docker
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data["docker_containers"] = [json.loads(line) for line in result.stdout.strip().split("\n") if line]
    except Exception:
        data["docker_containers"] = []

    # Databases
    data["databases"] = []
    for db in Path("/home/ubuntu").glob("*.db"):
        data["databases"].append({"name": db.name, "size_kb": db.stat().st_size / 1024})

    # Config files
    data["config_files"] = [
        ".opsora_env", ".bashrc", ".zshrc", ".gitconfig",
        "model-studio.env", ".env",
    ]

    return data

def show_local_catalog() -> None:
    """Show catalog of data on opsora-brain"""
    data = catalog_local_data()

    # Projects
    table = Table(title="📁 Projects on opsora-brain", box=box.ROUNDED, border_style="cyan")
    table.add_column("Project", style="cyan")
    table.add_column("Files")
    table.add_column("Size (MB)")
    for proj in data["projects"]:
        table.add_row(proj["name"], str(proj["files"]), f"{proj['size_mb']:.1f}")
    console.print(table)

    # Agent files
    console.print(Panel(
        f"[bold]Agent Files:[/bold] {', '.join(data['agent_files'])}",
        border_style="magenta", box=box.ROUNDED,
    ))

    # Databases
    if data["databases"]:
        table = Table(title="🗄️ Databases", box=box.ROUNDED, border_style="cyan")
        table.add_column("Database", style="cyan")
        table.add_column("Size (KB)")
        for db in data["databases"]:
            table.add_row(db["name"], f"{db['size_kb']:.1f}")
        console.print(table)

    # Docker
    if data["docker_containers"]:
        console.print(Panel(
            f"[bold]{len(data['docker_containers'])} Docker containers[/bold]",
            border_style="green", box=box.ROUNDED,
        ))

# ============================================================================
# Main Interactive Loop
# ============================================================================

def print_help() -> None:
    console.print(Panel(
        "[bold cyan]Opsora Unified Command Center[/bold cyan]\n\n"
        "[bold]list[/bold]              Show all instances\n"
        "[bold]data <name>[/bold]        Access data on instance\n"
        "[bold]local[/bold]             Catalog data on opsora-brain\n"
        "[bold]start <name>[/bold]       Start instance\n"
        "[bold]stop <name>[/bold]        Stop instance\n"
        "[bold]ssh <name>[/bold]         SSH into instance\n"
        "[bold]run <name> <cmd>[/bold]   Run command via SSM\n"
        "[bold]exec <name>[/bold]        Interactive data browser\n"
        "[bold]help[/bold]              Show this help\n"
        "[bold]exit[/bold]              Exit",
        title="Commands", border_style="cyan", box=box.ROUNDED,
    ))

def find_instance(name: str, instances: list[Instance]) -> Instance | None:
    name = name.lower()
    for inst in instances:
        if name in inst.instance_id.lower() or name in inst.name.lower():
            return inst
    return None

def main():
    console.clear()
    console.print(Panel(
        "[bold]⚡ Opsora Unified Instance Command Center[/bold]\n"
        "[dim]6 instances | 2 regions | All data accessible from ONE place[/dim]",
        border_style="cyan", box=box.DOUBLE,
    ))

    instances = discover_instances()
    show_instance_table(instances)

    # Auto-show local catalog
    console.print()
    console.print("[bold cyan]📋 Data on opsora-brain (this machine):[/bold cyan]")
    show_local_catalog()

    console.print("\n[dim]Type 'help' for commands, 'exit' to quit[/dim]")

    while True:
        try:
            prompt = input("\n\033[1;36mopsora-command\033[0m \033[33m❯\033[0m ").strip()
            if not prompt:
                continue

            parts = prompt.split()
            cmd = parts[0].lower()

            if cmd in ("exit", "quit", "q"):
                break
            elif cmd == "help":
                print_help()
            elif cmd == "list":
                instances = discover_instances()
                show_instance_table(instances)
            elif cmd == "local":
                show_local_catalog()
            elif cmd == "data":
                target = parts[1] if len(parts) > 1 else None
                inst = find_instance(target, instances) if target else None
                if inst:
                    if not inst.ssm_online and inst.state == "stopped":
                        console.print(f"[yellow]⚠ {inst.name} is stopped. Start it first with: start {inst.name}[/yellow]")
                        continue
                    if not inst.ssm_online:
                        console.print(f"[yellow]⚠ {inst.name} has no SSM agent. Use SSH instead.[/yellow]")
                        continue
                    show_data_menu(inst)
                    while True:
                        cat = input("\n\033[1;36mcategory\033[0m \033[33m❯\033[0m ").strip()
                        if cat.lower() in ("back", "exit", "q"):
                            break
                        if cat:
                            console.print(f"\n[bold]Fetching {cat} from {inst.name}...[/bold]\n")
                            output = fetch_instance_data(inst, cat)
                            console.print(output[:3000])
                            if len(output) > 3000:
                                console.print(f"[dim]... truncated ({len(output)} chars)[/dim]")
                else:
                    console.print(f"[red]Instance not found: {target}[/red]")
            elif cmd in ("start", "stop", "reboot", "ssh"):
                target = parts[1] if len(parts) > 1 else None
                inst = find_instance(target, instances) if target else None
                if not inst:
                    console.print(f"[red]Instance not found: {target}[/red]")
                    continue
                if cmd == "start":
                    console.print(f"[green]→ Starting {inst.name}...[/green]")
                    subprocess.run(
                        ["aws", "ec2", "start-instances",
                         "--profile", inst.profile, "--region", inst.region,
                         "--instance-ids", inst.instance_id],
                        capture_output=True, text=True
                    )
                elif cmd == "stop":
                    console.print(f"[yellow]→ Stopping {inst.name}...[/yellow]")
                    subprocess.run(
                        ["aws", "ec2", "stop-instances",
                         "--profile", inst.profile, "--region", inst.region,
                         "--instance-ids", inst.instance_id],
                        capture_output=True, text=True
                    )
                elif cmd == "ssh":
                    if inst.public_ip != "None":
                        user = "Administrator" if inst.platform == "Windows" else "ubuntu"
                        os.system(f"ssh -o StrictHostKeyChecking=no {user}@{inst.public_ip}")
                    else:
                        console.print(f"[red]No public IP for {inst.name}[/red]")
            elif cmd == "run" and len(parts) >= 3:
                target = parts[1]
                command_str = " ".join(parts[2:])
                inst = find_instance(target, instances)
                if inst and inst.ssm_online:
                    if inst.platform == "Windows":
                        console.print(ssm_run_powershell(inst, [command_str]))
                    else:
                        console.print(ssm_run_shell(inst, command_str))
                else:
                    console.print(f"[red]Instance not found or SSM offline: {target}[/red]")
            elif cmd == "exec":
                target = parts[1] if len(parts) > 1 else None
                inst = find_instance(target, instances) if target else None
                if inst:
                    if inst.ssm_online:
                        console.print(f"[green]→ Interactive session with {inst.name}[/green]")
                        if inst.platform == "Windows":
                            console.print(f"[dim]Run: aws ssm start-session --profile default --region {inst.region} --target {inst.instance_id}[/dim]")
                        else:
                            console.print(f"[dim]Run: aws ssm start-session --profile default --region {inst.region} --target {inst.instance_id}[/dim]")
                    else:
                        console.print(f"[yellow]⚠ {inst.name} SSM offline[/yellow]")
            else:
                console.print(f"[red]Unknown: {cmd}[/red]")

        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except EOFError:
            break

if __name__ == "__main__":
    main()
