"""Opsora MCP Client — Minimal Model Context Protocol integration.

Connects to MCP servers (stdio or HTTP/SSE) and exposes their tools
to the Opsora agent loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


@dataclass
class MCPServer:
    name: str
    transport: str  # "stdio" or "http"
    command: str = ""
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    tools: list[MCPTool] = field(default_factory=list)
    connected: bool = False
    process: Optional[subprocess.Popen] = None


class MCPClient:
    """Minimal MCP client supporting stdio transport."""

    def __init__(self):
        self.servers: list[MCPServer] = []
        self._request_id = 0

    def load_config(self, config_path: str = "") -> None:
        """Load MCP server configuration from JSON file."""
        if not config_path:
            config_path = str(Path.home() / ".opsora" / "mcp.json")

        path = Path(config_path)
        if not path.is_file():
            return

        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            for name, server_conf in config.get("mcpServers", {}).items():
                transport = "stdio" if "command" in server_conf else "http"
                server = MCPServer(
                    name=name,
                    transport=transport,
                    command=server_conf.get("command", ""),
                    url=server_conf.get("url", ""),
                    env=server_conf.get("env", {}),
                )
                self.servers.append(server)
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"[yellow]⚠ Failed to load MCP config: {e}[/yellow]")

    def connect(self, server_name: str = "") -> list[MCPServer]:
        """Connect to MCP servers and discover their tools."""
        targets = [s for s in self.servers if not server_name or s.name == server_name]
        for server in targets:
            if server.transport == "stdio":
                self._connect_stdio(server)
            else:
                self._connect_http(server)
        return [s for s in self.servers if s.connected]

    def _connect_stdio(self, server: MCPServer) -> None:
        """Connect to a stdio MCP server."""
        if not server.command:
            return

        env = {**os.environ, **server.env}

        try:
            parts = server.command.split()
            server.process = subprocess.Popen(
                parts,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )

            init_response = self._send_request(server, "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opsora-cli", "version": "3.0.0"},
            })

            if init_response is not None:
                server.connected = True
                tools_response = self._send_request(server, "tools/list", {})
                if tools_response and "tools" in tools_response:
                    for t in tools_response["tools"]:
                        server.tools.append(MCPTool(
                            name=f"mcp__{server.name}__{t['name']}",
                            description=t.get("description", ""),
                            input_schema=t.get("inputSchema", {}),
                            server_name=server.name,
                        ))
                console.print(f"  [green]●[/green] MCP [bold]{server.name}[/bold]: {len(server.tools)} tools")
        except Exception as e:
            console.print(f"  [red]○[/red] MCP [bold]{server.name}[/bold]: {e}")

    def _connect_http(self, server: MCPServer) -> None:
        """Connect to an HTTP MCP server (simplified)."""
        if not server.url:
            return
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{server.url}/mcp/tools",
                method="GET",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                server.connected = True
                for t in data.get("tools", []):
                    server.tools.append(MCPTool(
                        name=f"mcp__{server.name}__{t['name']}",
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                        server_name=server.name,
                    ))
            console.print(f"  [green]●[/green] MCP [bold]{server.name}[/bold]: {len(server.tools)} tools")
        except Exception as e:
            console.print(f"  [red]○[/red] MCP [bold]{server.name}[/bold]: {e}")

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool by its full name (mcp__server__tool)."""
        parts = tool_name.split("__", 2)
        if len(parts) < 3 or parts[0] != "mcp":
            return f"Invalid MCP tool name: {tool_name}"

        server_name = parts[1]
        actual_tool = parts[2]

        server = next((s for s in self.servers if s.name == server_name and s.connected), None)
        if not server:
            return f"MCP server '{server_name}' not connected."

        if server.transport == "stdio":
            response = self._send_request(server, "tools/call", {
                "name": actual_tool,
                "arguments": arguments,
            })
            if response is None:
                return "MCP tool call returned no response."
            if isinstance(response, dict):
                content = response.get("content", [])
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return "\n".join(texts) if texts else json.dumps(response, ensure_ascii=False)
                return json.dumps(response, ensure_ascii=False)
            return str(response)
        else:
            try:
                import urllib.request
                data = json.dumps({"name": actual_tool, "arguments": arguments}).encode()
                req = urllib.request.Request(
                    f"{server.url}/mcp/tools/call",
                    data=data,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read())
                    content = result.get("content", [])
                    if isinstance(content, list):
                        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
                    return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                return f"MCP HTTP call failed: {e}"

    def get_all_tools(self) -> list[MCPTool]:
        """Get all tools from all connected servers."""
        tools = []
        for server in self.servers:
            if server.connected:
                tools.extend(server.tools)
        return tools

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert MCP tools to OpenAI function-calling format."""
        tools = []
        for mcp_tool in self.get_all_tools():
            tools.append({
                "type": "function",
                "function": {
                    "name": mcp_tool.name,
                    "description": mcp_tool.description,
                    "parameters": mcp_tool.input_schema or {"type": "object", "properties": {}},
                },
            })
        return tools

    def _send_request(self, server: MCPServer, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request to a stdio MCP server."""
        if not server.process or not server.process.stdin or not server.process.stdout:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            server.process.stdin.write(json.dumps(request) + "\n")
            server.process.stdin.flush()

            line = server.process.stdout.readline()
            if not line:
                return None
            response = json.loads(line.strip())
            if "result" in response:
                return response["result"]
            if "error" in response:
                return {"error": response["error"]}
            return response
        except Exception as e:
            return None

    def disconnect_all(self) -> None:
        """Disconnect all MCP servers."""
        for server in self.servers:
            if server.process:
                try:
                    self._send_request(server, "shutdown", {})
                    server.process.terminate()
                    server.process.wait(timeout=5)
                except Exception:
                    if server.process:
                        server.process.kill()
                server.connected = False

    def render_status(self) -> Table:
        """Render MCP server status table."""
        table = Table(title="🔌 MCP Servers", box=box.ROUNDED, border_style="cyan")
        table.add_column("Server", style="cyan")
        table.add_column("Transport")
        table.add_column("Status")
        table.add_column("Tools")

        for server in self.servers:
            status = "[green]● connected[/green]" if server.connected else "[red]○ disconnected[/red]"
            table.add_row(
                server.name,
                server.transport,
                status,
                str(len(server.tools)),
            )
        return table
