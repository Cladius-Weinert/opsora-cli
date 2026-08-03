"""Opsora Google Tools — Gmail, Drive, Calendar, Contacts via OAuth2.

Integrasi dengan google_auth_manager.py untuk akses 4 akun Google.
Semua token OAuth sudah tersimpan di /root/.google_auth/tokens/
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

CONFIG_DIR = Path("/root/.google_auth")
TOKENS_DIR = CONFIG_DIR / "tokens"
CLIENT_CREDS = CONFIG_DIR / "client_creds.json"

ACCOUNTS = [
    "jalankecil351@gmail.com",
    "cladiusweinert05@gmail.com",
    "nurma67066@gmail.com",
    "cloudbitget@gmail.com",
]


def _load_client_creds() -> tuple[str, str]:
    """Load OAuth client credentials."""
    if not CLIENT_CREDS.exists():
        return "", ""
    try:
        with open(CLIENT_CREDS, "r") as f:
            data = json.loads(f.read())
    except Exception:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    return data.get("client_id", ""), data.get("client_secret", "")


def _load_tokens(email: str) -> Optional[dict]:
    """Load saved tokens for an account."""
    path = TOKENS_DIR / f"{email}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.loads(f.read())


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
    """Refresh an expired access token."""
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
            return tokens.get("access_token")
    except Exception:
        return None


def _get_valid_token(email: str) -> Optional[str]:
    """Get a valid access token, refreshing if needed."""
    client_id, client_secret = _load_client_creds()
    if not client_id:
        return None
    tokens = _load_tokens(email)
    if not tokens:
        return None
    if time.time() > tokens.get("expires_at", 0) - 60:
        rt = tokens.get("refresh_token")
        if not rt:
            return None
        new_at = _refresh_access_token(client_id, client_secret, rt)
        if new_at:
            tokens["access_token"] = new_at
            tokens["expires_at"] = time.time() + 3599
            save_path = TOKENS_DIR / f"{email}.json"
            save_path.write_text(json.dumps(tokens, indent=2))
            return new_at
        return None
    return tokens.get("access_token")


def _google_get(token: str, url: str) -> dict:
    """Make authenticated GET request to Google API."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _google_post(token: str, url: str, body: dict) -> dict:
    """Make authenticated POST request to Google API."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _token_error(target: str) -> str:
    """Error message when no valid OAuth token is available for an account.

    Covers both cases: akun tidak dikenal (no saved token file) dan
    token yang sudah tidak valid / gagal refresh.
    """
    return (
        f"❌ Token OAuth untuk '{target}' tidak valid atau akun tidak dikenal.\n"
        f"Akun yang tersedia: {', '.join(ACCOUNTS)}\n"
        f"Jalankan: python3 google_auth_manager.py authorize"
    )


# ── Public Tools ──

def gmail_list(email: str = "", max_results: int = 5) -> str:
    """List recent Gmail messages from inbox.

    Args:
        email: Account email (empty = first available)
        max_results: Number of messages to fetch (1-20)
    """
    target = email if email else ACCOUNTS[0]
    token = _get_valid_token(target)
    if not token:
        return _token_error(target)

    try:
        # Get message list
        data = _google_get(
            token,
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={min(max_results, 20)}&q=in:inbox"
        )
        messages = data.get("messages", [])
        if not messages:
            return f"📬 {target}: Tidak ada email di inbox."

        result = [f"📬 {target} — {len(messages)} email terbaru:\n"]
        for msg in messages[:max_results]:
            detail = _google_get(
                token,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
            )
            headers = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "?")
            date = headers.get("date", "?")
            snippet = detail.get("snippet", "")[:80]
            result.append(f"  ├ {subject}")
            result.append(f"  │  Dari: {sender}")
            result.append(f"  │  {snippet}")
            result.append(f"  │  {date}")
            result.append("")

        return "\n".join(result).strip()
    except Exception as e:
        return f"❌ Gagal baca Gmail: {e}"


def gmail_unread(email: str = "") -> str:
    """Get unread count for a Gmail account.

    Args:
        email: Account email (empty = all accounts)
    """
    targets = [email] if email else ACCOUNTS
    results = []

    for acct in targets:
        token = _get_valid_token(acct)
        if not token:
            results.append(f"  {acct}: ❌ Token OAuth tidak valid atau akun tidak dikenal")
            continue
        try:
            data = _google_get(
                token,
                "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=1&q=in:inbox%20is:unread"
            )
            count = data.get("resultSizeEstimate", 0)
            results.append(f"  {acct}: {count} unread")
        except Exception as e:
            results.append(f"  {acct}: ❌ {e}")

    return "📬 Unread count:\n" + "\n".join(results)


def gmail_search(query: str, email: str = "", max_results: int = 5) -> str:
    """Search Gmail messages.

    Args:
        query: Search query (same as Gmail search)
        email: Account email (empty = first available)
        max_results: Max results (1-20)
    """
    target = email if email else ACCOUNTS[0]
    token = _get_valid_token(target)
    if not token:
        return _token_error(target)

    try:
        q = urllib.parse.quote(query)
        data = _google_get(
            token,
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={min(max_results, 20)}&q={q}"
        )
        messages = data.get("messages", [])
        if not messages:
            return f"🔍 {target}: Tidak ada hasil untuk '{query}'."

        result = [f"🔍 {target} — '{query}' ({len(messages)} hasil):\n"]
        for msg in messages[:max_results]:
            detail = _google_get(
                token,
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
            )
            headers = {h["name"].lower(): h["value"] for h in detail.get("payload", {}).get("headers", [])}
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "?")
            snippet = detail.get("snippet", "")[:80]
            result.append(f"  ├ {subject}")
            result.append(f"  │  Dari: {sender}")
            result.append(f"  │  {snippet}")

        return "\n".join(result).strip()
    except Exception as e:
        return f"❌ Gagal search Gmail: {e}"


def drive_list(email: str = "", max_results: int = 10) -> str:
    """List recent Google Drive files.

    Args:
        email: Account email (empty = first available)
        max_results: Number of files (1-20)
    """
    target = email if email else ACCOUNTS[0]
    token = _get_valid_token(target)
    if not token:
        return _token_error(target)

    try:
        url = f"https://www.googleapis.com/drive/v3/files?pageSize={min(max_results, 20)}&fields=files(name,mimeType,modifiedTime,size)&orderBy=modifiedTime%20desc"
        data = _google_get(token, url)
        files = data.get("files", [])
        if not files:
            return f"📁 {target}: Tidak ada file."

        result = [f"📁 {target} — {len(files)} file terbaru:\n"]
        for f in files:
            name = f.get("name", "?")
            mime = f.get("mimeType", "")
            modified = f.get("modifiedTime", "?")[:10]
            size = f.get("size", 0)
            icon = "📄" if "document" in mime else "📊" if "spreadsheet" in mime else "📽️" if "presentation" in mime else "📁" if "folder" in mime else "📎"
            size_str = f"{int(size) // 1024}KB" if size else ""
            result.append(f"  {icon} {name}")
            result.append(f"     {modified}  {size_str}")

        return "\n".join(result).strip()
    except Exception as e:
        return f"❌ Gagal baca Drive: {e}"


def drive_search(query: str, email: str = "", max_results: int = 10) -> str:
    """Search Google Drive files by name.

    Args:
        query: File name or keyword to search
        email: Account email (empty = first available)
        max_results: Max results (1-20)
    """
    target = email if email else ACCOUNTS[0]
    token = _get_valid_token(target)
    if not token:
        return _token_error(target)

    try:
        q = urllib.parse.quote(f"name contains '{query}'")
        data = _google_get(
            token,
            f"https://www.googleapis.com/drive/v3/files?pageSize={min(max_results, 20)}&q={q}&fields=files(name,mimeType,modifiedTime,size)"
        )
        files = data.get("files", [])
        if not files:
            return f"🔍 {target}: Tidak ada file dengan '{query}'."

        result = [f"🔍 {target} — '{query}' ({len(files)} hasil):\n"]
        for f in files:
            name = f.get("name", "?")
            modified = f.get("modifiedTime", "?")[:10]
            result.append(f"  📄 {name} ({modified})")

        return "\n".join(result).strip()
    except Exception as e:
        return f"❌ Gagal search Drive: {e}"


def calendar_events(email: str = "", max_results: int = 5) -> str:
    """List upcoming Google Calendar events.

    Args:
        email: Account email (empty = first available)
        max_results: Number of events (1-20)
    """
    target = email if email else ACCOUNTS[0]
    token = _get_valid_token(target)
    if not token:
        return _token_error(target)

    try:
        now = urllib.parse.quote(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        data = _google_get(
            token,
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults={min(max_results, 20)}&singleEvents=true&orderBy=startTime&timeMin={now}"
        )
        events = data.get("items", [])
        if not events:
            return f"📅 {target}: Tidak ada event mendatang."

        result = [f"📅 {target} — {len(events)} event mendatang:\n"]
        for ev in events:
            summary = ev.get("summary", "(no title)")
            start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "?"))
            result.append(f"  ├ {summary}")
            result.append(f"  │  {start[:16]}")

        return "\n".join(result).strip()
    except Exception as e:
        return f"❌ Gagal baca Calendar: {e}"


def google_status(email: str = "") -> str:
    """Check Google OAuth status for all or specific account.

    Args:
        email: Account email (empty = all accounts)
    """
    targets = [email] if email else ACCOUNTS
    results = ["📊 Google Account Status:\n"]

    for acct in targets:
        token = _get_valid_token(acct)
        if not token:
            results.append(f"  {acct}: ❌ Token tidak valid atau akun tidak dikenal")
            continue

        try:
            profile = _google_get(token, "https://www.googleapis.com/oauth2/v1/userinfo?alt=json")
            name = profile.get("name", acct)
            results.append(f"  ✅ {name} ({acct})")

            # Quick API checks
            try:
                cal = _google_get(token, "https://www.googleapis.com/calendar/v3/calendars/primary")
                results.append(f"     Calendar: ✅")
            except Exception:
                results.append(f"     Calendar: ❌")

            try:
                drive = _google_get(token, "https://www.googleapis.com/drive/v3/about?fields=user")
                results.append(f"     Drive: ✅")
            except Exception:
                results.append(f"     Drive: ❌")

        except Exception as e:
            results.append(f"  {acct}: ❌ {e}")

    return "\n".join(results)