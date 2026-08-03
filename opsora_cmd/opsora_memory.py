"""Opsora persistent memory — SQLite-backed local memory store."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path("/root/.opsora/memory.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            source TEXT DEFAULT 'cli',
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_memory(text: str, source: str = "cli") -> str:
    if not text or not text.strip():
        return "Memory text cannot be empty."
    if len(text.strip()) > 4096:
        return "Memory text too long (max 4096 chars)."
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO memories (text, source, created_at) VALUES (?, ?, ?)",
            (text.strip(), source, time.time()),
        )
        conn.commit()
        return f"Saved to memory: {text.strip()[:120]}"
    except sqlite3.IntegrityError as e:
        return f"Database error: {e}"
    except Exception as e:
        return f"Unexpected error: {e}"
    finally:
        conn.close()


def search_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    conn = _get_conn()
    try:
        keywords = query.strip().lower().split()
        results = []
        for kw in keywords:
            rows = conn.execute(
                "SELECT id, text, source, created_at FROM memories WHERE LOWER(text) LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{kw}%", limit),
            ).fetchall()
            for row in rows:
                results.append({
                    "id": row[0],
                    "text": row[1],
                    "source": row[2],
                    "created_at": row[3],
                })
        seen = set()
        unique = []
        for r in results:
            if r["id"] not in seen:
                seen.add(r["id"])
                unique.append(r)
        return unique[:limit]
    finally:
        conn.close()


def memory_stats() -> dict[str, Any]:
    conn = _get_conn()
    try:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        latest = conn.execute(
            "SELECT created_at FROM memories ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return {
            "total_memories": count,
            "db_path": str(DB_PATH),
            "last_saved": latest[0] if latest else None,
        }
    finally:
        conn.close()
