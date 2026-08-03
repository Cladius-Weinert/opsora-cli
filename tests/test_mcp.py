"""Comprehensive tests for opsora_mcp_v2.py — the unified MCP client.

v1 (opsora_mcp.py) was removed in the Phase-1 MCP dedup; every v1 behaviour
the CLI relies on is covered here against the v2 API.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_mcp_v2
from opsora_mcp_v2 import MCPClient_v2, MCPServer_v2, MCPTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frame(payload: dict) -> tuple[bytes, bytes]:
    """Build one Content-Length framed JSON-RPC message (header line, body)."""
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n".encode("ascii"), body


def _stdio_mock(responses: list[dict]) -> MagicMock:
    """Mock Popen process whose stdout yields the given framed responses."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.stderr.readline.return_value = b""  # stop the drain thread at once

    readline_seq: list[bytes] = []
    read_seq: list[bytes] = []
    for payload in responses:
        header, body = _frame(payload)
        readline_seq.extend([header, b"\r\n"])
        read_seq.append(body)
    proc.stdout.readline.side_effect = readline_seq
    proc.stdout.read.side_effect = read_seq
    proc.poll.return_value = None
    return proc


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_tool_creation(self):
        tool = MCPTool(
            name="mcp__server__tool",
            description="Test tool",
            input_schema={"type": "object", "properties": {}},
            server_name="server",
        )
        assert tool.name == "mcp__server__tool"
        assert tool.description == "Test tool"
        assert tool.server_name == "server"

    def test_server_creation_stdio_defaults(self):
        server = MCPServer_v2(name="test-server", transport="stdio",
                              command="python server.py")
        assert server.command == "python server.py"
        assert server.tools == []
        assert server.resources == []
        assert server.prompts == []
        assert server.connected is False
        assert server.reconnect_attempts == 0

    def test_server_creation_http(self):
        server = MCPServer_v2(name="http-server", transport="http",
                              url="http://localhost:8080")
        assert server.transport == "http"
        assert server.url == "http://localhost:8080"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


class TestLoadConfig:
    @pytest.fixture
    def client(self):
        return MCPClient_v2()

    def test_missing_file_no_servers(self, client, tmp_path):
        client.load_config(str(tmp_path / "nonexistent.json"))
        assert client.servers == []

    def test_invalid_json_no_servers(self, client, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        client.load_config(str(bad))
        assert client.servers == []

    def test_valid_config_stdio_and_http(self, client, tmp_path):
        config = {
            "mcpServers": {
                "stdio-server": {"command": "python server.py",
                                 "env": {"KEY": "value"}},
                "http-server": {"url": "http://localhost:8080"},
            }
        }
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        client.load_config(str(path))

        assert len(client.servers) == 2
        stdio = next(s for s in client.servers if s.name == "stdio-server")
        assert stdio.transport == "stdio"
        assert stdio.command == "python server.py"
        assert stdio.env == {"KEY": "value"}

        http = next(s for s in client.servers if s.name == "http-server")
        assert http.transport == "http"
        assert http.url == "http://localhost:8080"

    def test_sse_url_detected(self, client, tmp_path):
        config = {"mcpServers": {"sse-server": {"url": "http://x:9/sse"}}}
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        client.load_config(str(path))
        assert client.servers[0].transport == "sse"

    def test_missing_fields_default_to_http(self, client, tmp_path):
        config = {"mcpServers": {"minimal": {}}}
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        client.load_config(str(path))

        server = client.servers[0]
        assert server.transport == "http"  # no command → not stdio
        assert server.command == ""
        assert server.url == ""


# ---------------------------------------------------------------------------
# stdio connection (Content-Length framed JSON-RPC)
# ---------------------------------------------------------------------------


class TestConnectStdio:
    def test_connect_success_discovers_tools(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="echo test")
        client.servers = [server]

        proc = _stdio_mock([
            {"result": {"protocolVersion": "2024-11-05"}},
            {"result": {"tools": [{"name": "tool1", "description": "Tool 1",
                                   "inputSchema": {}}]}},
            {"result": {}},  # resources/list → none
            {"result": {}},  # prompts/list → none
        ])
        with patch.object(opsora_mcp_v2.subprocess, "Popen", return_value=proc):
            client.connect_all()

        assert server.connected is True
        assert len(server.tools) == 1
        assert server.tools[0].name == "mcp__test__tool1"

    def test_connect_failure_pop_raises(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="bad-command")
        client.servers = [server]

        with patch.object(opsora_mcp_v2.subprocess, "Popen",
                          side_effect=OSError("Failed to start")):
            client.connect_all()

        assert server.connected is False

    def test_connect_no_response_not_connected(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cat")
        client.servers = [server]

        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stderr = MagicMock()
        proc.stderr.readline.return_value = b""
        proc.stdout.readline.return_value = b""  # EOF immediately
        with patch.object(opsora_mcp_v2.subprocess, "Popen", return_value=proc):
            client.connect_all()

        assert server.connected is False

    def test_quoted_command_parsed_with_shlex(self):
        """shlex.split must keep quoted arguments intact."""
        client = MCPClient_v2()
        server = MCPServer_v2(
            name="test", transport="stdio",
            command="python server.py --name 'my server' --flag")
        client.servers = [server]

        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stderr = MagicMock()
        proc.stderr.readline.return_value = b""
        proc.stdout.readline.return_value = b""  # abort after Popen
        with patch.object(opsora_mcp_v2.subprocess, "Popen", return_value=proc) as popen:
            client.connect_all()

        argv = popen.call_args[0][0]
        assert argv == ["python", "server.py", "--name", "my server", "--flag"]


# ---------------------------------------------------------------------------
# HTTP connection
# ---------------------------------------------------------------------------


class TestConnectHttp:
    def _http_response(self, payload: dict) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    def test_connect_http_success(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="http", transport="http",
                              url="http://localhost:8080")
        client.servers = [server]

        responses = [
            self._http_response({"ok": True}),  # initialize POST
            self._http_response({"tools": [{"name": "http_tool",
                                            "description": "HTTP tool",
                                            "inputSchema": {}}]}),
            self._http_response({"resources": []}),
        ]
        with patch.object(opsora_mcp_v2, "urlopen",
                          side_effect=responses) as urlopen_mock:
            client.connect_all()

        assert server.connected is True
        assert len(server.tools) == 1
        assert server.tools[0].name == "mcp__http__http_tool"
        assert urlopen_mock.call_count == 3

    def test_connect_http_failure(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="http", transport="http",
                              url="http://localhost:8080")
        client.servers = [server]

        with patch.object(opsora_mcp_v2, "urlopen",
                          side_effect=OSError("Connection refused")):
            client.connect_all()

        # initialize POST failed → _http_post returned error dict, but the
        # client still marks connected only after initialize succeeds; with
        # a hard OSError the discovery yields nothing.
        assert server.tools == []


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------


class TestCallTool:
    def _connected_stdio_client(self) -> tuple[MCPClient_v2, MCPServer_v2]:
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        server.tools = [MCPTool(name="mcp__test__mytool", description="Test tool",
                                input_schema={}, server_name="test")]
        client.servers = [server]
        return client, server

    def test_call_tool_full_stdio(self):
        client, server = self._connected_stdio_client()
        server.process = _stdio_mock([
            {"result": {"content": [{"type": "text", "text": "Tool result"}]}},
        ])
        result = client.call_tool_full("mcp__test__mytool", {"arg": "value"})
        assert result == "Tool result"

    def test_call_tool_full_error_response(self):
        client, server = self._connected_stdio_client()
        server.process = _stdio_mock([
            {"error": {"code": -32600, "message": "Invalid request"}},
        ])
        result = client.call_tool_full("mcp__test__mytool", {"arg": "value"})
        assert "Invalid request" in result

    def test_call_tool_full_invalid_name(self):
        client = MCPClient_v2()
        assert "Invalid MCP tool name" in client.call_tool_full("invalid_name", {})
        assert "Invalid MCP tool name" in client.call_tool_full("mcp__only", {})
        assert "Invalid MCP tool name" in client.call_tool_full("mcp____tool", {})
        assert "Invalid MCP tool name" in client.call_tool_full("notmcp__s__t", {})

    def test_call_tool_not_connected(self):
        client = MCPClient_v2()
        client.servers = [MCPServer_v2(name="test", transport="stdio",
                                       command="cmd", connected=False)]
        result = client.call_tool_full("mcp__test__mytool", {})
        assert "tidak terhubung" in result

    def test_call_tool_unknown_server(self):
        client = MCPClient_v2()
        result = client.call_tool_full("mcp__ghost__tool", {})
        assert "ghost" in result

    def test_call_tool_http(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="http", transport="http",
                              url="http://localhost:8080", connected=True)
        server.tools = [MCPTool(name="mcp__http__tool", description="Test",
                                input_schema={}, server_name="http")]
        client.servers = [server]

        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"content": [{"type": "text", "text": "HTTP tool result"}]}
        ).encode("utf-8")
        resp.__enter__.return_value = resp

        with patch.object(opsora_mcp_v2, "urlopen", return_value=resp):
            result = client.call_tool_full("mcp__http__tool", {"param": "value"})

        assert result == "HTTP tool result"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_stdio_alive(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="s", transport="stdio", command="cmd",
                              connected=True)
        proc = MagicMock()
        proc.poll.return_value = None  # still running
        server.process = proc
        client.servers = [server]

        results = client.health_check()
        assert results == {"s": "ok"}
        assert server.connected is True
        assert server.last_health_check > 0

    def test_stdio_dead_marks_disconnected(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="s", transport="stdio", command="cmd",
                              connected=True)
        proc = MagicMock()
        proc.poll.return_value = 1  # exited
        server.process = proc
        client.servers = [server]

        results = client.health_check()
        assert results == {"s": "dead"}
        assert server.connected is False

    def test_http_reachable(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="h", transport="http",
                              url="http://localhost:8080", connected=True)
        client.servers = [server]

        resp = MagicMock()
        resp.__enter__.return_value = resp
        with patch.object(opsora_mcp_v2, "urlopen", return_value=resp):
            results = client.health_check()
        assert results == {"h": "ok"}

    def test_http_unreachable_marks_disconnected(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="h", transport="http",
                              url="http://localhost:8080", connected=True)
        client.servers = [server]

        with patch.object(opsora_mcp_v2, "urlopen",
                          side_effect=OSError("no route")):
            results = client.health_check()
        assert results == {"h": "unreachable"}
        assert server.connected is False


# ---------------------------------------------------------------------------
# Aggregation / conversion
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_get_all_tools_only_connected(self):
        client = MCPClient_v2()
        s1 = MCPServer_v2(name="s1", transport="stdio", command="cmd",
                          connected=True)
        s1.tools = [MCPTool(name="mcp__s1__tool1", description="",
                            input_schema={}, server_name="s1")]
        s2 = MCPServer_v2(name="s2", transport="stdio", command="cmd",
                          connected=False)
        s2.tools = [MCPTool(name="mcp__s2__tool1", description="",
                            input_schema={}, server_name="s2")]
        client.servers = [s1, s2]

        tools = client.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "mcp__s1__tool1"

    def test_to_openai_tools_format(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        server.tools = [MCPTool(
            name="mcp__test__mytool",
            description="A test tool",
            input_schema={"type": "object",
                          "properties": {"arg": {"type": "string"}}},
            server_name="test",
        )]
        client.servers = [server]

        openai_tools = client.to_openai_tools()
        assert len(openai_tools) == 1
        fn = openai_tools[0]["function"]
        assert openai_tools[0]["type"] == "function"
        assert fn["name"] == "mcp__test__mytool"
        assert fn["description"] == "A test tool"
        assert fn["parameters"]["properties"]["arg"]["type"] == "string"

    def test_to_openai_tools_truncates_long_description(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        server.tools = [MCPTool(name="mcp__test__t", description="x" * 5000,
                                input_schema={}, server_name="test")]
        client.servers = [server]

        fn = client.to_openai_tools()[0]["function"]
        assert len(fn["description"]) == 1024

    def test_to_openai_tools_empty_schema_default(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        server.tools = [MCPTool(name="mcp__test__t", description="",
                                input_schema={}, server_name="test")]
        client.servers = [server]

        fn = client.to_openai_tools()[0]["function"]
        assert fn["parameters"] == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_none_response(self):
        assert MCPClient_v2._extract_text(None) == "Tidak ada response."

    def test_error_dict(self):
        assert "boom" in MCPClient_v2._extract_text({"error": "boom"})

    def test_text_content_joined(self):
        resp = {"content": [
            {"type": "text", "text": "line1"},
            {"type": "image", "data": "..."},
            {"type": "text", "text": "line2"},
        ]}
        assert MCPClient_v2._extract_text(resp) == "line1\nline2"

    def test_content_without_text_falls_to_json(self):
        resp = {"content": [{"type": "image", "data": "abc"}]}
        out = MCPClient_v2._extract_text(resp)
        assert "image" in out  # JSON dump of the whole response

    def test_non_dict_response_stringified(self):
        assert MCPClient_v2._extract_text("plain") == "plain"


# ---------------------------------------------------------------------------
# stdio JSON-RPC framing
# ---------------------------------------------------------------------------


class TestSendStdio:
    def _client_with_process(self) -> tuple[MCPClient_v2, MCPServer_v2, MagicMock]:
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd")
        proc = _stdio_mock([{"result": {"ok": True}}])
        server.process = proc
        return client, server, proc

    def test_request_written_with_content_length_frame(self):
        client, server, proc = self._client_with_process()
        result = client._send_stdio(server, "test_method", {"param": "value"})

        assert result == {"ok": True}
        written = proc.stdin.write.call_args[0][0]
        header, _, body = written.partition(b"\r\n\r\n")
        assert header == b"Content-Length: " + str(len(body)).encode("ascii")
        request = json.loads(body.decode("utf-8"))
        assert request["method"] == "test_method"
        assert request["params"] == {"param": "value"}
        assert request["jsonrpc"] == "2.0"
        assert "id" in request

    def test_notification_has_no_id_and_no_read(self):
        client, server, proc = self._client_with_process()
        result = client._send_stdio(server, "notifications/initialized", {},
                                    is_notification=True)
        assert result is None
        written = proc.stdin.write.call_args[0][0]
        body = written.partition(b"\r\n\r\n")[2]
        request = json.loads(body.decode("utf-8"))
        assert "id" not in request

    def test_no_process_returns_none(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd")
        server.process = None
        assert client._send_stdio(server, "test", {}) is None

    def test_broken_pipe_marks_disconnected(self):
        client, server, proc = self._client_with_process()
        server.connected = True
        proc.stdin.write.side_effect = BrokenPipeError("gone")
        result = client._send_stdio(server, "test", {})
        assert result is None
        assert server.connected is False

    def test_error_response_extracted(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd")
        server.process = _stdio_mock([{"error": {"message": "Failed"}}])
        result = client._send_stdio(server, "test", {})
        assert result == {"error": "Failed"}

    def test_bare_line_fallback_without_content_length(self):
        """Servers that skip framing and write a bare JSON line still parse."""
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd")
        proc = MagicMock()
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stderr = MagicMock()
        proc.stderr.readline.return_value = b""
        # First readline: empty header section ends immediately (cl stays 0),
        # then the bare JSON line is read.
        proc.stdout.readline.side_effect = [
            b"\r\n",
            json.dumps({"result": {"bare": True}}).encode("utf-8"),
        ]
        server.process = proc
        result = client._send_stdio(server, "test", {})
        assert result == {"bare": True}


# ---------------------------------------------------------------------------
# Disconnect / status rendering
# ---------------------------------------------------------------------------


class TestDisconnectAndStatus:
    def test_disconnect_all_terminates(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.return_value = None
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.readline.return_value = b""
        server.process = proc
        client.servers = [server]

        client.disconnect_all()

        assert server.connected is False
        proc.terminate.assert_called()

    def test_disconnect_all_kill_on_timeout(self):
        client = MCPClient_v2()
        server = MCPServer_v2(name="test", transport="stdio", command="cmd",
                              connected=True)
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.readline.return_value = b""
        server.process = proc
        client.servers = [server]

        client.disconnect_all()

        proc.kill.assert_called()

    def test_render_status_table(self):
        client = MCPClient_v2()
        s1 = MCPServer_v2(name="connected", transport="stdio", command="cmd",
                          connected=True)
        s1.tools = [MCPTool(name="t1", description="", input_schema={},
                            server_name="connected")]
        s2 = MCPServer_v2(name="disconnected", transport="http",
                          url="http://x", connected=False)
        client.servers = [s1, s2]

        table = client.render_status()
        assert isinstance(table, opsora_mcp_v2.Table)
        assert table.row_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
