"""Opsora new tools — web_search, db_query, http_request.

Stdlib-only tools for the Opsora agent. No external dependencies.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOOL_MAX_OUTPUT = 30_000
OPSORA_DIR = Path("/root/.opsora")


def _truncate(text: str, limit: int = TOOL_MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n... [truncated, {len(text) - limit} chars omitted]"


# ── web_search ────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo Instant Answer API."""
    if not query or not query.strip():
        return "❌ Query kosong, bro. Kasih kata kunci dulu."

    params = urllib.parse.urlencode({
        "q": query.strip(), "format": "json",
        "no_html": "1", "skip_disambig": "1",
    })
    url = f"https://api.duckduckgo.com/?{params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Opsora/3.0 Agent"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return f"❌ Gagal search: {exc}"

    lines: list[str] = []
    # Abstract (main answer)
    if data.get("AbstractText"):
        lines.append(f"📌 {data.get('Heading', 'Result')}\n   {data['AbstractText']}")
        if data.get("AbstractURL"):
            lines.append(f"   🔗 {data['AbstractURL']}")

    # Related topics
    topics = data.get("RelatedTopics", [])[:max_results]
    for i, topic in enumerate(topics, 1):
        if isinstance(topic, dict) and "Text" in topic:
            lines.append(f"\n{i}. {topic['Text']}")
            if topic.get("FirstURL"):
                lines.append(f"   🔗 {topic['FirstURL']}")

    # Results array
    for i, r in enumerate(data.get("Results", [])[:max_results], 1):
        if isinstance(r, dict) and r.get("Text"):
            lines.append(f"\n{i}. {r['Text']}")
            if r.get("FirstURL"):
                lines.append(f"   🔗 {r['FirstURL']}")

    if not lines:
        return f"🔍 Tidak ada hasil untuk \"{query}\". Coba kata kunci lain."

    return _truncate("\n".join(lines))


def web_search_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo. Returns titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Max results (default 5)", "default": 5},
                },
                "required": ["query"],
            },
        },
    }


# ── db_query ──────────────────────────────────────────────────────────

# Comprehensive list of SQL statements that modify data/schema
_DANGEROUS_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", 
    "REPLACE", "ATTACH", "DETACH", "TRUNCATE", "MERGE",
    "EXECUTE", "PREPARE", "DEALLOCATE", "CALL", "DO",
    "LOAD", "COPY", "IMPORT", "EXPORT", "BACKUP", "RESTORE",
    "VACUUM", "ANALYZE", "REINDEX", "CLUSTER",
)

# Dangerous patterns that can bypass simple keyword checks
_DANGEROUS_PATTERNS = [
    r"--",                    # SQL comments
    r"/\*.*\*/",              # Block comments
    r";\s*\w",               # Multiple statements
    r"UNION\s+(ALL\s+)?SELECT",  # Union injection
    r"OR\s+1\s*=\s*1",       # Classic injection
    r"'\s*;",                # Quote termination
]

_DANGEROUS_RE = re.compile(
    r"\b(" + "|".join(_DANGEROUS_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _validate_select_only(sql: str) -> tuple[bool, str]:
    """Validate that SQL is a read-only SELECT query.
    Returns (is_valid, error_message)."""
    sql_upper = sql.upper().strip()
    
    # Must start with SELECT or WITH (CTE)
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, "Hanya query SELECT atau WITH (CTE) yang diizinkan."
    
    # Check for dangerous keywords
    match = _DANGEROUS_RE.search(sql)
    if match:
        return False, f"Query mengandung keyword terlarang: {match.group(0)}"
    
    # Check for dangerous patterns
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            return False, f"Query mengandang pola berbahaya: {pattern}"
    
    # No semicolon except at end (prevent multiple statements)
    if sql.count(";") > 1 or (sql.count(";") == 1 and not sql.rstrip().endswith(";")):
        return False, "Hanya satu statement yang diizinkan (tanpa titik koma atau satu di akhir)."
    
    return True, ""


def db_query(sql: str, db_path: str = "/root/.opsora/memory.db") -> str:
    """Execute a read-only SQLite query and return formatted results."""
    if not sql or not sql.strip():
        return "❌ Query SQL kosong."

    # Validate SQL is read-only
    valid, error = _validate_select_only(sql)
    if not valid:
        return f"🚫 Query diblokir: {error}"

    path = Path(db_path)
    if not path.exists():
        # Auto-detect available databases
        dbs = list(OPSORA_DIR.glob("*.db"))
        if not dbs:
            return f"❌ Database tidak ditemukan: {db_path}"
        avail = "\n".join(f"  • {p.name}" for p in dbs)
        return f"❌ File `{path.name}` tidak ada. Database yang tersedia:\n{avail}"

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = cur.fetchmany(100)
        cols = [d[0] for d in (cur.description or [])]
        conn.close()
    except sqlite3.OperationalError as exc:
        return f"❌ Error SQL: {exc}"

    if not rows:
        return "✅ Query berhasil, tapi tidak ada hasil."

    # Format as text table
    widths = [len(c) for c in cols]
    str_rows: list[list[str]] = []
    for row in rows:
        sr = [str(v) for v in row]
        str_rows.append(sr)
        for i, v in enumerate(sr):
            widths[i] = max(widths[i], min(len(v), 50))

    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    sep = "-+-".join("-" * w for w in widths)
    lines = [header, sep]
    for sr in str_rows:
        line = " | ".join(sr[i][:50].ljust(widths[i]) for i in range(len(cols)))
        lines.append(line)

    result = "\n".join(lines)
    if len(rows) == 100:
        result += "\n\n⚠️  Ditampilkan max 100 baris."
    return _truncate(result)


def db_query_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "db_query",
            "description": "Run a read-only SQL query on Opsora's SQLite databases. Only SELECT allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query"},
                    "db_path": {"type": "string", "description": "Path to .db file", "default": "/root/.opsora/memory.db"},
                },
                "required": ["sql"],
            },
        },
    }


# ── http_request ──────────────────────────────────────────────────────

_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "169.254.169.254", "0.0.0.0", "::1"}
_BLOCKED_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                     "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                     "172.30.", "172.31.", "192.168.")
_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def http_request(
    url: str, method: str = "GET",
    headers: dict | None = None, body: str | None = None,
    timeout: int = 15,
) -> str:
    """Make an HTTP request and return status, headers, and body."""
    if not url or not url.strip():
        return "❌ URL kosong."

    method = method.upper()
    if method not in _ALLOWED_METHODS:
        return f"🚫 Method `{method}` tidak didukung. Gunakan: {', '.join(sorted(_ALLOWED_METHODS))}"

    # Block internal hosts
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        return "❌ URL tidak valid."

    if host.lower() in _BLOCKED_HOSTS or any(host.startswith(p) for p in _BLOCKED_PREFIXES):
        return "🚫 Akses ke internal/private network diblokir demi keamanan."

    req_headers = {"User-Agent": "Opsora/3.0 Agent"}
    if headers:
        req_headers.update(headers)

    data = body.encode() if body else None
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            resp_headers = dict(list(resp.headers.items())[:10])
            resp_body = resp.read(5000).decode(errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        resp_headers = dict(list(exc.headers.items())[:10])
        resp_body = exc.read(5000).decode(errors="replace")
    except Exception as exc:
        return f"❌ Request gagal: {exc}"

    hdr_lines = [f"  {k}: {v}" for k, v in resp_headers.items()]
    result = (
        f"📡 {method} {url}\n"
        f"Status: {status}\n"
        f"Headers:\n" + "\n".join(hdr_lines) +
        f"\n\nBody:\n{resp_body}"
    )
    return _truncate(result, 8000)


def http_request_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": "Make an HTTP request (GET/POST/PUT/DELETE/PATCH). Returns status, headers, body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL"},
                    "method": {"type": "string", "description": "HTTP method", "default": "GET"},
                    "headers": {"type": "object", "description": "Request headers"},
                    "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
                    "timeout": {"type": "integer", "description": "Timeout seconds", "default": 15},
                },
                "required": ["url"],
            },
        },
    }
