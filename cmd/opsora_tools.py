"""Opsora workspace tools — status and knowledge graph utilities."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path("/root")
OPSORA_DIR = WORKSPACE_ROOT / ".opsora"


def workspace_status() -> dict[str, Any]:
    disk = shutil.disk_usage(str(WORKSPACE_ROOT))
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": f"{platform.python_version()}",
        "workspace": str(WORKSPACE_ROOT),
        "disk_free_gb": round(disk.free / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "opsora_dir_exists": OPSORA_DIR.is_dir(),
        "providers": {
            "nvidia": bool(os.environ.get("NVIDIA_API_KEY")),
            "alibaba": bool(os.environ.get("DASHSCOPE_API_KEY")),
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
        },
        "cli_version": "3.0",
        "android_termux": "termux" in os.environ.get("PREFIX", "").lower(),
    }


def graphify_query(query: str, depth: int = 2) -> str:
    """Simple keyword-based project context search.

    Scans Python and Markdown files in workspace for matching keywords.
    Returns relevant file paths and matching lines.
    """
    if not query or not query.strip():
        return "No query provided."

    keywords = query.strip().lower().split()
    results: list[dict[str, str]] = []
    scan_dirs = [
        WORKSPACE_ROOT / "opsora-cli",
        WORKSPACE_ROOT / "projects",
        OPSORA_DIR,
    ]

    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for ext in ("*.py", "*.md", "*.json", "*.yaml", "*.yml", "*.toml"):
            for fpath in scan_dir.rglob(ext):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    content_lower = content.lower()
                    if any(kw in content_lower for kw in keywords):
                        rel = str(fpath.relative_to(WORKSPACE_ROOT))
                        matching_lines = []
                        for i, line in enumerate(content.splitlines(), 1):
                            if any(kw in line.lower() for kw in keywords):
                                matching_lines.append(f"  L{i}: {line.strip()[:100]}")
                                if len(matching_lines) >= 3:
                                    break
                        results.append({
                            "file": rel,
                            "matches": "\n".join(matching_lines),
                        })
                        if len(results) >= 10:
                            break
                except (PermissionError, OSError):
                    continue
            if len(results) >= 10:
                break
        if len(results) >= 10:
            break

    if not results:
        return f"No results found for: {query}"

    output = f"Graphify results for '{query}' ({len(results)} files):\n\n"
    for r in results:
        output += f"📄 {r['file']}\n{r['matches']}\n\n"
    return output.strip()
