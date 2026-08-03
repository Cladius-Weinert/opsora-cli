"""Opsora Knowledge Graph v2 — FTS5 + relationship graph for project context."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path

DB_PATH = Path("/root/.opsora/graph.db")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".opsora", ".cache", ".npm", ".cargo", ".local", ".config"}
EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".json", ".yaml", ".yml"}

FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(")
CLASS_RE = re.compile(r"^\s*class\s+(\w+)")
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+)?import\s+([\w.,\s]+)")
JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY, filepath TEXT, name TEXT,
            type TEXT, language TEXT, line_start INTEGER, line_end INTEGER,
            content_hash TEXT, indexed_at REAL
        );
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER,
            relationship TEXT,
            FOREIGN KEY (source_id) REFERENCES nodes(id),
            FOREIGN KEY (target_id) REFERENCES nodes(id)
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_filepath ON nodes(filepath);
        CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    """)
    # FTS5 table (idempotent)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_index USING fts5(
                filepath, name, type, content, language,
                tokenize='porter unicode61'
            )
        """)
    except sqlite3.OperationalError:
        pass  # FTS5 not available or already exists
    conn.commit()
    return conn


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode(errors="replace")).hexdigest()[:12]


def _extract_python(filepath: str, lines: list[str]) -> list[dict]:
    """Extract functions and classes from Python source."""
    items = []
    for i, line in enumerate(lines):
        m = FUNCTION_RE.match(line)
        if m:
            items.append({"name": m.group(1), "type": "function", "line": i + 1})
        m = CLASS_RE.match(line)
        if m:
            items.append({"name": m.group(1), "type": "class", "line": i + 1})
    return items


def _extract_imports(filepath: str, lines: list[str]) -> list[str]:
    """Extract import targets from Python/JS/TS files."""
    imports = []
    ext = Path(filepath).suffix
    for line in lines:
        if ext == ".py":
            m = IMPORT_RE.match(line)
            if m:
                mod = m.group(1) or ""
                names = m.group(2)
                imports.append(mod if mod else names.strip().split(",")[0].strip())
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            m = JS_IMPORT_RE.search(line)
            if m:
                imports.append(m.group(1) or m.group(2) or "")
    return [imp for imp in imports if imp]


def _scan_files(root: str, max_files: int) -> list[Path]:
    """Walk workspace, return eligible files sorted by size (smallest first)."""
    root_path = Path(root)
    files = []
    for p in root_path.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix in EXTENSIONS and p.stat().st_size < 500_000:
            files.append(p)
        if len(files) >= max_files * 2:
            break
    files.sort(key=lambda f: f.stat().st_size)
    return files[:max_files]


def index_workspace(workspace_root: str = "/root", max_files: int = 200) -> dict:
    """Scan workspace, extract code entities, build graph. Returns stats."""
    conn = _get_conn()
    files = _scan_files(workspace_root, max_files)
    stats = {"files_indexed": 0, "functions_found": 0, "classes_found": 0, "edges_created": 0}
    node_map: dict[str, int] = {}  # filepath -> node_id, name -> node_id

    for fpath in files:
        try:
            text = fpath.read_text(errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        fp_str = str(fpath)
        ext = fpath.suffix
        lang = {".py": "python", ".js": "javascript", ".ts": "typescript",
                ".jsx": "javascript", ".tsx": "typescript", ".md": "markdown",
                ".json": "json", ".yaml": "yaml", ".yml": "yaml"}.get(ext, "unknown")

        # File node
        cur = conn.execute(
            "INSERT INTO nodes (filepath, name, type, language, line_start, content_hash, indexed_at) "
            "VALUES (?, ?, 'file', ?, 1, ?, ?)",
            (fp_str, fpath.name, lang, _content_hash(text), time.time()),
        )
        file_id = cur.lastrowid
        node_map[fp_str] = file_id

        # FTS5 index
        try:
            conn.execute(
                "INSERT INTO code_index (filepath, name, type, content, language) VALUES (?,?,?,?,?)",
                (fp_str, fpath.name, "file", text[:8192], lang),
            )
        except sqlite3.OperationalError:
            pass

        # Extract entities
        if ext == ".py":
            entities = _extract_python(fp_str, lines)
        else:
            entities = []

        for ent in entities:
            cur2 = conn.execute(
                "INSERT INTO nodes (filepath, name, type, language, line_start, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fp_str, ent["name"], ent["type"], lang, ent["line"], time.time()),
            )
            ent_id = cur2.lastrowid
            node_map[ent["name"]] = ent_id
            # contains edge: file -> entity
            conn.execute(
                "INSERT INTO edges (source_id, target_id, relationship) VALUES (?, ?, 'contains')",
                (file_id, ent_id),
            )
            if ent["type"] == "function":
                stats["functions_found"] += 1
            else:
                stats["classes_found"] += 1
            stats["edges_created"] += 1

            # FTS5 for entity
            try:
                snippet = "\n".join(lines[max(0, ent["line"] - 1):ent["line"] + 10])
                conn.execute(
                    "INSERT INTO code_index (filepath, name, type, content, language) VALUES (?,?,?,?,?)",
                    (fp_str, ent["name"], ent["type"], snippet, lang),
                )
            except sqlite3.OperationalError:
                pass

        # Import edges
        imps = _extract_imports(fp_str, lines)
        for imp in imps:
            if imp in node_map:
                conn.execute(
                    "INSERT INTO edges (source_id, target_id, relationship) VALUES (?, ?, 'imports')",
                    (file_id, node_map[imp]),
                )
                stats["edges_created"] += 1

        stats["files_indexed"] += 1

    conn.commit()
    conn.close()
    return stats


def graph_query(query: str, depth: int = 2, max_results: int = 20) -> list[dict]:
    """FTS5 search + edge traversal. Returns nodes with related context."""
    conn = _get_conn()
    try:
        # Step 1: FTS5 search
        try:
            rows = conn.execute(
                "SELECT filepath, name, type, snippet(code_index, 3, '>>>', '<<<', '...', 20) "
                "FROM code_index WHERE code_index MATCH ? LIMIT ?",
                (query, max_results),
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback: LIKE search on nodes
            rows = conn.execute(
                "SELECT filepath, name, type, '' FROM nodes WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", max_results),
            ).fetchall()

        results = []
        for row in rows:
            # Step 2: find node id and traverse edges
            node_row = conn.execute(
                "SELECT id, filepath, name, type, language FROM nodes WHERE filepath=? AND name=?",
                (row[0], row[1]),
            ).fetchone()
            if not node_row:
                continue
            nid = node_row[0]
            related = []
            visited = {nid}
            frontier = [nid]
            for _ in range(depth):
                next_frontier = []
                for fid in frontier:
                    edges = conn.execute(
                        "SELECT e.target_id, e.relationship, n.name, n.type "
                        "FROM edges e JOIN nodes n ON n.id=e.target_id WHERE e.source_id=?",
                        (fid,),
                    ).fetchall()
                    edges += conn.execute(
                        "SELECT e.source_id, e.relationship, n.name, n.type "
                        "FROM edges e JOIN nodes n ON n.id=e.source_id WHERE e.target_id=?",
                        (fid,),
                    ).fetchall()
                    for e in edges:
                        if e[0] not in visited:
                            visited.add(e[0])
                            related.append({"name": e[2], "type": e[3], "rel": e[1]})
                            next_frontier.append(e[0])
                frontier = next_frontier

            results.append({
                "node": {"filepath": row[0], "name": row[1], "type": row[2], "language": node_row[4]},
                "snippet": row[3],
                "related": related[:10],
            })
        return results
    finally:
        conn.close()


def find_dependencies(filepath: str) -> dict:
    """Outgoing imports, incoming imports, contained entities."""
    conn = _get_conn()
    try:
        node = conn.execute("SELECT id FROM nodes WHERE filepath=? AND type='file'", (filepath,)).fetchone()
        if not node:
            return {"outgoing": [], "incoming": [], "contains": []}
        nid = node[0]
        outgoing = [r[0] for r in conn.execute(
            "SELECT n.filepath FROM edges e JOIN nodes n ON n.id=e.target_id "
            "WHERE e.source_id=? AND e.relationship='imports'", (nid,)).fetchall()]
        incoming = [r[0] for r in conn.execute(
            "SELECT n.filepath FROM edges e JOIN nodes n ON n.id=e.source_id "
            "WHERE e.target_id=? AND e.relationship='imports'", (nid,)).fetchall()]
        contains = [r[0] for r in conn.execute(
            "SELECT n.name FROM edges e JOIN nodes n ON n.id=e.target_id "
            "WHERE e.source_id=? AND e.relationship='contains'", (nid,)).fetchall()]
        return {"outgoing": outgoing, "incoming": incoming, "contains": contains}
    finally:
        conn.close()


def find_callers(function_name: str) -> list[dict]:
    """Find nodes that have a 'calls' edge pointing to this function."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT n.filepath, n.name, n.type FROM edges e "
            "JOIN nodes n ON n.id=e.source_id "
            "JOIN nodes t ON t.id=e.target_id "
            "WHERE t.name=? AND e.relationship='calls'", (function_name,),
        ).fetchall()
        return [{"filepath": r[0], "name": r[1], "type": r[2]} for r in rows]
    finally:
        conn.close()


def get_file_context(filepath: str) -> str:
    """Readable summary of a file for LLM context injection."""
    deps = find_dependencies(filepath)
    if not deps["contains"] and not deps["outgoing"]:
        return f"File: {filepath}\n(no indexed data)"
    lines = [f"File: {filepath}"]
    if deps["contains"]:
        lines.append(f"  Entities: {', '.join(deps['contains'])}")
    if deps["outgoing"]:
        lines.append(f"  Imports: {', '.join(deps['outgoing'][:10])}")
    if deps["incoming"]:
        lines.append(f"  Used by: {', '.join(deps['incoming'][:10])}")
    return "\n".join(lines)


def reindex_changed(files: list[str]) -> dict:
    """Re-index specific files: remove old nodes/edges, then re-scan."""
    conn = _get_conn()
    try:
        for fp in files:
            old = conn.execute("SELECT id FROM nodes WHERE filepath=?", (fp,)).fetchall()
            ids = [r[0] for r in old]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})", ids + ids)
                conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", ids)
            try:
                conn.execute("DELETE FROM code_index WHERE filepath=?", (fp,))
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()
    # Re-index via index_workspace with just these files' parent dirs
    count = 0
    for fp in files:
        p = Path(fp)
        if p.exists() and p.is_file():
            # Mini re-index: single file
            _reindex_single(fp)
            count += 1
    return {"reindexed": count}


def _reindex_single(fp_str: str) -> None:
    """Index a single file into the graph."""
    p = Path(fp_str)
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return
    lines = text.splitlines()
    ext = p.suffix
    lang = {".py": "python", ".js": "javascript", ".ts": "typescript"}.get(ext, "unknown")
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO nodes (filepath, name, type, language, line_start, content_hash, indexed_at) "
            "VALUES (?, ?, 'file', ?, 1, ?, ?)",
            (fp_str, p.name, lang, _content_hash(text), time.time()),
        )
        file_id = cur.lastrowid
        if ext == ".py":
            for ent in _extract_python(fp_str, lines):
                conn.execute(
                    "INSERT INTO nodes (filepath, name, type, language, line_start, indexed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fp_str, ent["name"], ent["type"], lang, ent["line"], time.time()),
                )
        conn.commit()
    finally:
        conn.close()
