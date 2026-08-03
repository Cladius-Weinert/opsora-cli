#!/usr/bin/env python3
"""MCP Server — Microsoft Outlook / Graph API.

Device Code Flow authentication (no Azure AD app registration needed).
Works on headless environments (Termux, SSH, containers).

Provides:
- Outlook Email: list, read, search, send, mark read/unread, delete
- Calendar: list events, create event
- OneDrive: list files, search
- Contacts: list contacts

Run via stdio transport.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Any

# Microsoft public client for device code flow (multi-tenant)
CLIENT_ID = "29d9ed98-a469-4536-ade2-f981bc1d605e"
DEVICE_CODE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

SCOPES = (
    "Mail.Read Mail.ReadWrite Mail.Send "
    "Calendars.Read Calendars.ReadWrite "
    "Files.Read Files.ReadWrite "
    "Contacts.Read User.Read offline_access"
)

TOKEN_FILE = os.path.expanduser("~/.outlook-mcp-tokens.json")
TOKEN_CACHE: dict | None = None


# ── Auth ──────────────────────────────────────────────────────────

def load_tokens() -> dict | None:
    global TOKEN_CACHE
    if TOKEN_CACHE and TOKEN_CACHE.get("access_token"):
        exp = TOKEN_CACHE.get("expires_at", 0)
        if time.time() < exp - 60:
            return TOKEN_CACHE
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE) as f:
                data = json.load(f)
            if data.get("access_token") and time.time() < data.get("expires_at", 0) - 60:
                TOKEN_CACHE = data
                return data
            # Try refresh
            if data.get("refresh_token"):
                return refresh_token(data["refresh_token"])
    except Exception:
        pass
    return None


def save_tokens(tokens: dict):
    global TOKEN_CACHE
    tokens["expires_at"] = time.time() + tokens.get("expires_in", 3600)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)
    os.chmod(TOKEN_FILE, 0o600)
    TOKEN_CACHE = tokens


def refresh_token(refresh: str) -> dict | None:
    try:
        body = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "scope": SCOPES,
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
        save_tokens(tokens)
        return tokens
    except Exception:
        return None


def device_code_login() -> str:
    """Start device code flow, return instructions for user."""
    body = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "scope": SCOPES,
    }).encode()
    req = urllib.request.Request(DEVICE_CODE_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    device_code = data["device_code"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    msg = (
        f"🔐 Microsoft Outlook Login\n\n"
        f"1. Buka URL ini di browser:\n   {verification_uri}\n\n"
        f"2. Masukkan kode: {user_code}\n\n"
        f"3. Login dengan akun Microsoft/Outlook kamu\n\n"
        f"Kode berlaku {expires_in // 60} menit. Menunggu approval..."
    )

    # Poll for token
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        poll_body = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        }).encode()
        try:
            poll_req = urllib.request.Request(TOKEN_URL, data=poll_body, method="POST")
            with urllib.request.urlopen(poll_req, timeout=15) as poll_resp:
                tokens = json.loads(poll_resp.read())
            save_tokens(tokens)
            return msg + "\n\n✅ Login berhasil! Token tersimpan."
        except urllib.error.HTTPError as e:
            err_body = json.loads(e.read())
            error = err_body.get("error", "")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            elif error == "expired_token":
                return msg + "\n\n❌ Kode expired. Coba login ulang."
            elif error == "authorization_declined":
                return msg + "\n\n❌ Login ditolak."
            else:
                return msg + f"\n\n❌ Error: {error} - {err_body.get('error_description', '')}"
        except Exception as e:
            continue

    return msg + "\n\n❌ Timeout. Coba login ulang."


def get_auth_header() -> dict:
    tokens = load_tokens()
    if not tokens:
        return {}
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def graph_get(path: str, params: dict | None = None) -> dict:
    headers = get_auth_header()
    if not headers:
        return {"error": "Not authenticated. Run outlook_login first."}
    url = GRAPH_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def graph_post(path: str, data: dict) -> dict:
    headers = get_auth_header()
    headers["Content-Type"] = "application/json"
    if not headers.get("Authorization"):
        return {"error": "Not authenticated. Run outlook_login first."}
    url = GRAPH_BASE + path
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 204:
                return {"status": "ok"}
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:500]
        return {"error": f"HTTP {e.code}: {body_text}"}
    except Exception as e:
        return {"error": str(e)}


def graph_patch(path: str, data: dict) -> dict:
    headers = get_auth_header()
    headers["Content-Type"] = "application/json"
    if not headers.get("Authorization"):
        return {"error": "Not authenticated. Run outlook_login first."}
    url = GRAPH_BASE + path
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 204:
                return {"status": "ok"}
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:500]
        return {"error": f"HTTP {e.code}: {body_text}"}
    except Exception as e:
        return {"error": str(e)}


def graph_delete(path: str) -> dict:
    headers = get_auth_header()
    if not headers.get("Authorization"):
        return {"error": "Not authenticated. Run outlook_login first."}
    url = GRAPH_BASE + path
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"status": "ok"}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")[:500]
        return {"error": f"HTTP {e.code}: {body_text}"}
    except Exception as e:
        return {"error": str(e)}


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "outlook_login",
        "description": "Login to Microsoft/Outlook account using Device Code Flow. Returns a URL and code to enter in browser.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "outlook_auth_status",
        "description": "Check if currently authenticated with Microsoft/Outlook.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "outlook_mail_list",
        "description": "List recent emails from Outlook inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Folder name: inbox, sentitems, drafts, junkemail, deleteditems (default: inbox)"},
                "count": {"type": "integer", "description": "Number of emails (1-50, default 10)"},
                "unread_only": {"type": "boolean", "description": "Only show unread emails"}
            }
        }
    },
    {
        "name": "outlook_mail_read",
        "description": "Read a specific email by ID. Returns full body.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Email message ID"}
            },
            "required": ["message_id"]
        }
    },
    {
        "name": "outlook_mail_search",
        "description": "Search emails by keyword. Searches subject, body, sender.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword"},
                "count": {"type": "integer", "description": "Max results (1-50, default 10)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "outlook_mail_send",
        "description": "Send an email via Outlook.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address(es), comma-separated"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                "cc": {"type": "string", "description": "CC recipients (optional)"},
                "is_html": {"type": "boolean", "description": "Body is HTML (default false)"}
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "outlook_mail_mark_read",
        "description": "Mark an email as read or unread.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Email message ID"},
                "is_read": {"type": "boolean", "description": "True = mark as read, False = mark as unread"}
            },
            "required": ["message_id", "is_read"]
        }
    },
    {
        "name": "outlook_mail_delete",
        "description": "Delete (move to Deleted Items) an email.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Email message ID"}
            },
            "required": ["message_id"]
        }
    },
    {
        "name": "outlook_calendar_list",
        "description": "List upcoming calendar events.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of events (1-50, default 10)"},
                "days_ahead": {"type": "integer", "description": "Days ahead to look (default 7)"}
            }
        }
    },
    {
        "name": "outlook_calendar_create",
        "description": "Create a new calendar event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start time (ISO 8601, e.g. 2026-08-02T10:00:00)"},
                "end": {"type": "string", "description": "End time (ISO 8601)"},
                "location": {"type": "string", "description": "Location (optional)"},
                "body": {"type": "string", "description": "Event description (optional)"},
                "attendees": {"type": "string", "description": "Attendee emails, comma-separated (optional)"}
            },
            "required": ["subject", "start", "end"]
        }
    },
    {
        "name": "outlook_contacts_list",
        "description": "List Outlook contacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of contacts (1-50, default 10)"}
            }
        }
    },
    {
        "name": "outlook_onedrive_list",
        "description": "List files in OneDrive root or specified folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path (default: root). E.g. '/Documents'"}
            }
        }
    },
    {
        "name": "outlook_onedrive_search",
        "description": "Search files in OneDrive.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "outlook_profile",
        "description": "Get the authenticated user's profile info (name, email, etc).",
        "inputSchema": {"type": "object", "properties": {}}
    },
]


# ── Tool handlers ─────────────────────────────────────────────────

def fmt_email(e: dict) -> str:
    """Format an email for display."""
    subj = e.get("subject", "(no subject)")
    frm = e.get("from", {}).get("emailAddress", {}).get("address", "unknown")
    frm_name = e.get("from", {}).get("emailAddress", {}).get("name", "")
    date = e.get("receivedDateTime", "")[:16]
    preview = e.get("bodyPreview", "")[:120]
    read = "📖" if e.get("isRead") else "📩"
    att = " 📎" if e.get("hasAttachments") else ""
    imp = " ‼️" if e.get("importance") == "high" else ""
    return f"{read}{imp}{att} [{date}] {subj}\n   From: {frm_name} <{frm}>\n   {preview}"


def handle_tool(name: str, args: dict) -> str:
    if name == "outlook_login":
        return device_code_login()

    elif name == "outlook_auth_status":
        tokens = load_tokens()
        if tokens:
            remaining = int(tokens.get("expires_at", 0) - time.time())
            return json.dumps({"authenticated": True, "token_expires_in": f"{remaining}s", "has_refresh": bool(tokens.get("refresh_token"))})
        return json.dumps({"authenticated": False, "message": "Run outlook_login to authenticate"})

    elif name == "outlook_mail_list":
        folder = args.get("folder", "inbox")
        count = min(args.get("count", 10), 50)
        params = {"$top": count, "$orderby": "receivedDateTime desc",
                  "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,importance,isRead"}
        if args.get("unread_only"):
            params["$filter"] = "isRead eq false"
        result = graph_get(f"/me/mailFolders/{folder}/messages", params)
        if "error" in result:
            return json.dumps(result)
        emails = result.get("value", [])
        lines = [f"📬 {folder.capitalize()} ({len(emails)} emails):\n"]
        for e in emails:
            lines.append(fmt_email(e))
            lines.append(f"   ID: {e.get('id', 'N/A')}\n")
        return "\n".join(lines)

    elif name == "outlook_mail_read":
        mid = args["message_id"]
        result = graph_get(f"/me/messages/{mid}", {"$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,importance,isRead,internetMessageHeaders"})
        if "error" in result:
            return json.dumps(result)
        subj = result.get("subject", "(no subject)")
        frm = result.get("from", {}).get("emailAddress", {})
        to_list = [r.get("emailAddress", {}).get("address", "") for r in result.get("toRecipients", [])]
        date = result.get("receivedDateTime", "")[:19]
        body = result.get("body", {}).get("content", "")
        content_type = result.get("body", {}).get("contentType", "text")
        return f"Subject: {subj}\nFrom: {frm.get('name','')} <{frm.get('address','')}>\nTo: {', '.join(to_list)}\nDate: {date}\n\n{body[:3000]}"

    elif name == "outlook_mail_search":
        q = args["query"]
        count = min(args.get("count", 10), 50)
        result = graph_get("/me/messages", {"$search": f'"{q}"', "$top": count, "$orderby": "receivedDateTime desc",
                                            "$select": "id,subject,from,receivedDateTime,bodyPreview,hasAttachments,importance,isRead"})
        if "error" in result:
            return json.dumps(result)
        emails = result.get("value", [])
        lines = [f"🔍 Search results for '{q}' ({len(emails)} emails):\n"]
        for e in emails:
            lines.append(fmt_email(e))
            lines.append(f"   ID: {e.get('id', 'N/A')}\n")
        return "\n".join(lines) if emails else f"No emails found for '{q}'"

    elif name == "outlook_mail_send":
        to_addrs = [a.strip() for a in args["to"].split(",")]
        to_recipients = [{"emailAddress": {"address": a}} for a in to_addrs]
        msg = {
            "subject": args["subject"],
            "body": {"contentType": "HTML" if args.get("is_html") else "Text", "content": args["body"]},
            "toRecipients": to_recipients,
        }
        if args.get("cc"):
            cc_addrs = [a.strip() for a in args["cc"].split(",")]
            msg["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_addrs]
        result = graph_post("/me/sendMail", {"message": msg})
        if "error" in result:
            return json.dumps(result)
        return f"✅ Email sent to {args['to']}\nSubject: {args['subject']}"

    elif name == "outlook_mail_mark_read":
        mid = args["message_id"]
        result = graph_patch(f"/me/messages/{mid}", {"isRead": args["is_read"]})
        status = "read" if args["is_read"] else "unread"
        return f"✅ Email marked as {status}" if "error" not in result else json.dumps(result)

    elif name == "outlook_mail_delete":
        mid = args["message_id"]
        result = graph_delete(f"/me/messages/{mid}")
        return "✅ Email deleted" if "error" not in result else json.dumps(result)

    elif name == "outlook_calendar_list":
        count = min(args.get("count", 10), 50)
        days = args.get("days_ahead", 7)
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        start = now.isoformat()
        end = (now + timedelta(days=days)).isoformat()
        result = graph_get("/me/calendarView", {
            "startDateTime": start, "endDateTime": end,
            "$top": count, "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,location,bodyPreview,isAllDay,organizer"
        })
        if "error" in result:
            return json.dumps(result)
        events = result.get("value", [])
        lines = [f"📅 Upcoming events ({len(events)}):\n"]
        for ev in events:
            subj = ev.get("subject", "(no title)")
            s = ev.get("start", {}).get("dateTime", "")[:16]
            e_time = ev.get("end", {}).get("dateTime", "")[:16]
            loc = ev.get("location", {}).get("displayName", "")
            org = ev.get("organizer", {}).get("emailAddress", {}).get("name", "")
            lines.append(f"  📌 {subj}\n     {s} → {e_time}")
            if loc: lines.append(f"     📍 {loc}")
            if org: lines.append(f"     👤 {org}")
            lines.append(f"     ID: {ev.get('id', 'N/A')}\n")
        return "\n".join(lines) if events else "No upcoming events."

    elif name == "outlook_calendar_create":
        event = {
            "subject": args["subject"],
            "start": {"dateTime": args["start"], "timeZone": "UTC"},
            "end": {"dateTime": args["end"], "timeZone": "UTC"},
        }
        if args.get("location"):
            event["location"] = {"displayName": args["location"]}
        if args.get("body"):
            event["body"] = {"contentType": "Text", "content": args["body"]}
        if args.get("attendees"):
            addrs = [a.strip() for a in args["attendees"].split(",")]
            event["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in addrs]
        result = graph_post("/me/events", event)
        if "error" in result:
            return json.dumps(result)
        return f"✅ Event created: {args['subject']}\n{args['start']} → {args['end']}\nID: {result.get('id', 'N/A')}"

    elif name == "outlook_contacts_list":
        count = min(args.get("count", 10), 50)
        result = graph_get("/me/contacts", {"$top": count, "$select": "id,displayName,emailAddresses,phones,companyName"})
        if "error" in result:
            return json.dumps(result)
        contacts = result.get("value", [])
        lines = [f"👥 Contacts ({len(contacts)}):\n"]
        for c in contacts:
            name = c.get("displayName", "Unknown")
            emails = [e.get("address", "") for e in c.get("emailAddresses", [])]
            company = c.get("companyName", "")
            lines.append(f"  {name} — {', '.join(emails)}")
            if company: lines.append(f"     🏢 {company}")
            lines.append("")
        return "\n".join(lines) if contacts else "No contacts found."

    elif name == "outlook_onedrive_list":
        path = args.get("path", "")
        endpoint = f"/me/drive/root/children" if not path else f"/me/drive/root:{path}:/children"
        result = graph_get(endpoint, {"$top": 50, "$select": "id,name,size,lastModifiedDateTime,webUrl,folder,file"})
        if "error" in result:
            return json.dumps(result)
        items = result.get("value", [])
        lines = [f"📁 OneDrive {path or '/'} ({len(items)} items):\n"]
        for item in items:
            name = item.get("name", "?")
            size = item.get("size", 0)
            modified = item.get("lastModifiedDateTime", "")[:16]
            is_folder = "folder" in item
            icon = "📁" if is_folder else "📄"
            size_str = f"{size / 1024:.1f}KB" if size < 1048576 else f"{size / 1048576:.1f}MB"
            lines.append(f"  {icon} {name} ({size_str}, {modified})")
        return "\n".join(lines) if items else "Folder is empty."

    elif name == "outlook_onedrive_search":
        q = args["query"]
        result = graph_get(f"/me/drive/root/search(q='{urllib.parse.quote(q)}')", {"$top": 20, "$select": "id,name,size,lastModifiedDateTime,webUrl,folder,file"})
        if "error" in result:
            return json.dumps(result)
        items = result.get("value", [])
        lines = [f"🔍 OneDrive search '{q}' ({len(items)} results):\n"]
        for item in items:
            name = item.get("name", "?")
            is_folder = "folder" in item
            icon = "📁" if is_folder else "📄"
            lines.append(f"  {icon} {name}")
        return "\n".join(lines) if items else f"No files found for '{q}'"

    elif name == "outlook_profile":
        result = graph_get("/me", {"$select": "displayName,mail,userPrincipalName,jobTitle,officeLocation,companyName"})
        return json.dumps(result)

    return json.dumps({"error": f"Unknown tool: {name}"})


# ── MCP protocol ──────────────────────────────────────────────────

def handle_request(request: dict) -> dict:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "outlook-mcp", "version": "1.0.0"}
            }
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        args = request.get("params", {}).get("arguments", {})
        try:
            result = handle_tool(tool_name, args)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0"}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main():
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
            error_resp = {"jsonrpc": "2.0", "error": {"code": -32700, "message": str(e)}}
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
