"""Opsora Session Manager — SQLite-based session persistence.

Save, resume, list, and search conversation sessions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path("/root/.opsora/sessions.db")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            token_count INTEGER NOT NULL DEFAULT 0,
            approval_mode TEXT NOT NULL DEFAULT 'full-auto'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_calls TEXT,
            tool_call_id TEXT,
            name TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
    conn.commit()
    return conn


def _generate_id() -> str:
    import hashlib
    raw = f"{time.time()}-{id(object())}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class Session:
    id: str = ""
    title: str = ""
    provider: str = ""
    model: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    token_count: int = 0
    approval_mode: str = "full-auto"
    messages: list[dict[str, Any]] = field(default_factory=list)


def save_session(
    session_id: str,
    title: str,
    provider: str,
    model: str,
    approval_mode: str,
    messages: list[dict[str, Any]],
) -> str:
    if not session_id or not isinstance(session_id, str):
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(messages, list):
        raise TypeError("messages must be a list")
    now = time.time()
    conn = _conn()
    try:
        existing = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessions SET title=?, provider=?, model=?, updated_at=?, token_count=?, approval_mode=? WHERE id=?",
                (title, provider, model, now, _estimate_tokens(messages), approval_mode, session_id),
            )
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        else:
            conn.execute(
                "INSERT INTO sessions (id, title, provider, model, created_at, updated_at, token_count, approval_mode) VALUES (?,?,?,?,?,?,?,?)",
                (session_id, title, provider, model, now, now, _estimate_tokens(messages), approval_mode),
            )

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            tool_calls_json = json.dumps(msg.get("tool_calls"), ensure_ascii=False) if msg.get("tool_calls") else None
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    session_id,
                    msg.get("role", ""),
                    msg.get("content", ""),
                    tool_calls_json,
                    msg.get("tool_call_id"),
                    msg.get("name"),
                    now,
                ),
            )

        conn.commit()
        return session_id
    except sqlite3.IntegrityError as e:
        raise ValueError(f"Database integrity error: {e}")
    except Exception as e:
        raise RuntimeError(f"Session save failed: {e}")
    finally:
        conn.close()


def load_session(session_id: str) -> Optional[Session]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, title, provider, model, created_at, updated_at, token_count, approval_mode FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None

        messages = []
        for mrow in conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall():
            msg: dict[str, Any] = {"role": mrow[0]}
            if mrow[1] is not None:
                msg["content"] = mrow[1]
            if mrow[2] is not None:
                try:
                    msg["tool_calls"] = json.loads(mrow[2])
                except json.JSONDecodeError:
                    pass
            if mrow[3] is not None:
                msg["tool_call_id"] = mrow[3]
            if mrow[4] is not None:
                msg["name"] = mrow[4]
            messages.append(msg)

        return Session(
            id=row[0],
            title=row[1],
            provider=row[2],
            model=row[3],
            created_at=row[4],
            updated_at=row[5],
            token_count=row[6],
            approval_mode=row[7],
            messages=messages,
        )
    finally:
        conn.close()


def list_sessions(limit: int = 20) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, title, provider, model, created_at, updated_at, token_count, approval_mode FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "provider": r[2],
                "model": r[3],
                "created_at": r[4],
                "updated_at": r[5],
                "token_count": r[6],
                "approval_mode": r[7],
            }
            for r in rows
        ]
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    conn = _conn()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def search_sessions(query: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT DISTINCT s.id, s.title, s.provider, s.model, s.updated_at
               FROM sessions s JOIN messages m ON m.session_id = s.id
               WHERE LOWER(m.content) LIKE ? OR LOWER(s.title) LIKE ?
               ORDER BY s.updated_at DESC LIMIT ?""",
            (f"%{query.lower()}%", f"%{query.lower()}%", limit),
        ).fetchall()
        return [{"id": r[0], "title": r[1], "provider": r[2], "model": r[3], "updated_at": r[4]} for r in rows]
    finally:
        conn.close()


def _estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if content:
            total += len(content.split())
    return total
