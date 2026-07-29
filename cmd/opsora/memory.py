"""Persistent memory with SQLite FTS5 search."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from opsora.config import get_paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'cli',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text,
    source,
    tags,
    content='memories',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, source, tags)
    VALUES (new.id, new.text, new.source, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, source, tags)
    VALUES ('delete', old.id, old.text, old.source, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, source, tags)
    VALUES ('delete', old.id, old.text, old.source, old.tags);
    INSERT INTO memories_fts(rowid, text, source, tags)
    VALUES (new.id, new.text, new.source, new.tags);
END;
"""


def _connect() -> sqlite3.Connection:
    paths = get_paths()
    paths.ensure_dirs()
    conn = sqlite3.connect(paths.memory_db)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def add_memory(text: str, source: str = "cli", tags: list[str] | None = None) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "ERROR: memory text is empty"
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000]

    now = time.time()
    tag_json = json.dumps(tags or [], ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memories (text, source, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (cleaned, source, tag_json, now, now),
        )
        row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return f"Saved memory #{row_id}"


def search_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
    cleaned = (query or "").strip()
    if not cleaned:
        return []

    limit = max(1, min(limit, 20))
    with _connect() as conn:
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.text, m.source, m.tags, m.created_at, bm25(memories_fts) AS score
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.rowid
                WHERE memories_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (cleaned, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                """
                SELECT id, text, source, tags, created_at, 0.0 AS score
                FROM memories
                WHERE text LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (f"%{cleaned}%", limit),
            ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row["id"],
                "text": row["text"],
                "source": row["source"],
                "tags": json.loads(row["tags"] or "[]"),
                "score": float(row["score"]),
            }
        )
    return results


def memory_stats() -> dict[str, Any]:
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        latest = conn.execute(
            "SELECT text, source, created_at FROM memories ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return {
        "count": count,
        "latest": dict(latest) if latest else None,
        "db_path": str(get_paths().memory_db),
    }
