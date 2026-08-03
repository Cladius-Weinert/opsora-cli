#!/usr/bin/env python3
"""
Opsora Telegram MCP Server
Lightweight Telegram MCP server using Telethon - no heavy dependencies.
Implements MCP JSON-RPC 2.0 over stdio.
"""
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s: %(message)s")
log = logging.getLogger("tg-mcp")

SESSION_PATH = "/root/.telegram-mcp/opsora"
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")

client = None

def get_client():
    global client
    if client is None:
        if not API_ID or not API_HASH:
            raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")
        from telethon import TelegramClient
        client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    return client

# --- MCP Protocol (JSON-RPC 2.0 over stdio) ---

def read_message():
    """Read a JSON-RPC message from stdin (Content-Length header format)"""
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

def send_message(msg):
    """Write a JSON-RPC message to stdout"""
    body = json.dumps(msg, ensure_ascii=False)
    header = f"Content-Length: {len(body.encode())}\r\n\r\n"
    sys.stdout.write(header + body)
    sys.stdout.flush()

def send_response(id, result):
    send_message({"jsonrpc": "2.0", "id": id, "result": result})

def send_error(id, code, message):
    send_message({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})

# --- Tools Definition ---

TOOLS = [
    {
        "name": "telegram_list_chats",
        "description": "List recent Telegram chats (dialogs). Returns chat ID, title, and last message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max number of chats (default 20)", "default": 20}
            }
        }
    },
    {
        "name": "telegram_send_message",
        "description": "Send a text message to a Telegram chat by chat ID or username.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Chat ID (number), username, or phone number"},
                "message": {"type": "string", "description": "Message text to send"}
            },
            "required": ["chat", "message"]
        }
    },
    {
        "name": "telegram_get_messages",
        "description": "Get recent messages from a Telegram chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Chat ID, username, or phone number"},
                "limit": {"type": "integer", "description": "Max messages (default 10)", "default": 10}
            },
            "required": ["chat"]
        }
    },
    {
        "name": "telegram_search_messages",
        "description": "Search messages in a Telegram chat or globally.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "chat": {"type": "string", "description": "Optional: search in specific chat"},
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "telegram_get_contacts",
        "description": "List Telegram contacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max contacts (default 50)", "default": 50}
            }
        }
    },
    {
        "name": "telegram_get_me",
        "description": "Get your Telegram profile info.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "telegram_forward_message",
        "description": "Forward a message from one chat to another.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_chat": {"type": "string", "description": "Source chat ID or username"},
                "message_id": {"type": "integer", "description": "ID of message to forward"},
                "to_chat": {"type": "string", "description": "Destination chat ID or username"}
            },
            "required": ["from_chat", "message_id", "to_chat"]
        }
    },
    {
        "name": "telegram_delete_message",
        "description": "Delete a message from a chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Chat ID or username"},
                "message_id": {"type": "integer", "description": "Message ID to delete"}
            },
            "required": ["chat", "message_id"]
        }
    }
]

# --- Tool Implementations ---

async def tool_list_chats(args):
    await ensure_connected()
    c = get_client()
    limit = args.get("limit", 20)
    dialogs = await c.get_dialogs(limit=limit)
    chats = []
    for d in dialogs:
        chats.append({
            "id": d.id,
            "title": d.title or d.name or str(d.id),
            "type": "group" if d.is_group else "channel" if d.is_channel else "private",
            "unread": d.unread_count,
            "last_message": d.message.text[:200] if d.message and d.message.text else None,
            "date": str(d.message.date) if d.message else None
        })
    return {"content": [{"type": "text", "text": json.dumps(chats, ensure_ascii=False, indent=2)}]}

async def tool_send_message(args):
    await ensure_connected()
    c = get_client()
    chat = args["chat"]
    message = args["message"]
    try:
        entity = await c.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    except Exception:
        entity = chat
    msg = await c.send_message(entity, message)
    return {"content": [{"type": "text", "text": f"Sent message (ID: {msg.id}) to {chat}"}]}

async def tool_get_messages(args):
    await ensure_connected()
    c = get_client()
    chat = args["chat"]
    limit = args.get("limit", 10)
    try:
        entity = await c.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    except Exception:
        entity = chat
    messages = await c.get_messages(entity, limit=limit)
    result = []
    for m in messages:
        result.append({
            "id": m.id,
            "from": str(m.sender_id) if m.sender_id else None,
            "text": m.text or "",
            "date": str(m.date),
            "reply_to": m.reply_to_msg_id
        })
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

async def tool_search_messages(args):
    await ensure_connected()
    c = get_client()
    query = args["query"]
    limit = args.get("limit", 10)
    chat = args.get("chat")
    if chat:
        try:
            entity = await c.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
        except Exception:
            entity = chat
        messages = await c.get_messages(entity, limit=limit, search=query)
    else:
        messages = []
        async for dialog in c.iter_dialogs():
            msgs = await c.get_messages(dialog.id, limit=5, search=query)
            messages.extend(msgs)
            if len(messages) >= limit:
                messages = messages[:limit]
                break
    result = []
    for m in messages:
        result.append({
            "id": m.id,
            "chat_id": m.chat_id,
            "from": str(m.sender_id) if m.sender_id else None,
            "text": (m.text or "")[:300],
            "date": str(m.date)
        })
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

async def tool_get_contacts(args):
    await ensure_connected()
    c = get_client()
    limit = args.get("limit", 50)
    contacts = await c.get_contacts()
    result = []
    for contact in contacts[:limit]:
        result.append({
            "id": contact.id,
            "name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
            "username": contact.username,
            "phone": contact.phone
        })
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}

async def tool_get_me(args):
    await ensure_connected()
    c = get_client()
    me = await c.get_me()
    info = {
        "id": me.id,
        "first_name": me.first_name,
        "last_name": me.last_name,
        "username": me.username,
        "phone": me.phone,
        "premium": me.premium
    }
    return {"content": [{"type": "text", "text": json.dumps(info, ensure_ascii=False, indent=2)}]}

async def tool_forward_message(args):
    await ensure_connected()
    c = get_client()
    from_chat = args["from_chat"]
    msg_id = args["message_id"]
    to_chat = args["to_chat"]
    try:
        from_entity = await c.get_entity(int(from_chat) if from_chat.lstrip("-").isdigit() else from_chat)
    except Exception:
        from_entity = from_chat
    try:
        to_entity = await c.get_entity(int(to_chat) if to_chat.lstrip("-").isdigit() else to_chat)
    except Exception:
        to_entity = to_chat
    await c.forward_messages(to_entity, msg_id, from_entity)
    return {"content": [{"type": "text", "text": f"Forwarded message {msg_id} from {from_chat} to {to_chat}"}]}

async def tool_delete_message(args):
    await ensure_connected()
    c = get_client()
    chat = args["chat"]
    msg_id = args["message_id"]
    try:
        entity = await c.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    except Exception:
        entity = chat
    await c.delete_messages(entity, msg_id)
    return {"content": [{"type": "text", "text": f"Deleted message {msg_id} from {chat}"}]}

TOOL_HANDLERS = {
    "telegram_list_chats": tool_list_chats,
    "telegram_send_message": tool_send_message,
    "telegram_get_messages": tool_get_messages,
    "telegram_search_messages": tool_search_messages,
    "telegram_get_contacts": tool_get_contacts,
    "telegram_get_me": tool_get_me,
    "telegram_forward_message": tool_forward_message,
    "telegram_delete_message": tool_delete_message,
}

# --- Main Loop ---

async def handle_request(msg):
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        return send_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "opsora-telegram", "version": "1.0.0"}
        })

    elif method == "notifications/initialized":
        return  # No response needed for notifications

    elif method == "tools/list":
        return send_response(msg_id, {"tools": TOOLS})

    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if not handler:
            return send_error(msg_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = await handler(tool_args)
            return send_response(msg_id, result)
        except Exception as e:
            log.error(f"Tool error: {e}")
            return send_error(msg_id, -32000, str(e))

    elif method == "ping":
        return send_response(msg_id, {})

    else:
        return send_error(msg_id, -32601, f"Unknown method: {method}")

async def ensure_connected():
    """Lazily connect to Telegram on first tool use"""
    c = get_client()
    if not c.is_connected():
        await c.connect()
        if not await c.is_user_authorized():
            raise Exception("Not authorized! Run telegram_auth.py first.")
        me = await c.get_me()
        log.warning(f"Connected as {me.first_name} (@{me.username})")

async def main():
    # Start MCP protocol immediately — don't block on Telegram connect
    while True:
        try:
            msg = read_message()
            if msg is None:
                break
            await handle_request(msg)
        except Exception as e:
            log.error(f"Error: {e}")
            break

    c = get_client()
    if c.is_connected():
        await c.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
