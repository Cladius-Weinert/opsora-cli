"""Comprehensive tests for opsora_mcp.py MCP client."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, call
import json
import subprocess

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_mcp


class TestMCPTool:
    """Tests for MCPTool dataclass."""

    def test_tool_creation(self):
        tool = opsora_mcp.MCPTool(
            name="mcp__server__tool",
            description="Test tool",
            input_schema={"type": "object", "properties": {}},
            server_name="server"
        )
        assert tool.name == "mcp__server__tool"
        assert tool.description == "Test tool"
        assert tool.server_name == "server"


class TestMCPServer:
    """Tests for MCPServer dataclass."""

    def test_server_creation_stdio(self):
        server = opsora_mcp.MCPServer(
            name="test-server",
            transport="stdio",
            command="python server.py"
        )
        assert server.name == "test-server"
        assert server.transport == "stdio"
        assert server.command == "python server.py"
        assert server.tools == []
        assert server.connected is False

    def test_server_creation_http(self):
        server = opsora_mcp.MCPServer(
            name="http-server",
            transport="http",
            url="http://localhost:8080"
        )
        assert server.transport == "http"
        assert server.url == "http://localhost:8080"


class TestMCPClient:
    """Tests for MCPClient class."""

    @pytest.fixture
    def client(self):
        return opsora_mcp.MCPClient()

    def test_client_initialization(self, client):
        assert client.servers == []
        assert client._request_id == 0

    def test_load_config_no_file(self, client):
        """Test loading config when file doesn't exist."""
        with patch('pathlib.Path.is_file', return_value=False):
            client.load_config("/nonexistent.json")
            assert client.servers == []

    def test_load_config_invalid_json(self, client):
        """Test loading invalid JSON config."""
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', mock_open(read_data="not json")):
                client.load_config("/invalid.json")
                assert client.servers == []

    def test_load_config_valid(self, client):
        """Test loading valid config."""
        config = {
            "mcpServers": {
                "stdio-server": {"command": "python server.py", "env": {"KEY": "value"}},
                "http-server": {"url": "http://localhost:8080"}
            }
        }
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(config))):
                client.load_config("/valid.json")

        assert len(client.servers) == 2
        stdio_server = next(s for s in client.servers if s.name == "stdio-server")
        assert stdio_server.transport == "stdio"
        assert stdio_server.command == "python server.py"
        assert stdio_server.env == {"KEY": "value"}

        http_server = next(s for s in client.servers if s.name == "http-server")
        assert http_server.transport == "http"
        assert http_server.url == "http://localhost:8080"

    def test_load_config_missing_fields(self, client):
        """Test loading config with missing optional fields."""
        config = {"mcpServers": {"minimal": {}}}
        with patch('pathlib.Path.is_file', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(config))):
                client.load_config("/minimal.json")

        server = client.servers[0]
        assert server.name == "minimal"
        assert server.transport == "http"  # defaults to http when no command
        assert server.command == ""
        assert server.url == ""

    def test_connect_stdio_success(self, client):
        """Test successful stdio connection."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="echo test")
        client.servers = [server]

        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.stdout.readline.side_effect = [
            json.dumps({"result": {"protocolVersion": "2024-11-05"}}),  # initialize
            json.dumps({"result": {"tools": [{"name": "tool1", "description": "Tool 1", "inputSchema": {}}]}})  # tools/list
        ]

        with patch('subprocess.Popen', return_value=mock_process):
            client.connect()

        assert server.connected is True
        assert len(server.tools) == 1
        assert server.tools[0].name == "mcp__test__tool1"

    def test_connect_stdio_failure(self, client):
        """Test stdio connection failure."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="bad-command")
        client.servers = [server]

        with patch('subprocess.Popen', side_effect=Exception("Failed to start")):
            client.connect()

        assert server.connected is False

    def test_connect_http_success(self, client):
        """Test successful HTTP connection."""
        server = opsora_mcp.MCPServer(name="http", transport="http", url="http://localhost:8080")
        client.servers = [server]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "tools": [{"name": "http_tool", "description": "HTTP tool", "inputSchema": {}}]
        }).encode()

        with patch('urllib.request.urlopen', return_value=mock_response):
            client.connect()

        assert server.connected is True
        assert len(server.tools) == 1
        assert server.tools[0].name == "mcp__http__http_tool"

    def test_connect_http_failure(self, client):
        """Test HTTP connection failure."""
        server = opsora_mcp.MCPServer(name="http", transport="http", url="http://localhost:8080")
        client.servers = [server]

        with patch('urllib.request.urlopen', side_effect=Exception("Connection refused")):
            client.connect()

        assert server.connected is False

    def test_call_tool_stdio(self, client):
        """Test calling stdio MCP tool."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd", connected=True)
        server.tools = [opsora_mcp.MCPTool(
            name="mcp__test__mytool",
            description="Test tool",
            input_schema={},
            server_name="test"
        )]
        client.servers = [server]

        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline.return_value = json.dumps({
            "result": {"content": [{"type": "text", "text": "Tool result"}]}
        })
        server.process = mock_process

        result = client.call_tool("mcp__test__mytool", {"arg": "value"})

        assert result == "Tool result"

    def test_call_tool_stdio_error(self, client):
        """Test calling stdio MCP tool with error response."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd", connected=True)
        server.tools = [opsora_mcp.MCPTool(
            name="mcp__test__mytool",
            description="Test tool",
            input_schema={},
            server_name="test"
        )]
        client.servers = [server]

        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline.return_value = json.dumps({
            "error": {"code": -32600, "message": "Invalid request"}
        })
        server.process = mock_process

        result = client.call_tool("mcp__test__mytool", {"arg": "value"})

        assert "error" in result.lower() or "Error" in result

    def test_call_tool_not_connected(self, client):
        """Test calling tool on disconnected server."""
        result = client.call_tool("mcp__test__mytool", {})
        assert "not connected" in result

    def test_call_tool_invalid_name(self, client):
        """Test calling tool with invalid name format."""
        result = client.call_tool("invalid_name", {})
        assert "Invalid MCP tool name" in result

    def test_call_tool_http(self, client):
        """Test calling HTTP MCP tool."""
        server = opsora_mcp.MCPServer(name="http", transport="http", url="http://localhost:8080", connected=True)
        server.tools = [opsora_mcp.MCPTool(
            name="mcp__http__tool",
            description="Test",
            input_schema={},
            server_name="http"
        )]
        client.servers = [server]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "content": [{"type": "text", "text": "HTTP tool result"}]
        }).encode()

        with patch('urllib.request.urlopen', return_value=mock_response):
            result = client.call_tool("mcp__http__tool", {"param": "value"})

        assert result == "HTTP tool result"

    def test_get_all_tools(self, client):
        """Test getting all tools from connected servers."""
        server1 = opsora_mcp.MCPServer(name="s1", transport="stdio", command="cmd", connected=True)
        server1.tools = [opsora_mcp.MCPTool(name="mcp__s1__tool1", description="", input_schema={}, server_name="s1")]

        server2 = opsora_mcp.MCPServer(name="s2", transport="stdio", command="cmd", connected=False)
        server2.tools = [opsora_mcp.MCPTool(name="mcp__s2__tool1", description="", input_schema={}, server_name="s2")]

        client.servers = [server1, server2]

        tools = client.get_all_tools()
        assert len(tools) == 1
        assert tools[0].name == "mcp__s1__tool1"

    def test_to_openai_tools(self, client):
        """Test converting MCP tools to OpenAI format."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd", connected=True)
        server.tools = [opsora_mcp.MCPTool(
            name="mcp__test__mytool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"arg": {"type": "string"}}},
            server_name="test"
        )]
        client.servers = [server]

        openai_tools = client.to_openai_tools()

        assert len(openai_tools) == 1
        tool = openai_tools[0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "mcp__test__mytool"
        assert tool["function"]["description"] == "A test tool"
        assert tool["function"]["parameters"]["properties"]["arg"]["type"] == "string"

    def test_send_request_stdio(self, client):
        """Test sending JSON-RPC request to stdio server."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd")
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline.return_value = json.dumps({"result": {"ok": True}})
        server.process = mock_process

        result = client._send_request(server, "test_method", {"param": "value"})

        assert result == {"ok": True}
        mock_process.stdin.write.assert_called()
        written = mock_process.stdin.write.call_args[0][0]
        request = json.loads(written.strip())
        assert request["method"] == "test_method"
        assert request["params"] == {"param": "value"}
        assert request["jsonrpc"] == "2.0"

    def test_send_request_no_process(self, client):
        """Test sending request when process not available."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd")
        server.process = None

        result = client._send_request(server, "test", {})
        assert result is None

    def test_send_request_error_response(self, client):
        """Test handling error response."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd")
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()
        mock_process.stdout.readline.return_value = json.dumps({"error": {"message": "Failed"}})
        server.process = mock_process

        result = client._send_request(server, "test", {})
        assert result == {"error": {"message": "Failed"}}

    def test_disconnect_all(self, client):
        """Test disconnecting all servers."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd", connected=True)
        mock_process = MagicMock()
        mock_process.wait.return_value = None
        server.process = mock_process
        client.servers = [server]

        client.disconnect_all()

        assert server.connected is False
        mock_process.terminate.assert_called()

    def test_disconnect_all_kill_on_timeout(self, client):
        """Test killing process if terminate times out."""
        server = opsora_mcp.MCPServer(name="test", transport="stdio", command="cmd", connected=True)
        mock_process = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        server.process = mock_process
        client.servers = [server]

        client.disconnect_all()

        mock_process.kill.assert_called()

    def test_render_status(self, client):
        """Test rendering status table."""
        server1 = opsora_mcp.MCPServer(name="connected", transport="stdio", command="cmd", connected=True)
        server1.tools = [opsora_mcp.MCPTool(name="t1", description="", input_schema={}, server_name="connected")]

        server2 = opsora_mcp.MCPServer(name="disconnected", transport="http", url="http://x", connected=False)

        client.servers = [server1, server2]

        table = client.render_status()

        assert isinstance(table, opsora_mcp.Table)
        # Table should have rows for both servers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])