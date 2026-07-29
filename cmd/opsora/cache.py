"""Disk-backed cache for tool results and context prefetch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from opsora.config import get_paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cache_namespace ON cache_entries(namespace);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_entries(expires_at);
"""


def _connect() -> sqlite3.Connection:
    paths = get_paths()
    paths.ensure_dirs()
    conn = sqlite3.connect(paths.cache_db)
    conn.executescript(_SCHEMA)
    return conn


def _hash_key(namespace: str, payload: dict[str, Any] | str) -> str:
    raw = f"{namespace}:{json.dumps(payload, sort_keys=True, ensure_ascii=False) if isinstance(payload, dict) else payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached(namespace: str, payload: dict[str, Any] | str) -> str | None:
    key = _hash_key(namespace, payload)
    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload, expires_at FROM cache_entries WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if row[1] < now:
            conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (key,))
            return None
        conn.execute(
            "UPDATE cache_entries SET hits = hits + 1 WHERE cache_key = ?",
            (key,),
        )
        return row[0]


def set_cached(
    namespace: str,
    payload: dict[str, Any] | str,
    value: str,
    ttl_seconds: int = 3600,
) -> None:
    key = _hash_key(namespace, payload)
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO cache_entries (cache_key, namespace, payload, created_at, expires_at, hits)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (key, namespace, value, now, now + max(60, ttl_seconds)),
        )


def cache_stats() -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM cache_entries WHERE expires_at >= ?",
            (now,),
        ).fetchone()[0]
        hits = conn.execute("SELECT COALESCE(SUM(hits), 0) FROM cache_entries").fetchone()[0]
    return {
        "total_entries": total,
        "active_entries": active,
        "total_hits": hits,
        "db_path": str(get_paths().cache_db),
    }


def purge_expired() -> int:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute("DELETE FROM cache_entries WHERE expires_at < ?", (now,))
        return cur.rowcount
