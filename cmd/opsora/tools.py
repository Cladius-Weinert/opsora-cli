"""Tool execution with caching and lightweight Graphify fallback."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from opsora.cache import get_cached, set_cached
from opsora.config import get_paths
from opsora.memory import add_memory, memory_stats, search_memory

CACHEABLE_TOOLS = {
    "memory_search": 1800,
    "graphify_query": 3600,
    "workspace_status": 300,
    "skill_list": 600,
    "skill_match": 600,
}


def workspace_status() -> dict[str, Any]:
    paths = get_paths()
    stats = memory_stats()
    graphify_available = paths.graphify_root.exists()
    skill_count = 0
    try:
        from opsora.skills import list_skills

        skill_count = len(list_skills())
    except Exception:
        skill_count = 0
    return {
        "workspace_root": str(paths.workspace_root),
        "memory": stats,
        "graphify": {
            "available": graphify_available,
            "root": str(paths.graphify_root),
        },
        "skills_loaded": skill_count,
        "cache_db": str(paths.cache_db),
    }


def graphify_query(query: str, depth: int = 2) -> str:
    paths = get_paths()
    query = (query or "").strip()
    if not query:
        return "ERROR: graphify query is empty"

    try:
        result = subprocess.run(
            ["graphify", "query", query, "--depth", str(depth)],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=paths.workspace_root,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 and output.strip():
            return output[:50000]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return _graphify_fallback(query, depth)


def _graphify_fallback(query: str, depth: int) -> str:
    paths = get_paths()
    matches: list[dict[str, str]] = []
    tokens = [token.lower() for token in query.split() if len(token) > 2][:6]
    search_roots = [paths.workspace_root]
    if paths.graphify_root.exists():
        search_roots.append(paths.graphify_root)

    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml", ".sh"}:
                continue
            name = path.name.lower()
            if tokens and not any(token in name for token in tokens):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if tokens and not any(token in text.lower() for token in tokens):
                continue
            matches.append({"path": str(path), "preview": text[:240]})
            if len(matches) >= max(3, depth * 4):
                break
        if len(matches) >= max(3, depth * 4):
            break

    if not matches:
        return json.dumps(
            {
                "mode": "fallback",
                "message": "Graphify CLI not found; no local keyword matches",
                "query": query,
            },
            ensure_ascii=False,
        )
    return json.dumps({"mode": "fallback", "query": query, "matches": matches}, ensure_ascii=False)


def execute_tool(name: str, args: dict[str, Any]) -> str:
    cache_ttl = CACHEABLE_TOOLS.get(name)
    if cache_ttl is not None:
        cached = get_cached(f"tool:{name}", args)
        if cached is not None:
            return cached

    if name == "memory_add":
        result = add_memory(args.get("text", ""), source=args.get("source", "cli"))
    elif name == "memory_search":
        result = json.dumps(search_memory(args.get("query", ""), args.get("limit", 5)), ensure_ascii=False)
    elif name == "graphify_query":
        result = graphify_query(args.get("query", ""), depth=int(args.get("depth", 2)))
    elif name == "workspace_status":
        result = json.dumps(workspace_status(), ensure_ascii=False)
    elif name == "skill_list":
        from opsora.skills import list_skills

        result = json.dumps(
            [{"name": s.name, "description": s.description, "source": s.source} for s in list_skills()],
            ensure_ascii=False,
        )
    elif name == "skill_match":
        from opsora.skills import match_skills

        query = args.get("query", "")
        result = json.dumps(
            [{"name": s.name, "description": s.description, "source": s.source} for s in match_skills(query)],
            ensure_ascii=False,
        )
    elif name == "read_file":
        result = _read_file(args.get("filepath", ""))
    elif name == "write_file":
        result = _write_file(args.get("filepath", ""), str(args.get("content", "")))
    elif name == "run_command":
        result = _run_command(str(args.get("command", "")))
    elif name == "aws_command":
        result = _aws_command(str(args.get("arguments", "")))
    else:
        result = f"Unknown tool: {name}"

    if cache_ttl is not None:
        set_cached(f"tool:{name}", args, result, ttl_seconds=cache_ttl)
    return result


def _read_file(filepath: str) -> str:
    paths = get_paths()
    path = Path(filepath)
    if not path.is_absolute():
        path = paths.workspace_root / path
    blocked = {".aws", ".ssh", ".gnupg"}
    lowered = {part.casefold() for part in path.resolve().parts}
    if lowered & blocked:
        return "ERROR: Access to credential directories is blocked."
    return path.read_text(encoding="utf-8", errors="replace")[:50000]


def _write_file(filepath: str, content: str) -> str:
    paths = get_paths()
    path = Path(filepath)
    if not path.is_absolute():
        path = paths.workspace_root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


def _run_command(command: str) -> str:
    paths = get_paths()
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=paths.workspace_root,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return output[:50000] or f"Command exited with code {result.returncode}."


def _aws_command(arguments: str) -> str:
    import os
    import shlex

    profile = os.environ.get("AWS_PROFILE", "default")
    cmd_args = shlex.split(arguments)
    allowed_prefixes = ("get-", "describe-", "list-", "head-", "scan", "query")
    if len(cmd_args) >= 2:
        op = cmd_args[1].lower()
        if not any(op.startswith(prefix) for prefix in allowed_prefixes):
            return "ERROR: Only read-only AWS operations allowed."
    result = subprocess.run(
        ["aws", "--profile", profile] + cmd_args,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return ((result.stdout or "") + (result.stderr or ""))[:50000]
