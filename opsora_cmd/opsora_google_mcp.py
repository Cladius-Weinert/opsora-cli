#!/usr/bin/env python3
"""MCP Server — Google Tools (Gmail, Drive, Calendar, Contacts).

Run via stdio transport. Qwen Code calls this as an MCP server.
"""

from __future__ import annotations

import json
import sys
from typing import Any

# Import Google tools
sys.path.insert(0, "/root/opsora-cli/cmd")
from opsora_google import (
    gmail_list, gmail_unread, gmail_search,
    drive_list, drive_search,
    calendar_events, google_status,
)

TOOLS = [
    {
        "name": "gmail_list",
        "description": "List recent Gmail inbox messages. Returns subject, sender, snippet, date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Account email. Options: jalankecil351@gmail.com, cladiusweinert05@gmail.com, nurma67066@gmail.com, cloudbitget@gmail.com. Empty = first available."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of messages (1-20, default 5)"
                }
            }
        }
    },
    {
        "name": "gmail_unread",
        "description": "Get unread email count. Empty email = all accounts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Account email or empty for all accounts"
                }
            }
        }
    },
    {
        "name": "gmail_search",
        "description": "Search Gmail messages with a query (same as Gmail search syntax).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "email": {
                    "type": "string",
                    "description": "Account email. Empty = first available"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (1-20, default 5)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "drive_list",
        "description": "List recent Google Drive files ordered by modified time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Account email. Empty = first available"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of files (1-20, default 10)"
                }
            }
        }
    },
    {
        "name": "drive_search",
        "description": "Search Google Drive files by name/keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "File name or keyword"},
                "email": {
                    "type": "string",
                    "description": "Account email. Empty = first available"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results (1-20, default 10)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "calendar_events",
        "description": "List upcoming Google Calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Account email. Empty = first available"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of events (1-20, default 5)"
                }
            }
        }
    },
    {
        "name": "google_status",
        "description": "Check OAuth token status and API access for Google accounts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Account email. Empty = all accounts"
                }
            }
        }
    },
]


def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "opsora-google-mcp",
                    "version": "1.0.0"
                }
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }

    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        args = request.get("params", {}).get("arguments", {})

        try:
            if tool_name == "gmail_list":
                result = gmail_list(args.get("email", ""), args.get("max_results", 5))
            elif tool_name == "gmail_unread":
                result = gmail_unread(args.get("email", ""))
            elif tool_name == "gmail_search":
                result = gmail_search(args.get("query", ""), args.get("email", ""), args.get("max_results", 5))
            elif tool_name == "drive_list":
                result = drive_list(args.get("email", ""), args.get("max_results", 10))
            elif tool_name == "drive_search":
                result = drive_search(args.get("query", ""), args.get("email", ""), args.get("max_results", 10))
            elif tool_name == "calendar_events":
                result = calendar_events(args.get("email", ""), args.get("max_results", 5))
            elif tool_name == "google_status":
                result = google_status(args.get("email", ""))
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0"}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """Run MCP server over stdio."""
    # Read JSON-RPC messages line by line
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except Exception as e:
            error_resp = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": str(e)}
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()