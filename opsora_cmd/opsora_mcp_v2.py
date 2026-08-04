"""Opsora MCP Client v2 — Full MCP protocol support (stdio + HTTP + SSE).

Upgrades from v1: Content-Length framed JSON-RPC 2.0, notifications,
resources, prompts, health checks, auto-reconnect. Sync only, stdlib only.
"""
from __future__ import annotations

import json, os, select, shlex, subprocess, threading, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

@dataclass
class MCPTool:
    name: str; description: str; input_schema: dict[str, Any]; server_name: str

@dataclass
class MCPResource:
    uri: str; name: str; description: str; mime_type: str; server_name: str

@dataclass
class MCPPrompt:
    name: str; description: str; arguments: list[dict]; server_name: str

@dataclass
class MCPServer_v2:
    name: str; transport: str  # "stdio", "http", "sse"
    command: str = ""; url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[MCPResource] = field(default_factory=list)
    prompts: list[MCPPrompt] = field(default_factory=list)
    connected: bool = False; process: Optional[subprocess.Popen] = None
    last_health_check: float = 0.0
    reconnect_attempts: int = 0; max_reconnect: int = 3


class MCPClient_v2:
    """Full MCP protocol client — sync, stdlib-only."""

    def __init__(self) -> None:
        self.servers: list[MCPServer_v2] = []
        self._request_id = 0
        self._lock = threading.Lock()

    # -- config --

    def load_config(self, config_path: str = "") -> None:
        if not config_path:
            config_path = str(Path.home() / ".opsora" / "mcp.json")
        path = Path(config_path)
        if not path.is_file():
            return
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            console.print(f"[yellow]⚠ Gagal load MCP config: {e}[/yellow]"); return
        for name, conf in config.get("mcpServers", {}).items():
            transport = "stdio" if "command" in conf else ("sse" if "/sse" in conf.get("url", "") else "http")
            self.servers.append(MCPServer_v2(
                name=name, transport=transport,
                command=conf.get("command", ""), url=conf.get("url", ""), env=conf.get("env", {})))

    # -- connection --

    def connect_all(self) -> list[MCPServer_v2]:
        for srv in self.servers:
            try:
                if srv.transport == "stdio":
                    self._connect_stdio(srv)
                else:
                    self._connect_http(srv, is_sse=(srv.transport == "sse"))
            except Exception as e:
                console.print(f"  [red]○[/red] MCP [bold]{srv.name}[/bold]: {e}")
        return [s for s in self.servers if s.connected]

    def _connect_stdio(self, srv: MCPServer_v2) -> None:
        if not srv.command:
            return
        # M2: start from clean slate
        srv.tools = []
        srv.resources = []
        srv.prompts = []
        # M2: kill any leaked process before spawning a new one
        if srv.process is not None and srv.process.poll() is None:
            try:
                srv.process.terminate()
                srv.process.wait(timeout=2)
            except Exception:
                try:
                    srv.process.kill()
                except Exception:
                    pass
        # shlex.split honors quoted arguments ("python server.py --name 'my srv'")
        # where str.split would mis-split inside the quotes.
        srv.process = subprocess.Popen(
            shlex.split(srv.command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env={**os.environ, **srv.env}, text=False, bufsize=0)
        threading.Thread(target=self._drain_stderr, args=(srv,), daemon=True).start()
        resp = self._send_stdio(srv, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "opsora-cli", "version": "3.1.0"}})
        if resp is None:
            return
        self._send_stdio(srv, "notifications/initialized", {}, is_notification=True)
        srv.connected = True
        self._discover_stdio(srv)
        console.print(f"  [green]●[/green] MCP [bold]{srv.name}[/bold]: "
                      f"{len(srv.tools)} tools, {len(srv.resources)} res, {len(srv.prompts)} prompts")

    def _discover_stdio(self, srv: MCPServer_v2) -> None:
        for method, attr, cls, key in [
            ("tools/list", "tools", MCPTool, "tools"),
            ("resources/list", "resources", MCPResource, "resources"),
            ("prompts/list", "prompts", MCPPrompt, "prompts"),
        ]:
            resp = self._send_stdio(srv, method, {})
            if not resp or key not in resp:
                continue
            for item in resp[key]:
                if cls is MCPTool:
                    srv.tools.append(MCPTool(
                        name=f"mcp__{srv.name}__{item['name']}", description=item.get("description", ""),
                        input_schema=item.get("inputSchema", {}), server_name=srv.name))
                elif cls is MCPResource:
                    srv.resources.append(MCPResource(
                        uri=item.get("uri", ""), name=item.get("name", ""),
                        description=item.get("description", ""),
                        mime_type=item.get("mimeType", "text/plain"), server_name=srv.name))
                else:
                    srv.prompts.append(MCPPrompt(
                        name=item.get("name", ""), description=item.get("description", ""),
                        arguments=item.get("arguments", []), server_name=srv.name))

    def _connect_http(self, srv: MCPServer_v2, is_sse: bool = False) -> None:
        if not srv.url:
            return
        # M2: start from clean slate
        srv.tools = []
        srv.resources = []
        srv.prompts = []
        base = srv.url.rstrip("/")
        if is_sse:
            base = base.rsplit("/sse", 1)[0].rstrip("/"); srv.url = base
        self._http_post(f"{base}/mcp/initialize", {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "opsora-cli", "version": "3.1.0"}}, timeout=15)
        srv.connected = True
        for ep, attr in [("/mcp/tools", "tools"), ("/mcp/resources", "resources")]:
            data = self._http_get(f"{base}{ep}")
            if not data:
                continue
            for item in data.get(ep.rsplit("/", 1)[1], []):
                if attr == "tools":
                    srv.tools.append(MCPTool(
                        name=f"mcp__{srv.name}__{item['name']}", description=item.get("description", ""),
                        input_schema=item.get("inputSchema", {}), server_name=srv.name))
                else:
                    srv.resources.append(MCPResource(
                        uri=item.get("uri", ""), name=item.get("name", ""),
                        description=item.get("description", ""),
                        mime_type=item.get("mimeType", "text/plain"), server_name=srv.name))
        if is_sse:
            srv.transport = "sse"
        console.print(f"  [green]●[/green] MCP [bold]{srv.name}[/bold]: "
                      f"{len(srv.tools)} tools, {len(srv.resources)} res")

    # -- tool / resource / prompt calls --

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        srv = self._find_server(server_name)
        if not srv:
            return f"Server '{server_name}' tidak terhubung."
        actual = tool_name.removeprefix(f"mcp__{server_name}__")
        try:
            resp = (self._send_stdio(srv, "tools/call", {"name": actual, "arguments": arguments}, timeout=30)
                    if srv.transport == "stdio"
                    else self._http_post(f"{srv.url.rstrip('/')}/mcp/tools/call",
                                         {"name": actual, "arguments": arguments}, timeout=30))
            # M4: transport failure (broken pipe / EOF / timeout) returns None
            if resp is None:
                raise ConnectionError(f"MCP server '{srv.name}' tidak merespons")
            # M5: successful response resets reconnect counter
            srv.reconnect_attempts = 0
        except Exception:
            if srv.reconnect_attempts < srv.max_reconnect:
                srv.reconnect_attempts += 1
                srv.connected = False
                self._reconnect_server(srv)
                return self.call_tool(server_name, tool_name, arguments)
            return "Tool call gagal dan reconnect gagal."
        return self._extract_text(resp)

    def _reconnect_server(self, srv: MCPServer_v2) -> None:
        """Reconnect only the given server (M2: no global reconnect)."""
        # Kill existing process if any
        if srv.process is not None:
            try:
                if srv.process.poll() is None:
                    srv.process.terminate()
                    srv.process.wait(timeout=2)
            except Exception:
                try:
                    srv.process.kill()
                except Exception:
                    pass
            srv.process = None
        # Clear stale discovery data
        srv.tools = []
        srv.resources = []
        srv.prompts = []
        srv.connected = False
        # Reconnect
        try:
            if srv.transport == "stdio":
                self._connect_stdio(srv)
            else:
                self._connect_http(srv, is_sse=(srv.transport == "sse"))
        except Exception as e:
            console.print(f"  [red]○[/red] MCP [bold]{srv.name}[/bold]: {e}")

    def call_tool_full(self, full_name: str, arguments: dict) -> str:
        """Call a tool by its full ``mcp__<server>__<tool>`` name.

        Compatibility entry point for callers (opsora_v2.execute_tool) that
        only know the flattened OpenAI function name, not the server/tool
        split.
        """
        parts = full_name.split("__", 2)
        if len(parts) < 3 or parts[0] != "mcp" or not parts[1] or not parts[2]:
            return f"Invalid MCP tool name: {full_name}"
        return self.call_tool(parts[1], full_name, arguments)

    def read_resource(self, server_name: str, uri: str) -> str:
        srv = self._find_server(server_name)
        if not srv:
            return f"Server '{server_name}' tidak terhubung."
        try:
            resp = (self._send_stdio(srv, "resources/read", {"uri": uri}, timeout=30)
                    if srv.transport == "stdio"
                    else self._http_post(f"{srv.url.rstrip('/')}/mcp/resources/read", {"uri": uri}, timeout=30))
            return self._extract_text(resp)
        except Exception as e:
            return f"Gagal baca resource: {e}"

    def get_prompt(self, server_name: str, name: str, arguments: dict | None = None) -> dict:
        srv = self._find_server(server_name)
        if not srv:
            return {"error": f"Server '{server_name}' tidak terhubung."}
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        try:
            resp = (self._send_stdio(srv, "prompts/get", params, timeout=15)
                    if srv.transport == "stdio"
                    else self._http_post(f"{srv.url.rstrip('/')}/mcp/prompts/get", params, timeout=15))
            return resp if isinstance(resp, dict) else {"result": resp}
        except Exception as e:
            return {"error": str(e)}

    # -- health / conversion / status / disconnect --

    def health_check(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for srv in self.servers:
            if srv.transport == "stdio":
                alive = srv.process is not None and srv.process.poll() is None
                results[srv.name] = "ok" if alive else "dead"
                if not alive:
                    srv.connected = False
            else:
                try:
                    urlopen(Request(f"{srv.url.rstrip('/')}/mcp/health", method="HEAD"), timeout=5).close()
                    results[srv.name] = "ok"
                except Exception:
                    results[srv.name] = "unreachable"; srv.connected = False
            srv.last_health_check = time.time()
        return results

    def get_all_tools(self) -> list[MCPTool]:
        return [t for s in self.servers if s.connected for t in s.tools]

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {
            "name": t.name, "description": t.description[:1024],
            "parameters": t.input_schema or {"type": "object", "properties": {}},
        }} for t in self.get_all_tools()]

    def render_status(self) -> Table:
        t = Table(title="🔌 MCP Servers v2", box=box.ROUNDED, border_style="cyan")
        for c in ["Server", "Transport", "Status", "Tools", "Resources", "Prompts"]:
            t.add_column(c, style="cyan" if c == "Server" else "",
                         justify="right" if c in ("Tools", "Resources", "Prompts") else "left")
        for s in self.servers:
            st = "[green]● connected[/green]" if s.connected else "[red]○ disconnected[/red]"
            t.add_row(s.name, s.transport, st, str(len(s.tools)), str(len(s.resources)), str(len(s.prompts)))
        return t

    def disconnect_all(self) -> None:
        for srv in self.servers:
            if srv.process and srv.process.poll() is None:
                try:
                    self._send_stdio(srv, "shutdown", {}, is_notification=True)
                    srv.process.terminate(); srv.process.wait(timeout=5)
                except Exception:
                    try: srv.process.kill()
                    except Exception: pass
            srv.connected = False

    # -- stdio JSON-RPC with Content-Length framing --

    def _send_stdio(self, srv: MCPServer_v2, method: str, params: dict,
                    is_notification: bool = False, timeout: int = 15) -> Optional[dict]:
        if not srv.process or not srv.process.stdin or not srv.process.stdout:
            return None
        # M1: hold lock only around id increment + message build + write
        with self._lock:
            self._request_id += 1
            msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
            if not is_notification:
                msg["id"] = self._request_id
            body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            try:
                srv.process.stdin.write(header + body); srv.process.stdin.flush()
            except (BrokenPipeError, OSError):
                srv.connected = False; return None
            request_id = self._request_id
        # M1: lock released before reading
        if is_notification:
            return None
        deadline = time.monotonic() + timeout
        return self._read_stdio_response(srv, request_id, deadline)

    def _read_stdio_response(self, srv: MCPServer_v2, request_id: int,
                             deadline: float) -> Optional[dict]:
        """Read framed JSON-RPC response matching the given request_id.

        Loops until the matching response arrives, skipping notifications
        and non-matching responses. Uses select.select for timeout enforcement
        with a try/except fallback for mock objects in tests.
        """
        if not srv.process or not srv.process.stdout:
            return None
        stdout = srv.process.stdout
        while True:
            # M1: enforce deadline with select.select
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("MCP server timeout")
            try:
                rlist, _, _ = select.select([stdout], [], [], remaining)
                if not rlist:
                    raise TimeoutError("MCP server timeout")
            except (OSError, ValueError, TypeError):
                # Fall through to blocking read for mock objects in tests
                pass
            try:
                cl = 0
                while True:
                    line = stdout.readline()
                    if not line:
                        return None
                    ls = (line.decode("ascii", errors="replace") if isinstance(line, bytes) else line).strip()
                    if not ls:
                        break
                    if ls.lower().startswith("content-length:"):
                        cl = int(ls.split(":")[1].strip())
                if cl == 0:
                    raw = stdout.readline()
                    if not raw:
                        return None
                    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                else:
                    body = stdout.read(cl)
                    data = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
            except (json.JSONDecodeError, OSError, ValueError):
                return None

            # M3: match response by id
            msg_id = data.get("id")
            has_method = "method" in data
            has_result = "result" in data
            has_error = "error" in data

            if msg_id is not None and msg_id != request_id:
                # Non-matching response — skip, keep waiting
                continue
            if msg_id is None and has_method:
                # Notification — skip
                continue
            # Accept: matching id, or id-less result/error (lenient for tests/non-strict servers)
            if "result" in data:
                result = data["result"]
                return result if result is not None else {}
            if "error" in data:
                err = data["error"]
                return {"error": err.get("message", str(err)) if isinstance(err, dict) else str(err)}
            return data

    # -- HTTP helpers --

    def _http_get(self, url: str, timeout: int = 10) -> Optional[dict]:
        try:
            req = Request(url, method="GET"); req.add_header("Accept", "application/json")
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError, OSError):
            return None

    def _http_post(self, url: str, payload: dict, timeout: int = 15) -> Optional[dict]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json"); req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"}
        except (URLError, OSError) as e:
            return {"error": f"Koneksi gagal: {e}"}
        except json.JSONDecodeError:
            return None

    def _find_server(self, name: str) -> Optional[MCPServer_v2]:
        return next((s for s in self.servers if s.name == name and s.connected), None)

    @staticmethod
    def _extract_text(resp: Optional[dict]) -> str:
        if resp is None:
            return "Tidak ada response."
        if isinstance(resp, dict):
            if "error" in resp:
                return f"Error: {resp['error']}"
            content = resp.get("content", [])
            if isinstance(content, list):
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                return "\n".join(texts) if texts else json.dumps(resp, ensure_ascii=False)
        return str(resp)

    @staticmethod
    def _drain_stderr(srv: MCPServer_v2) -> None:
        try:
            if srv.process and srv.process.stderr:
                while srv.process.stderr.readline():
                    pass
        except Exception:
            pass