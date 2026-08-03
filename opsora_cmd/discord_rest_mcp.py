#!/usr/bin/env python3
"""
Discord REST-only MCP Server
No WebSocket gateway needed — uses Discord REST API directly via requests.
Lightweight, works in proot/Termux where discord.js WebSocket hangs.
"""
import sys
import json
import os
import logging
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s: %(message)s")
log = logging.getLogger("discord-rest-mcp")

TOKEN = os.environ.get("DISCORD_TOKEN", "")
BASE = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "OpsoraBot (1.0)",
}


def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Discord API {e.code}: {body}")


def send_message(args):
    channel = args["channel"]
    content = args["content"]
    embeds = args.get("embeds")
    data = {"content": content}
    if embeds:
        data["embeds"] = embeds
    result = api("POST", f"/channels/{channel}/messages", data)
    return {"content": [{"type": "text", "text": f"Sent message ID {result.get('id')} to channel {channel}"}]}


def list_guilds(args):
    guilds = api("GET", "/users/@me/guilds")
    lines = []
    for g in guilds:
        lines.append(f"- {g['name']} (ID: {g['id']}, owner: {g.get('owner', False)})")
    text = "\n".join(lines) if lines else "No guilds found."
    return {"content": [{"type": "text", "text": text}]}


def list_channels(args):
    guild_id = args["guild_id"]
    channels = api("GET", f"/guilds/{guild_id}/channels")
    lines = []
    for c in channels:
        ctype = "text" if c["type"] == 0 else "voice" if c["type"] == 2 else f"type-{c['type']}"
        lines.append(f"- #{c['name']} (ID: {c['id']}, {ctype})")
    text = "\n".join(lines) if lines else "No channels found."
    return {"content": [{"type": "text", "text": text}]}


def get_messages(args):
    channel = args["channel"]
    limit = args.get("limit", 10)
    msgs = api("GET", f"/channels/{channel}/messages?limit={limit}")
    lines = []
    for m in msgs:
        author = m.get("author", {}).get("username", "unknown")
        text = m.get("content", "")[:200]
        lines.append(f"[{m['id']}] {author}: {text}")
    result = "\n".join(lines) if lines else "No messages."
    return {"content": [{"type": "text", "text": result}]}


def create_embed(args):
    channel = args["channel"]
    title = args.get("title", "")
    description = args.get("description", "")
    color = args.get("color", 9124854)  # Opsora violet #8b5cf6
    fields = args.get("fields", [])
    embed = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    if args.get("thumbnail"):
        embed["thumbnail"] = {"url": args["thumbnail"]}
    if args.get("image"):
        embed["image"] = {"url": args["image"]}
    data = {"embeds": [embed]}
    result = api("POST", f"/channels/{channel}/messages", data)
    return {"content": [{"type": "text", "text": f"Sent embed to channel {channel} (msg ID: {result.get('id')})"}]}


def delete_message(args):
    channel = args["channel"]
    message_id = args["message_id"]
    api("DELETE", f"/channels/{channel}/messages/{message_id}")
    return {"content": [{"type": "text", "text": f"Deleted message {message_id}"}]}


def get_me(args):
    me = api("GET", "/users/@me")
    return {"content": [{"type": "text", "text": json.dumps(me, indent=2)}]}


TOOLS = [
    {
        "name": "discord_send_message",
        "description": "Send a text message to a Discord channel by channel ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Discord channel ID"},
                "content": {"type": "string", "description": "Message text"},
                "embeds": {"type": "array", "description": "Optional embed objects"}
            },
            "required": ["channel", "content"]
        }
    },
    {
        "name": "discord_list_guilds",
        "description": "List all Discord servers (guilds) the bot is in.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "discord_list_channels",
        "description": "List channels in a Discord server.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "guild_id": {"type": "string", "description": "Guild/server ID"}
            },
            "required": ["guild_id"]
        }
    },
    {
        "name": "discord_get_messages",
        "description": "Get recent messages from a Discord channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID"},
                "limit": {"type": "integer", "description": "Max messages (default 10)", "default": 10}
            },
            "required": ["channel"]
        }
    },
    {
        "name": "discord_create_embed",
        "description": "Send a rich embed message to a Discord channel (for marketing posts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID"},
                "title": {"type": "string", "description": "Embed title"},
                "description": {"type": "string", "description": "Embed description"},
                "color": {"type": "integer", "description": "Embed color (decimal, default: violet)"},
                "fields": {"type": "array", "description": "Embed fields [{name, value, inline}]"},
                "thumbnail": {"type": "string", "description": "Thumbnail URL"},
                "image": {"type": "string", "description": "Image URL"}
            },
            "required": ["channel"]
        }
    },
    {
        "name": "discord_delete_message",
        "description": "Delete a message from a Discord channel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID"},
                "message_id": {"type": "string", "description": "Message ID to delete"}
            },
            "required": ["channel", "message_id"]
        }
    },
    {
        "name": "discord_get_me",
        "description": "Get bot profile info.",
        "inputSchema": {"type": "object", "properties": {}}
    }
]

HANDLERS = {
    "discord_send_message": send_message,
    "discord_list_guilds": list_guilds,
    "discord_list_channels": list_channels,
    "discord_get_messages": get_messages,
    "discord_create_embed": create_embed,
    "discord_delete_message": delete_message,
    "discord_get_me": get_me,
}


# --- MCP Protocol ---

def read_message():
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line or line == "\r\n" or line == "\n":
            break
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()
    length = int(headers.get("content-length", 0))
    if length == 0:
        return None
    body = sys.stdin.read(length)
    return json.loads(body)


def write(msg):
    body = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(f"Content-Length: {len(body.encode())}\r\n\r\n{body}")
    sys.stdout.flush()


def respond(id, result):
    write({"jsonrpc": "2.0", "id": id, "result": result})


def error(id, code, message):
    write({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


def main():
    if not TOKEN:
        log.error("DISCORD_TOKEN not set!")
        sys.exit(1)

    while True:
        try:
            msg = read_message()
            if msg is None:
                break
            method = msg.get("method")
            mid = msg.get("id")

            if method == "initialize":
                respond(mid, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "opsora-discord-rest", "version": "1.0.0"}
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                respond(mid, {"tools": TOOLS})
            elif method == "tools/call":
                params = msg.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                handler = HANDLERS.get(name)
                if not handler:
                    error(mid, -32601, f"Unknown tool: {name}")
                else:
                    try:
                        result = handler(args)
                        respond(mid, result)
                    except Exception as e:
                        log.error(f"Tool error: {e}")
                        error(mid, -32000, str(e))
            elif method == "ping":
                respond(mid, {})
            else:
                error(mid, -32601, f"Unknown method: {method}")
        except Exception as e:
            log.error(f"Fatal: {e}")
            break


if __name__ == "__main__":
    main()
