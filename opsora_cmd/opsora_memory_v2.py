"""Opsora Semantic Memory v2 — Embedding-powered memory search."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DB_PATH = Path("/root/.opsora/memory.db")

DASHSCOPE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/embeddings"
DASHSCOPE_MODEL = "text-embedding-v3"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/embeddings"
NVIDIA_MODEL = "nv-embedqa-e5-v5"
EMBED_DIM = 1024


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
    # Add embedding columns if missing (idempotent)
    for stmt in [
        "ALTER TABLE memories ADD COLUMN embedding BLOB",
        "ALTER TABLE memories ADD COLUMN embedding_model TEXT DEFAULT ''",
        "ALTER TABLE memories ADD COLUMN embedding_dim INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn


def _pack_floats(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_floats(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def generate_embedding(text: str, provider: str = "dashscope") -> list[float] | None:
    """Generate 1024-dim embedding via DashScope (primary) or NVIDIA (fallback)."""
    providers = []
    if provider == "dashscope":
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if key:
            providers.append((DASHSCOPE_URL, DASHSCOPE_MODEL, key))
        nkey = os.environ.get("NVIDIA_API_KEY", "")
        if nkey:
            providers.append((NVIDIA_URL, NVIDIA_MODEL, nkey))
    else:
        nkey = os.environ.get("NVIDIA_API_KEY", "")
        if nkey:
            providers.append((NVIDIA_URL, NVIDIA_MODEL, nkey))
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if key:
            providers.append((DASHSCOPE_URL, DASHSCOPE_MODEL, key))

    for url, model, api_key in providers:
        try:
            body = json.dumps({"model": model, "input": text[:2048]}).encode()
            req = Request(url, data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            })
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            vec = data["data"][0]["embedding"]
            if len(vec) == EMBED_DIM:
                return vec
        except (HTTPError, URLError, KeyError, json.JSONDecodeError, OSError):
            continue
    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Returns 0.0 on edge cases."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def add_memory_semantic(text: str, source: str = "cli") -> str:
    """Simpan memory dengan embedding. Fallback ke plain text jika embedding gagal."""
    if not text or not text.strip():
        return "Teks memory gak boleh kosong."
    if len(text.strip()) > 4096:
        return "Teks kepanjangan (max 4096 karakter)."

    conn = _get_conn()
    vec = generate_embedding(text.strip())
    try:
        if vec:
            conn.execute(
                "INSERT INTO memories (text, source, created_at, embedding, embedding_model, embedding_dim) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (text.strip(), source, time.time(), _pack_floats(vec), DASHSCOPE_MODEL, EMBED_DIM),
            )
            conn.commit()
            return f"Memory tersimpan (semantic): {text[:80]}"
        else:
            conn.execute(
                "INSERT INTO memories (text, source, created_at) VALUES (?, ?, ?)",
                (text.strip(), source, time.time()),
            )
            conn.commit()
            return f"Memory tersimpan (tanpa embedding): {text[:80]}"
    finally:
        conn.close()


def search_memory_semantic(query: str, limit: int = 5, threshold: float = 0.3) -> list[dict]:
    """Cari memory pakai semantic similarity. Fallback ke keyword search."""
    conn = _get_conn()
    try:
        vec = generate_embedding(query)
        if vec:
            rows = conn.execute(
                "SELECT id, text, source, created_at, embedding FROM memories WHERE embedding IS NOT NULL"
            ).fetchall()
            scored = []
            for row in rows:
                mem_vec = _unpack_floats(row[4])
                sim = cosine_similarity(vec, mem_vec)
                if sim >= threshold:
                    scored.append({
                        "id": row[0], "text": row[1], "source": row[2],
                        "created_at": row[3], "similarity": round(sim, 4),
                    })
            scored.sort(key=lambda x: x["similarity"], reverse=True)
            if scored:
                return scored[:limit]

        # Fallback: keyword search
        keywords = query.strip().split()[:5]
        clause = " AND ".join("text LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]
        rows = conn.execute(
            f"SELECT id, text, source, created_at FROM memories WHERE {clause} "
            "ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [{"id": r[0], "text": r[1], "source": r[2], "created_at": r[3],
                 "similarity": 0.0, "fallback": True} for r in rows]
    finally:
        conn.close()


def migrate_existing_memories() -> int:
    """Generate embeddings for memories that don't have one yet. Batch 10, delay 1s."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, text FROM memories WHERE embedding IS NULL ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()

    migrated = 0
    for i in range(0, len(rows), 10):
        batch = rows[i:i + 10]
        for row in batch:
            vec = generate_embedding(row[1])
            if vec:
                c = _get_conn()
                try:
                    c.execute(
                        "UPDATE memories SET embedding=?, embedding_model=?, embedding_dim=? WHERE id=?",
                        (_pack_floats(vec), DASHSCOPE_MODEL, EMBED_DIM, row[0]),
                    )
                    c.commit()
                    migrated += 1
                finally:
                    c.close()
        if i + 10 < len(rows):
            time.sleep(1)
    return migrated


def memory_stats_v2() -> dict:
    """Statistik memory: total, with/without embedding, DB size."""
    conn = _get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        with_emb = conn.execute("SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL").fetchone()[0]
        last = conn.execute("SELECT MAX(created_at) FROM memories").fetchone()[0]
    finally:
        conn.close()
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "total": total,
        "with_embedding": with_emb,
        "without_embedding": total - with_emb,
        "last_saved": last,
        "db_size_kb": round(db_size / 1024, 1),
    }
