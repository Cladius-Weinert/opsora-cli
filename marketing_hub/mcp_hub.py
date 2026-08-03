#!/usr/bin/env python3
"""
Opsora MCP Integration Hub — Unified Wrapper for ALL 12 MCP Servers
Connects all MCP servers for unified marketing operations.

Usage:
    python3 -m marketing_hub.mcp_hub status          # Show all MCP status
    python3 -m marketing_hub.mcp_hub test --server all  # Test connections
    python3 -m marketing_hub.mcp_hub env             # Show env vars
    python3 -m marketing_hub.mcp_hub cloud           # Show cloud CLI tools
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "mcp_hub.log"), logging.StreamHandler()],
)
log = logging.getLogger("mcp_hub")


@dataclass
class MCPServer:
    name: str
    type: str
    command: Optional[str] = None
    args: list[str] = field(default_factory=list)
    url: Optional[str] = None
    status: str = "unknown"
    error: Optional[str] = None
    tools: list[str] = field(default_factory=list)


class MCPHub:
    def __init__(self):
        self.settings_path = Path("/root/.qwen/settings.json")
        self.servers: dict[str, MCPServer] = {}
        self._load_config()

    def _load_config(self):
        try:
            with open(self.settings_path) as f:
                config = json.load(f)
            mcp_config = config.get("mcp", {}).get("servers", {})
            for name, cfg in mcp_config.items():
                self.servers[name] = MCPServer(
                    name=name,
                    type=cfg.get("type", "local"),
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("url"),
                )
        except Exception as e:
            log.error(f"Failed to load MCP config: {e}")

    async def test_connection(self, server_name: str) -> MCPServer:
        server = self.servers.get(server_name)
        if not server:
            return MCPServer(name=server_name, type="unknown", status="error", error="Not configured")
        try:
            if server.type == "local":
                if server.command:
                    result = subprocess.run(["which", server.command.split()[0]], capture_output=True, text=True, timeout=5)
                    if result.returncode != 0:
                        server.status, server.error = "error", f"Command not found: {server.command}"
                        return server
                if server.args:
                    script_path = server.args[0] if server.args else ""
                    if script_path and not os.path.exists(script_path):
                        server.status, server.error = "error", f"Script not found: {script_path}"
                        return server
                server.status = "connected"
            elif server.type == "remote":
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(server.url or "", follow_redirects=True)
                    server.status = "connected" if response.status_code < 500 else "error"
                    if server.status == "error":
                        server.error = f"HTTP {response.status_code}"
        except Exception as e:
            server.status, server.error = "error", str(e)
        return server

    async def test_all(self) -> dict[str, MCPServer]:
        log.info("Testing all MCP server connections...")
        results = {}
        for name in self.servers:
            try:
                results[name] = await self.test_connection(name)
            except Exception as e:
                results[name] = MCPServer(name=name, type="unknown", status="error", error=str(e))
        return results

    def get_status_summary(self) -> str:
        lines = ["📡 MCP Server Status", "=" * 50]
        for name, server in sorted(self.servers.items()):
            icon = {"connected": "✅", "error": "❌", "unknown": "❓"}.get(server.status, "❓")
            lines.append(f"  {icon} {name} ({server.type})")
            if server.error:
                lines.append(f"     Error: {server.error}")
        connected = sum(1 for s in self.servers.values() if s.status == "connected")
        lines.append(f"\n  {connected}/{len(self.servers)} servers connected")
        return "\n".join(lines)

    def get_env_status(self) -> str:
        env_vars = {
            "NVIDIA_API_KEY": "NVIDIA NIM", "DASHSCOPE_API_KEY": "Alibaba DashScope",
            "XAI_API_KEY": "Grok/XAI", "OPENAI_API_KEY": "OpenAI",
            "GITHUB_PAT": "GitHub", "VERCEL_TOKEN": "Vercel",
            "CLOUDFLARE_API_TOKEN": "Cloudflare", "SUPABASE_MCP_TOKEN": "Supabase",
            "TELEGRAM_API_ID": "Telegram", "TWITTER_API_KEY": "Twitter/X",
        }
        lines = ["🔑 Environment Variables", "=" * 50]
        for var, service in env_vars.items():
            value = os.environ.get(var, "")
            if value:
                masked = value[:8] + "..." if len(value) > 12 else "set"
                lines.append(f"  ✅ {service}: {masked}")
            else:
                lines.append(f"  ❌ {service}: Not set")
        return "\n".join(lines)

    def get_cloud_status(self) -> str:
        tools = {
            "gcloud": "Google Cloud", "aws": "AWS", "aliyun": "Alibaba Cloud",
            "fly": "Fly.io", "flyctl": "Fly.io (alt)", "vercel": "Vercel",
            "wrangler": "Cloudflare", "gh": "GitHub CLI", "docker": "Docker",
        }
        lines = ["☁️  Cloud CLI Tools", "=" * 50]
        for cmd, name in tools.items():
            found = subprocess.run(["which", cmd], capture_output=True).returncode == 0
            lines.append(f"  {'✅' if found else '❌'} {name} ({cmd})")
        return "\n".join(lines)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Opsora MCP Integration Hub")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show all MCP server status")
    subparsers.add_parser("env", help="Show environment variable status")
    subparsers.add_parser("cloud", help="Show cloud CLI tools status")
    test_parser = subparsers.add_parser("test", help="Test MCP connections")
    test_parser.add_argument("--server", default="all")

    args = parser.parse_args()
    hub = MCPHub()

    if args.command == "status":
        await hub.test_all()
        print(hub.get_status_summary())
    elif args.command == "env":
        print(hub.get_env_status())
    elif args.command == "cloud":
        print(hub.get_cloud_status())
    elif args.command == "test":
        if args.server == "all":
            await hub.test_all()
            print(hub.get_status_summary())
        else:
            result = await hub.test_connection(args.server)
            icon = "✅" if result.status == "connected" else "❌"
            print(f"{icon} {result.name}: {result.status}")
            if result.error:
                print(f"   Error: {result.error}")
    else:
        print(hub.get_env_status())
        print()
        print(hub.get_cloud_status())
        print()
        await hub.test_all()
        print(hub.get_status_summary())


if __name__ == "__main__":
    asyncio.run(main())