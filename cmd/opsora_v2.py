#!/usr/bin/env python3
"""
Opsora CLI v3 — Codex/Claude Code-style Agentic Terminal Assistant

Integrates: TUI engine, agent loop with self-reflection, sub-agents,
MCP tools, session persistence, approval modes, and multi-provider routing.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import platform
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.error import URLError
from urllib.request import urlopen, Request

# --- OpenAI client (with fallback to lightweight urllib implementation) ---
try:
    from openai import OpenAI
except (ImportError, Exception):
    from openai_lite import OpenAI

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style as PromptStyle
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner

# Opsora modules
from opsora_tui import (
    ApprovalMode,
    StatusBar,
    console,
    cycle_approval_mode,
    get_approval_mode,
    needs_approval,
    print_welcome,
    prompt_approval,
    render_file_edit,
    render_file_tree,
    render_help,
    render_tool_call,
    set_approval_mode,
    stream_markdown,
)
from opsora_session import (
    delete_session,
    list_sessions,
    load_session,
    save_session,
    search_sessions,
)
from opsora_subagent import SubagentOrchestrator
from opsora_mcp import MCPClient

# ============================================================================
# Workspace Configuration
# ============================================================================

WORKSPACE_ROOT = Path("/root")
OPSORA_DIR = WORKSPACE_ROOT / ".opsora"
OPSORA_DIR.mkdir(exist_ok=True)


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key.replace("_", "").isalnum() or key[:1].isdigit():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(WORKSPACE_ROOT / ".opsora_env")
load_env_file(OPSORA_DIR / "qwen-code" / "secrets.env")

# ============================================================================
# Provider Configuration
# ============================================================================

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
nvidia_client = OpenAI(api_key=NVIDIA_API_KEY, base_url=NVIDIA_URL, timeout=40) if NVIDIA_API_KEY else None

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
ALIBABA_URL = os.environ.get("ALIBABA_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
alibaba_client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=ALIBABA_URL, timeout=40) if DASHSCOPE_API_KEY else None

MODEL_STUDIO_KEY = DASHSCOPE_API_KEY
MODEL_STUDIO_URL = "https://ws-u05t2ivr4fghrt6v.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
model_studio_client = OpenAI(api_key=MODEL_STUDIO_KEY, base_url=MODEL_STUDIO_URL, timeout=40) if MODEL_STUDIO_KEY else None

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=40) if OPENAI_API_KEY else None

LOCAL_URL = os.environ.get("OPSORA_OLLAMA_URL", "http://127.0.0.1:11434/v1")
LOCAL_TAGS_URL = LOCAL_URL.removesuffix("/v1") + "/api/tags"
local_client = OpenAI(api_key="ollama", base_url=LOCAL_URL, timeout=60)

import boto3
from botocore.config import Config

AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def bedrock_available() -> bool:
    try:
        return boto3.Session(profile_name=AWS_PROFILE).get_credentials() is not None
    except Exception:
        return False


TOKENHUB_API_KEY = os.environ.get("TOKENHUB_API_KEY", "")
TOKENHUB_URL = "https://tokenhub.tencentmaas.com/v1"
tokenhub_client = OpenAI(api_key=TOKENHUB_API_KEY, base_url=TOKENHUB_URL, timeout=40) if TOKENHUB_API_KEY else None

OPSORA_API_URL = os.environ.get("OPSORA_API_URL", "")
OPSORA_API_TOKEN = os.environ.get("OPSORA_API_TOKEN", "")
opsora_api_client = (
    OpenAI(api_key=OPSORA_API_TOKEN, base_url=f"{OPSORA_API_URL}/v1", timeout=120)
    if OPSORA_API_URL and OPSORA_API_TOKEN
    else None
)


def get_provider_order() -> list[str]:
    order = os.environ.get("OPSORA_PROVIDER_ORDER", "alibaba,nvidia,bedrock,local")
    return [p.strip() for p in order.split(",") if p.strip()]


PROVIDER_MODELS = {
    "nvidia": os.environ.get("OPSORA_MODEL", "meta/llama-3.1-70b-instruct"),
    "alibaba": "qwen-plus,qwen-turbo,qwen-max",
    "model_studio": "qwen-plus,qwen-turbo,qwen-max",
    "openai": "gpt-4o,gpt-4o-mini",
    "bedrock": "amazon.nova-pro-v1:0,amazon.nova-lite-v1:0",
    "tokenhub": "hy3,kimi-k3,deepseek-v4-flash",
    "opsora_api": "opsora-fast,opsora-brain,opsora-code",
    "local": "qwen3.5:4b,llama3.1:latest",
}

# ============================================================================
# Model Selection & Routing
# ============================================================================


@dataclass
class Selection:
    provider: str
    model: str


def is_provider_available(provider: str) -> bool:
    return {
        "nvidia": nvidia_client is not None,
        "alibaba": alibaba_client is not None,
        "model_studio": model_studio_client is not None,
        "openai": openai_client is not None,
        "bedrock": bedrock_available(),
        "tokenhub": tokenhub_client is not None,
        "opsora_api": opsora_api_client is not None,
        "local": _check_ollama(),
    }.get(provider, False)


def _check_ollama() -> bool:
    try:
        with urlopen(LOCAL_TAGS_URL, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def auto_select_model(prompt: str) -> Selection:
    p = prompt.lower()
    if any(kw in p for kw in ["code", "function", "class", "def ", "bug", "fix", "refactor", "script", "debug", "python", "bash", "implement"]):
        if tokenhub_client:
            return Selection("tokenhub", "hy3")
        if alibaba_client:
            return Selection("alibaba", "qwen-plus")
    if any(kw in p for kw in ["what is", "who is", "quick", "simple", "brief", "jelaskan", "apa", "berapa"]):
        if alibaba_client:
            return Selection("alibaba", "qwen-turbo")
    if any(kw in p for kw in ["analyze", "architecture", "design", "strategy", "complex", "deep"]):
        if tokenhub_client:
            return Selection("tokenhub", "kimi-k3")
        if alibaba_client:
            return Selection("alibaba", "qwen-max")
    for prov in get_provider_order():
        if is_provider_available(prov):
            models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
            if models:
                return Selection(prov, models[0])
    return Selection("alibaba", "qwen-plus")


# ============================================================================
# Tools
# ============================================================================

SAFE_TOOLS = [
    {"type": "function", "function": {"name": "memory_add", "description": "Save a fact to persistent memory", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "source": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "memory_search", "description": "Search persistent memory", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "graphify_query", "description": "Query knowledge graph for project context", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "workspace_status", "description": "Show workspace status", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a file", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Edit a file — replace exact text match", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["filepath", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Execute a shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "grep_search", "description": "Search file contents with regex", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "file_type": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "glob_search", "description": "Find files by glob pattern", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "base": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "Fetch URL content (HTML stripped)", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "list_directory", "description": "List files in a directory", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "todo_write", "description": "Create or update a task/todo list to track multi-step work. Use at the START of complex tasks to plan, then update status as you work.", "parameters": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "content", "status"]}}}, "required": ["todos"]}}},
    {"type": "function", "function": {"name": "git_diff", "description": "Show git diff of working tree changes (unstaged). Use to see what files changed and how.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "staged": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_status", "description": "Show git working tree status — modified, staged, untracked files.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_log", "description": "Show recent git commits with messages.", "parameters": {"type": "object", "properties": {"count": {"type": "integer"}, "path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "run_tests", "description": "Detect test framework and run tests. Auto-detects pytest, jest, go test, cargo test, etc.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "filter": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "git_commit", "description": "Stage all changes and commit with a descriptive message. Use after completing a task.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}, "path": {"type": "string"}}, "required": ["message"]}}},
    {"type": "function", "function": {"name": "lint_check", "description": "Detect and run linter (ruff, flake8, eslint, etc) on a file or directory.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "fix": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "image_read", "description": "Read and describe an image file (PNG, JPG, GIF, SVG). Returns image metadata and dimensions.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}}},
    {"type": "function", "function": {"name": "pip_info", "description": "Show info about an installed Python package: version, location, dependencies.", "parameters": {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]}}},
]

TOOL_MAX_ROUNDS = 20
TOOL_MAX_OUTPUT = 30_000
SENSITIVE_PATHS = {".aws", ".ssh", ".gnupg", ".tccli"}
SENSITIVE_FILES = {"render.env", "secrets.env", ".opsora_env", "credentials", ".env",
                   "cloud-manager.sh", ".bash_history", ".netrc", ".pgpass"}
CREDENTIAL_KEYWORDS = ["api_key", "secret_key", "password", "token", "access_key"]


def execute_tool(name: str, args: dict[str, Any]) -> str:
    try:
        # --- Memory ---
        if name == "memory_add":
            from opsora_memory import add_memory
            return add_memory(args.get("text", ""), source=args.get("source", "cli"))
        if name == "memory_search":
            from opsora_memory import search_memory
            return json.dumps(search_memory(args.get("query", ""), args.get("limit", 5)), ensure_ascii=False)

        # --- Graphify / Workspace ---
        if name == "graphify_query":
            from opsora_tools import graphify_query
            return graphify_query(args.get("query", ""), depth=args.get("depth", 2))
        if name == "workspace_status":
            from opsora_tools import workspace_status
            return json.dumps(workspace_status(), ensure_ascii=False)

        # --- File Operations ---
        if name == "read_file":
            fp = Path(args["filepath"])
            if not fp.is_absolute():
                fp = WORKSPACE_ROOT / fp
            resolved = fp.resolve()
            if SENSITIVE_PATHS & set(resolved.parts):
                return "BLOCKED: folder credential (.aws/.ssh/.gnupg) gak bisa dibaca."
            if resolved.name in SENSITIVE_FILES or resolved.name.startswith(".env"):
                return f"BLOCKED: {resolved.name} berisi credentials."
            if needs_approval("read_file"):
                if not prompt_approval(f"Read {resolved}"):
                    return "Read cancelled."
            content = resolved.read_text(encoding="utf-8", errors="replace")[:TOOL_MAX_OUTPUT]
            # Scan for credential keywords and redact
            lower = content.lower()
            if any(kw in lower for kw in CREDENTIAL_KEYWORDS):
                import re
                content = re.sub(
                    r'((?:api_key|secret_key|password|token|access_key|secret_id|api_token)\s*[=:"]\s*["\']?)([A-Za-z0-9_\-/.]{8,})(["\']?)',
                    r'\1[REDACTED]\3',
                    content, flags=re.IGNORECASE,
                )
            return content

        if name == "write_file":
            fp = Path(args["filepath"])
            if not fp.is_absolute():
                fp = WORKSPACE_ROOT / fp
            content = str(args.get("content", ""))
            if needs_approval("write_file"):
                preview = content[:500]
                if not prompt_approval(f"Write {fp}", preview):
                    return "Write cancelled."
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} chars to {fp}"

        if name == "edit_file":
            fp = Path(args["filepath"])
            if not fp.is_absolute():
                fp = WORKSPACE_ROOT / fp
            if not fp.exists():
                return f"ERROR: File not found: {fp}"
            content = fp.read_text(encoding="utf-8")
            old_str, new_str = args["old_string"], args["new_string"]
            if old_str not in content:
                return f"ERROR: old_string not found in {fp}."
            if needs_approval("edit_file"):
                if not prompt_approval(f"Edit {fp}", f"- {old_str[:100]}\n+ {new_str[:100]}"):
                    return "Edit cancelled."
            new_content = content.replace(old_str, new_str, 1)
            fp.write_text(new_content, encoding="utf-8")
            return f"Edited {fp}: replaced {len(old_str)} → {len(new_str)} chars"

        # --- Shell ---
        if name == "run_command":
            cmd = str(args["command"])
            if needs_approval("run_command"):
                if not prompt_approval(f"Run command", cmd):
                    return "Command cancelled."
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120, cwd=WORKSPACE_ROOT)
            output = (result.stdout or "") + (result.stderr or "")
            return output[:TOOL_MAX_OUTPUT] or f"Exit code {result.returncode}."

        # --- Search ---
        if name == "grep_search":
            pattern = args["pattern"]
            search_path = args.get("path", ".")
            if not Path(search_path).is_absolute():
                search_path = str(WORKSPACE_ROOT / search_path)
            file_type = args.get("file_type", "")
            cmd = ["grep", "-rn", "--color=never"]
            if file_type:
                cmd.extend([f"--include=*.{file_type}"])
            cmd.extend([pattern, search_path])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout
            if not output:
                return f"No matches for '{pattern}'"
            lines = output.strip().split("\n")
            if len(lines) > 200:
                output = "\n".join(lines[:200]) + f"\n… ({len(lines)} total)"
            return output[:TOOL_MAX_OUTPUT]

        if name == "glob_search":
            import glob as glob_mod
            base = args.get("base", "")
            pattern = args["pattern"]
            # If no base given, search across workspace + common project dirs
            if not base:
                search_roots = [
                    str(WORKSPACE_ROOT),
                    str(WORKSPACE_ROOT / "projects"),
                    str(WORKSPACE_ROOT / "opsora-cli"),
                ]
            else:
                p = Path(base)
                if not p.is_absolute():
                    p = WORKSPACE_ROOT / p
                search_roots = [str(p)]

            all_matches = []
            # Auto-add ** if pattern doesn't contain path separator (recursive by default)
            if "/" not in pattern and "**" not in pattern:
                pattern = f"**/{pattern}"

            # Directories/files to always skip
            _SKIP_DIRS = {"/.git/", "/__pycache__/", "/node_modules/", "/.cache/", "/.venv/", "/venv/", "/dist/", "/build/", "/.tox/"}
            _SKIP_EXTS = {".pyc", ".pyo", ".class", ".o", ".so", ".dylib"}

            for root in search_roots:
                full_pattern = os.path.join(root, pattern)
                matches = glob_mod.glob(full_pattern, recursive=True)
                for m in matches:
                    if not os.path.isfile(m):
                        continue
                    if any(skip in m for skip in _SKIP_DIRS):
                        continue
                    if any(m.endswith(ext) for ext in _SKIP_EXTS):
                        continue
                    try:
                        all_matches.append(str(Path(m).relative_to(WORKSPACE_ROOT)))
                    except ValueError:
                        all_matches.append(m)

            all_matches = sorted(set(all_matches))[:100]
            return json.dumps(all_matches, indent=2) if all_matches else f"Gak ada file matching '{args['pattern']}'"

        if name == "list_directory":
            target = Path(args["path"])
            if not target.is_absolute():
                target = WORKSPACE_ROOT / target
            if not target.is_dir():
                return f"ERROR: {target} is not a directory."
            entries = sorted(target.iterdir())[:100]
            lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries]
            return "\n".join(lines) if lines else "Empty directory."

        # --- Web ---
        if name == "web_fetch":
            import re as re_mod
            url = args["url"]
            if not url.startswith(("http://", "https://")):
                return "ERROR: URL must start with http:// or https://"
            max_chars = int(args.get("max_chars", 50000))
            req = Request(url, headers={"User-Agent": "Opsora/3.0 Agent"})
            try:
                with urlopen(req, timeout=15) as resp:
                    raw = resp.read(max_chars * 2).decode("utf-8", errors="replace")
            except Exception as e:
                return f"ERROR: {e}"
            clean = re_mod.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re_mod.DOTALL)
            clean = re_mod.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re_mod.DOTALL)
            clean = re_mod.sub(r"<[^>]+>", " ", clean)
            clean = re_mod.sub(r"\s+", " ", clean).strip()
            return clean[:max_chars]

        # --- Git Tools ---
        if name == "git_diff":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            staged = "--cached" if args.get("staged") else ""
            result = subprocess.run(
                f"cd {repo_path} && git diff {staged} --stat && echo '---FULL DIFF---' && git diff {staged}",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            output = (result.stdout or result.stderr or "No changes.").strip()
            # Truncate large diffs
            if len(output) > 8000:
                lines = output.split("\n")
                stat_end = next((i for i, l in enumerate(lines) if "---FULL DIFF---" in l), 20)
                output = "\n".join(lines[:stat_end]) + f"\n… diff truncated ({len(output)} chars total)"
            return output

        if name == "git_status":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            result = subprocess.run(
                f"cd {repo_path} && git status --short",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            output = (result.stdout or result.stderr or "Clean working tree.").strip()
            return output

        if name == "git_log":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            count = args.get("count", 10)
            result = subprocess.run(
                f"cd {repo_path} && git log --oneline -{count}",
                shell=True, capture_output=True, text=True, timeout=10,
            )
            return (result.stdout or result.stderr or "No commits found.").strip()

        if name == "run_tests":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            test_filter = args.get("filter", "")
            rp = Path(repo_path)

            # Auto-detect test framework
            cmd = None
            if (rp / "pytest.ini").exists() or (rp / "pyproject.toml").exists() or (rp / "setup.py").exists() or list(rp.glob("**/test_*.py")):
                cmd = f"cd {repo_path} && python3 -m pytest {test_filter} -x -q --tb=short 2>&1 | head -100"
            elif (rp / "package.json").exists():
                cmd = f"cd {repo_path} && npm test 2>&1 | head -100"
            elif (rp / "Cargo.toml").exists():
                cmd = f"cd {repo_path} && cargo test 2>&1 | head -100"
            elif (rp / "go.mod").exists():
                cmd = f"cd {repo_path} && go test ./... 2>&1 | head -100"
            elif (rp / "Makefile").exists():
                cmd = f"cd {repo_path} && make test 2>&1 | head -100"
            else:
                return "No test framework detected. Supported: pytest, npm test, cargo test, go test, make test."

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            output = (result.stdout or "") + (result.stderr or "")
            return output.strip()[:TOOL_MAX_OUTPUT] or f"Tests exited with code {result.returncode}."

        if name == "git_commit":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            message = args.get("message", "auto-commit")
            if needs_approval("git_commit"):
                if not prompt_approval(f"git commit in {repo_path}", message):
                    return "Commit cancelled."
            result = subprocess.run(
                f"cd {repo_path} && git add -A && git commit -m {shlex.quote(message)}",
                shell=True, capture_output=True, text=True, timeout=30,
            )
            return (result.stdout or result.stderr or "Nothing to commit.").strip()

        if name == "lint_check":
            repo_path = args.get("path", str(WORKSPACE_ROOT))
            if not Path(repo_path).is_absolute():
                repo_path = str(WORKSPACE_ROOT / repo_path)
            fix = "--fix" if args.get("fix") else ""
            rp = Path(repo_path)

            # Auto-detect linter
            cmd = None
            if shutil.which("ruff"):
                cmd = f"cd {repo_path} && ruff check {fix} . 2>&1 | head -60"
            elif shutil.which("flake8"):
                cmd = f"cd {repo_path} && flake8 . 2>&1 | head -60"
            elif (rp / "package.json").exists() and shutil.which("npx"):
                cmd = f"cd {repo_path} && npx eslint {fix} . 2>&1 | head -60"
            elif shutil.which("pylint"):
                cmd = f"cd {repo_path} && pylint {repo_path} 2>&1 | head -60"
            else:
                return "No linter found. Install: ruff, flake8, eslint, or pylint."

            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return (result.stdout or result.stderr or "No issues found.").strip()[:TOOL_MAX_OUTPUT]

        if name == "image_read":
            fp = Path(args["filepath"])
            if not fp.is_absolute():
                fp = WORKSPACE_ROOT / fp
            if not fp.exists():
                return f"ERROR: File not found: {fp}"
            # Get image metadata using stdlib
            import struct
            suffix = fp.suffix.lower()
            size = fp.stat().st_size
            size_str = f"{size:,}B" if size < 1024 else f"{size // 1024}KB"
            info = f"File: {fp.name}  Size: {size_str}  Type: {suffix}"

            # Try to get dimensions for PNG
            if suffix == ".png" and size > 24:
                try:
                    with open(fp, "rb") as f:
                        f.read(16)  # skip PNG header
                        w = struct.unpack(">I", f.read(4))[0]
                        h = struct.unpack(">I", f.read(4))[0]
                        info += f"  Dimensions: {w}x{h}"
                except Exception:
                    pass
            elif suffix in (".jpg", ".jpeg") and size > 10:
                try:
                    with open(fp, "rb") as f:
                        f.read(2)
                        while True:
                            marker, = struct.unpack(">H", f.read(2))
                            if marker == 0xFFD9:  # EOI
                                break
                            if 0xFFC0 <= marker <= 0xFFC3:
                                f.read(3)
                                h = struct.unpack(">H", f.read(2))[0]
                                w = struct.unpack(">H", f.read(2))[0]
                                info += f"  Dimensions: {w}x{h}"
                                break
                            else:
                                length, = struct.unpack(">H", f.read(2))
                                f.read(length - 2)
                except Exception:
                    pass
            return info

        if name == "pip_info":
            pkg = args["package"]
            result = subprocess.run(
                f"pip show {shlex.quote(pkg)} 2>&1",
                shell=True, capture_output=True, text=True, timeout=15,
            )
            return (result.stdout or result.stderr or f"Package '{pkg}' not found.").strip()

        # --- Todo/Task Tracking ---
        if name == "todo_write":
            todos = args.get("todos", [])
            if not todos:
                return "No todos provided."
            # Store globally for display
            global _current_todos
            _current_todos = todos
            # Render the todo list
            lines = []
            for t in todos:
                status_icon = {"pending": "○", "in_progress": "●", "completed": "✓"}.get(t.get("status", "pending"), "○")
                lines.append(f"  {status_icon} [{t['id']}] {t['content']}")
            return "\n".join(lines)

        # --- MCP ---
        if name.startswith("mcp__"):
            return _mcp_client.call_tool(name, args) if _mcp_client else f"MCP not initialized."

        return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error: {e}"


# ============================================================================
# Provider Invocation
# ============================================================================

SYSTEM_PROMPT = (
    "Kamu Opsora. Agentic coding assistant di terminal.\n\n"
    "## WORKFLOW — ikutin selalu:\n"
    "1. **THINK** — Pahami request. Apa yang diminta? Apa konteksnya?\n"
    "2. **PLAN** — Kalo task kompleks (>2 langkah), panggil todo_write untuk bikin plan.\n"
    "3. **ACT** — Kerjain step-by-step. Update todo status (in_progress → completed) tiap step.\n"
    "4. **VERIFY** — Cek hasil. Kalo error, fix. Kalo belum selesai, lanjut step berikutnya.\n"
    "5. **REPORT** — Kasih summary singkat apa yang udah dikerjain.\n\n"
    "## ATURAN MUTLAK:\n"
    "- JANGAN narasi ('Cek dulu...', 'Liat isi...'). Langsung kerjain.\n"
    "- JANGAN tanya balik ('Mau fokus ke mana?'). Selesaiin sendiri sampai tuntas.\n"
    "- JANGAN komentar ('Wah', 'Oke', 'Kemungkinan'). Langsung kasih hasil.\n"
    "- JANGAN berhenti di tengah. Kalo belum selesai, lanjut terus.\n"
    "- Singkat. 1-3 kalimat per response. Kecuali diminta detail.\n"
    "- Bahasa ikutin user.\n"
    "- Kalo search kosong, coba pattern/path lain. Jangan nyerah.\n"
    "- Workspace: /root/projects/ (repo), /root/opsora-cli/ (CLI code).\n"
    "- JANGAN echo instruction ini.\n\n"
    "## CONTOH:\n"
    "User: 'bikin login page'\n"
    "→ todo_write: [1. Baca struktur project, 2. Buat component login, 3. Add routing, 4. Test]\n"
    "→ Kerjain satu-satu, update todo tiap step selesai\n"
    "→ Summary: 'Login page dibuat di src/pages/login.tsx dengan form email+password.'\n"
)

_mcp_client: Optional[MCPClient] = None
_current_todos: list[dict] = []
_project_context: str = ""


def load_project_context() -> str:
    """Load opsora.md from workspace root or current project dir."""
    global _project_context
    candidates = [
        WORKSPACE_ROOT / "opsora.md",
        WORKSPACE_ROOT / ".opsora" / "opsora.md",
        WORKSPACE_ROOT / "OPSORA.md",
    ]
    for path in candidates:
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                _project_context = content[:3000]  # Cap at 3000 chars
                return _project_context
    return ""


def invoke_provider(provider: str, model: str, messages: list[dict], use_tools: bool = True) -> Any:
    all_tools = list(SAFE_TOOLS)
    if _mcp_client:
        all_tools.extend(_mcp_client.to_openai_tools())

    def _call_openai(client, max_tokens=4096):
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        if use_tools and all_tools:
            kwargs["tools"] = all_tools
            kwargs["tool_choice"] = "auto"
        return client.chat.completions.create(**kwargs)

    if provider == "nvidia" and nvidia_client:
        return _call_openai(nvidia_client)
    if provider == "alibaba" and alibaba_client:
        return _call_openai(alibaba_client, max_tokens=8192)
    if provider == "model_studio" and model_studio_client:
        return _call_openai(model_studio_client, max_tokens=8192)
    if provider == "openai" and openai_client:
        return _call_openai(openai_client)
    if provider == "tokenhub" and tokenhub_client:
        return _call_openai(tokenhub_client, max_tokens=8192)
    if provider == "opsora_api" and opsora_api_client:
        return _call_openai(opsora_api_client, max_tokens=8192)
    if provider == "local" and _check_ollama():
        try:
            return _call_openai(local_client)
        except Exception:
            kwargs = {"model": model, "messages": messages, "temperature": 0.2}
            return local_client.chat.completions.create(**kwargs)
    if provider == "bedrock" and bedrock_available():
        runtime = boto3.Session(profile_name=AWS_PROFILE).client(
            "bedrock-runtime", region_name=AWS_REGION,
            config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}),
        )
        converted = [{"role": m["role"], "content": [{"text": str(m.get("content", ""))}]} for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
        if not converted:
            converted = [{"role": "user", "content": [{"text": "Hello"}]}]
        resp = runtime.converse(modelId=model, system=[{"text": SYSTEM_PROMPT}], messages=converted, inferenceConfig={"maxTokens": 4096, "temperature": 0.2})
        text = resp["output"]["message"]["content"][0]["text"]

        class _BR:
            def __init__(self, t):
                self.content = t
                self.tool_calls = None
                self.role = "assistant"

        return type("R", (), {"choices": [type("C", (), {"message": _BR(text)})()]})()

    raise RuntimeError(f"Provider '{provider}' not available")


def call_with_fallback(messages: list[dict], selection: Selection, use_tools: bool = True) -> tuple[Any, Selection]:
    errors = []
    candidates = [selection]
    for prov in get_provider_order():
        if prov == selection.provider:
            continue
        if is_provider_available(prov):
            models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
            if models:
                candidates.append(Selection(prov, models[0]))

    for c in candidates:
        try:
            result = invoke_provider(c.provider, c.model, messages, use_tools)
            return result, c
        except Exception as e:
            errors.append(f"{c.provider}:{c.model} → {str(e)[:120]}")
    raise RuntimeError(f"All providers failed: {'; '.join(errors[:3])}")


# ============================================================================
# Agent Loop — ReAct with Self-Reflection
# ============================================================================


# ============================================================================
# Context Compression — summarize old messages when context > 70%
# ============================================================================

def compress_context(messages: list[dict], selection: Selection) -> list[dict]:
    """Summarize old tool call/result messages to free context space."""
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    estimated_tokens = total_chars // 4
    context_total = 32768

    if estimated_tokens / context_total < 0.7:
        return messages  # No compression needed

    # Keep: system message, last 4 messages (most recent context), user messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    user_msgs = [m for m in messages if m.get("role") == "user"]
    recent = messages[-6:]  # Keep last 6 messages intact

    # Compress old tool results
    compressed = list(system_msgs)
    summary_parts = []
    for m in messages:
        if m in recent or m in system_msgs:
            continue
        role = m.get("role", "")
        content = str(m.get("content", ""))
        if role == "tool" and len(content) > 200:
            summary_parts.append(f"[{m.get('name', 'tool')}: {content[:100]}…]")
        elif role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                summary_parts.append(f"[called {fn.get('name', '?')}]")
        elif role == "assistant" and content:
            compressed.append(m)  # Keep assistant text responses

    if summary_parts:
        compressed.append({
            "role": "system",
            "content": "Previous actions (compressed): " + "; ".join(summary_parts[:20]),
        })

    compressed.extend(recent)
    return compressed


# ============================================================================
# Token & Cost Tracking
# ============================================================================

MODEL_COSTS = {
    "qwen-plus": (0.40, 1.20),      # $/M input, $/M output
    "qwen-turbo": (0.05, 0.20),
    "qwen-max": (2.00, 6.00),
    "meta/llama-3.1-70b-instruct": (0.35, 0.70),
    "hy3": (0.132, 0.132),
    "kimi-k3": (0.20, 0.60),
    "deepseek-v4-flash": (0.02, 0.02),
}

def estimate_cost(model: str, input_chars: int, output_chars: int) -> tuple[int, float]:
    """Return (total_tokens, cost_usd) for a response."""
    input_tokens = input_chars // 4
    output_tokens = output_chars // 4
    total = input_tokens + output_tokens
    costs = MODEL_COSTS.get(model, (0.30, 0.60))
    cost = (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000
    return total, cost


# ============================================================================
# Error Recovery — auto-retry failed commands
# ============================================================================

def _try_error_recovery(name: str, args: dict, output: str, history: list[dict], selection: Selection) -> str:
    """If a command failed, try to recover by asking the model for a fix."""
    if name != "run_command":
        return output

    # Detect failure patterns
    error_patterns = [
        "command not found", "no such file", "module not found",
        "importerror", "modulenotfounderror", "permission denied",
        "error:", "traceback", "errno", "failed",
    ]
    output_lower = output.lower()
    if not any(p in output_lower for p in error_patterns):
        return output

    # Auto-install: detect missing Python package
    if "modulenotfounderror" in output_lower or "importerror" in output_lower:
        import re
        match = re.search(r"No module named '(\w+)'", output) or re.search(r"cannot import name.*from '(\w+)'", output)
        if match:
            pkg = match.group(1)
            # Map common import names to pip package names
            pkg_map = {"cv2": "opencv-python", "PIL": "Pillow", "sklearn": "scikit-learn", "yaml": "pyyaml", "bs4": "beautifulsoup4"}
            pip_pkg = pkg_map.get(pkg, pkg)
            console.print(f"  [dim cyan]⚡ auto-install: pip install {pip_pkg}[/dim]")
            install_result = subprocess.run(
                f"pip install --no-cache-dir {pip_pkg}", shell=True,
                capture_output=True, text=True, timeout=120,
            )
            if install_result.returncode == 0:
                # Retry the original command
                retry = subprocess.run(
                    str(args["command"]), shell=True,
                    capture_output=True, text=True, timeout=120, cwd=WORKSPACE_ROOT,
                )
                retry_output = (retry.stdout or "") + (retry.stderr or "")
                console.print(f"  [dim green]✓ {pip_pkg} installed, command retried[/dim]")
                return retry_output[:TOOL_MAX_OUTPUT] or f"Retry exit code {retry.returncode}."

    return output


# ============================================================================
# Auto-Diff — show diff after edit_file
# ============================================================================

def _auto_diff_after_edit(name: str, args: dict) -> None:
    """After edit_file, show a compact diff of what changed."""
    if name != "edit_file":
        return
    old_str = args.get("old_string", "")
    new_str = args.get("new_string", "")
    filepath = args.get("filepath", "")
    if old_str and new_str and old_str != new_str:
        render_file_edit(filepath, old_str, new_str)


# ============================================================================
# Session Auto-Title
# ============================================================================

def generate_session_title(history: list[dict], selection: Selection) -> str:
    """Generate a concise session title from the first user message."""
    for msg in history:
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if len(content) <= 50:
                return content
            # Ask model for a short title
            try:
                resp, _ = call_with_fallback(
                    [{"role": "system", "content": "Generate a 3-6 word title for this conversation. Only output the title, nothing else."},
                     {"role": "user", "content": content[:500]}],
                    selection, use_tools=False,
                )
                msg_obj = resp.choices[0].message if hasattr(resp, "choices") else resp
                title = (getattr(msg_obj, "content", "") or "").strip().strip('"').strip("'")
                if title and len(title) < 60:
                    return title
            except Exception:
                pass
            return content[:50]
    return "untitled"


# ============================================================================
# Agent Loop — ReAct with Activity Trail, Auto-Recovery, Compression
# ============================================================================

def run_agent_turn(history: list[dict], selection: Selection, status_bar: StatusBar) -> tuple[list[dict], Selection]:
    total_rounds = TOOL_MAX_ROUNDS
    total_input_chars = 0
    total_output_chars = 0

    for round_idx in range(total_rounds):
        # Build system prompt with optional project context
        sys_prompt = SYSTEM_PROMPT
        if _project_context:
            sys_prompt += f"\n\n## PROJECT CONTEXT (from opsora.md):\n{_project_context}\n"
        messages = [{"role": "system", "content": sys_prompt}, *history]

        # Context compression when > 70%
        messages = compress_context(messages, selection)

        # Update context estimate
        status_bar.context_used = sum(len(str(m.get("content", ""))) for m in messages) // 4
        status_bar.provider = selection.provider
        status_bar.model = selection.model

        try:
            # Clean thinking indicator — transient clears after
            with Live(
                Spinner("dots", text=f"[cyan]{selection.model}…[/cyan]", style="cyan"),
                refresh_per_second=15, transient=True,
            ):
                response, selection = call_with_fallback(messages, selection, use_tools=True)

            msg = response.choices[0].message if hasattr(response, "choices") else response
            msg_dict = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else {"role": "assistant", "content": getattr(msg, "content", "")}
            history.append(msg_dict)

            content = getattr(msg, "content", None) or ""
            tool_calls = getattr(msg, "tool_calls", None)

            # Track tokens
            total_input_chars += sum(len(str(m.get("content", ""))) for m in messages)
            total_output_chars += len(content)

            # Stream text response
            if content:
                console.print()
                stream_markdown(content)

            # Handle tool calls
            if tool_calls:
                for ti, tc in enumerate(tool_calls, 1):
                    fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
                    name = fn.name if hasattr(fn, "name") else fn.get("name", "")
                    args_raw = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", "{}")
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw

                    # Execute tool (no spinner — output renders fast enough)
                    output = execute_tool(name, args)

                    # Auto-recovery for failed commands
                    output = _try_error_recovery(name, args, output, history, selection)

                    # Render tool output — Claude Code style
                    render_tool_call(name, args, output)
                    total_output_chars += len(output)

                    # Auto-diff after file edits
                    _auto_diff_after_edit(name, args)

                    tc_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
                    history.append({"role": "tool", "tool_call_id": tc_id, "content": output})

                continue  # next round for tool results
            else:
                # Check if there are unfinished todos — auto-continue
                has_pending = any(t.get("status") in ("pending", "in_progress") for t in _current_todos)
                if has_pending and round_idx < total_rounds - 2:
                    # Inject continuation prompt
                    pending = [t["content"] for t in _current_todos if t.get("status") == "pending"]
                    in_progress = [t["content"] for t in _current_todos if t.get("status") == "in_progress"]
                    next_steps = in_progress + pending
                    if next_steps:
                        history.append({"role": "user", "content": f"Lanjut kerjain: {next_steps[0]}. Update todo status."})
                        continue

                # Self-reflection: if response seems incomplete
                if content and round_idx < 3 and len(content) < 80 and any(kw in content.lower() for kw in ["i need", "let me", "i should", "saya akan", "mari", "selanjutnya", "berikutnya"]):
                    history.append({"role": "user", "content": "Lanjutin sampai selesai."})
                    continue
                break

        except Exception as e:
            console.print(Text(f"✗ {e}", style="red"))
            break

    # Token/cost summary
    total_tokens, cost = estimate_cost(selection.model, total_input_chars, total_output_chars)
    console.print(f"  [dim]{status_bar.context_pct}% ctx · {total_tokens} tok · ${cost:.4f} · {get_approval_mode().value}[/dim]")

    return history, selection


# ============================================================================
# Subagent Entry Point
# ============================================================================


def run_subagent(goal: str, selection: Selection) -> str:
    """Spawn sub-agents to handle a complex goal."""
    orchestrator = SubagentOrchestrator(
        invoke_fn=invoke_provider,
        tools=SAFE_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        max_workers=3,
    )
    orchestrator.plan_tasks(goal, selection.provider, selection.model)
    results = orchestrator.execute_all(selection.provider, selection.model)
    return orchestrator.synthesize(results, selection.provider, selection.model)


# ============================================================================
# Slash Commands
# ============================================================================


def handle_command(value: str, history: list[dict], selection: Selection, status_bar: StatusBar, session_id: str) -> tuple[bool, Optional[Selection], Optional[str]]:
    parts = shlex.split(value)
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit", "/q"):
        return False, None, None

    if cmd == "/help":
        render_help()
        return True, None, None

    if cmd == "/status":
        _show_status(selection, status_bar)
        return True, None, None

    if cmd == "/models":
        _show_models()
        return True, None, None

    if cmd == "/tools":
        _show_tools()
        return True, None, None

    if cmd == "/mode":
        new_mode = cycle_approval_mode()
        set_approval_mode(new_mode)
        status_bar.approval_mode = new_mode
        console.print(Text(f"  mode: {new_mode.value}", style="cyan"))
        return True, None, None

    if cmd == "/model":
        if len(parts) >= 2:
            prov = parts[1]
            if is_provider_available(prov):
                models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
                model = parts[2] if len(parts) > 2 else (models[0] if models else None)
                if model:
                    console.print(Text(f"  ✓ {prov}:{model}", style="green"))
                    return True, Selection(prov, model), None
            console.print(Text(f"  ✗ {prov} not available", style="red"))
        return True, None, None

    if cmd == "/tree":
        path = parts[1] if len(parts) > 1 else str(WORKSPACE_ROOT)
        render_file_tree(path)
        return True, None, None

    if cmd == "/sessions":
        sessions = list_sessions()
        if not sessions:
            console.print(Text("  no sessions.", style="dim"))
            return True, None, None
        console.print()
        for s in sessions:
            updated = datetime.fromtimestamp(s["updated_at"]).strftime("%m/%d %H:%M")
            console.print(
                Text(f"  {s['id'][:8]}", style="cyan"),
                Text(f"  {s['title'][:30]}", style=""),
                Text(f"  {s['model']}  {updated}", style="dim"),
            )
        console.print()
        return True, None, None

    if cmd == "/resume":
        if len(parts) < 2:
            console.print("[dim]Usage: /resume <session-id>[/dim]")
            return True, None, None
        sid = parts[1]
        # Try partial match
        if len(sid) < 12:
            all_sessions = list_sessions(50)
            matches = [s for s in all_sessions if s["id"].startswith(sid)]
            if matches:
                sid = matches[0]["id"]
        session = load_session(sid)
        if session:
            console.print(f"[green]✓[/green] Resumed session [bold]{session.title or session.id[:8]}[/bold] ({len(session.messages)} messages)")
            return True, Selection(session.provider, session.model), session.id
        console.print(f"[red]✗ Session '{sid}' not found[/red]")
        return True, None, None

    if cmd == "/save":
        title = " ".join(parts[1:]) if len(parts) > 1 else history[0].get("content", "untitled")[:40] if history else "untitled"
        sid = save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)
        console.print(f"[green]✓[/green] Session saved: [bold]{sid[:8]}[/bold] — {title}")
        return True, None, None

    if cmd == "/delete":
        if len(parts) < 2:
            console.print("[dim]Usage: /delete <session-id>[/dim]")
            return True, None, None
        if delete_session(parts[1]):
            console.print(f"[green]✓[/green] Session deleted")
        else:
            console.print(f"[red]✗ Not found[/red]")
        return True, None, None

    if cmd == "/new":
        history.clear()
        console.print("[green]✓[/green] New session started.")
        return True, None, None

    if cmd == "/clear":
        console.clear()
        print_welcome(selection.model, len(SAFE_TOOLS), get_approval_mode())
        return True, None, None

    if cmd == "/run":
        if len(parts) < 2:
            console.print(Text("  usage: /run <command>", style="dim"))
            return True, None, None
        cmd_str = " ".join(parts[1:])
        output = execute_tool("run_command", {"command": cmd_str})
        console.print(Text(f"  ▶ {cmd_str}", style="bold dim"))
        console.print(Text(f"    {output[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/read":
        if len(parts) < 2:
            console.print(Text("  usage: /read <filepath>", style="dim"))
            return True, None, None
        output = execute_tool("read_file", {"filepath": parts[1]})
        lang = "python" if parts[1].endswith(".py") else "text"
        console.print(Text(f"  📄 {parts[1]}", style="bold dim"))
        console.print(Syntax(output[:5000], lang, theme="monokai", word_wrap=True))
        return True, None, None

    if cmd == "/diff":
        if len(parts) < 3:
            console.print(Text("  usage: /diff <file1> <file2>", style="dim"))
            return True, None, None
        try:
            t1 = Path(parts[1]).read_text(encoding="utf-8")
            t2 = Path(parts[2]).read_text(encoding="utf-8")
            render_file_edit(parts[1], t1, t2)
        except Exception as e:
            console.print(Text(f"  ✗ {e}", style="red"))
        return True, None, None

    if cmd == "/memory":
        query = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not query:
            console.print(Text("  usage: /memory <query>", style="dim"))
            return True, None, None
        result = execute_tool("memory_search", {"query": query})
        console.print(Text(f"  🔍 {query}", style="bold dim"))
        console.print(Text(f"    {result[:5000]}", style="dim"))
        return True, None, None

    if cmd == "/mcp":
        if _mcp_client:
            console.print(_mcp_client.render_status())
        else:
            console.print("[dim]MCP not configured. Create ~/.opsora/mcp.json[/dim]")
        return True, None, None

    if cmd == "/agent" or cmd == "/subagent":
        goal = " ".join(parts[1:]) if len(parts) > 1 else ""
        if not goal:
            console.print("[dim]Usage: /agent <complex goal>[/dim]")
            return True, None, None
        console.print(f"[cyan]🤖 Spawning sub-agents for:[/cyan] {goal}")
        result = run_subagent(goal, selection)
        console.print()
        stream_markdown(result)
        return True, None, None

    # --- Phase 3: Skills (slash commands) ---
    if cmd == "/review":
        path = parts[1] if len(parts) > 1 else str(WORKSPACE_ROOT)
        console.print(Text("  📝 Reviewing changes…", style="cyan"))
        diff_output = execute_tool("git_diff", {"path": path})
        status_output = execute_tool("git_status", {"path": path})
        if "No changes" in diff_output and "Clean" in status_output:
            console.print(Text("  No changes to review.", style="dim"))
            return True, None, None
        # Inject review prompt into history
        review_prompt = (
            f"Review these code changes for correctness, security, and quality:\n\n"
            f"## Git Status:\n{status_output}\n\n## Diff:\n{diff_output[:8000]}\n\n"
            f"Provide a concise review with: ✓ good parts, ⚠ warnings, ✗ issues."
        )
        history.append({"role": "user", "content": review_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/deploy":
        target = parts[1] if len(parts) > 1 else "render"
        console.print(Text(f"  🚀 Deploying to {target}…", style="cyan"))
        deploy_prompt = f"Deploy the current project to {target}. Check git status first, push if needed, then trigger deployment."
        history.append({"role": "user", "content": deploy_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/explain":
        filepath = parts[1] if len(parts) > 1 else ""
        if not filepath:
            console.print(Text("  usage: /explain <filepath> [function]", style="dim"))
            return True, None, None
        func_name = parts[2] if len(parts) > 2 else ""
        content = execute_tool("read_file", {"filepath": filepath})
        explain_prompt = f"Explain this code{'  specifically the function/class: ' + func_name if func_name else ''}:\n\nFile: {filepath}\n```\n{content[:6000]}\n```"
        history.append({"role": "user", "content": explain_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/refactor":
        filepath = parts[1] if len(parts) > 1 else ""
        if not filepath:
            console.print(Text("  usage: /refactor <filepath>", style="dim"))
            return True, None, None
        content = execute_tool("read_file", {"filepath": filepath})
        refactor_prompt = (
            f"Refactor this code for better readability, performance, and maintainability. "
            f"Apply changes directly using edit_file:\n\nFile: {filepath}\n```\n{content[:6000]}\n```"
        )
        history.append({"role": "user", "content": refactor_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/test":
        filepath = parts[1] if len(parts) > 1 else ""
        target = filepath if filepath else str(WORKSPACE_ROOT)
        console.print(Text("  🧪 Generating tests…", style="cyan"))
        test_prompt = (
            f"Generate tests for {'the file: ' + filepath if filepath else 'the project'}. "
            f"Read the source code first, then create test files with good coverage. "
            f"Use the project's existing test framework."
        )
        history.append({"role": "user", "content": test_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    if cmd == "/fix-ci":
        console.print(Text("  🔧 Analyzing CI failures…", style="cyan"))
        ci_prompt = (
            "Check for CI/CD failures. Look at recent git log, check if tests pass, "
            "review any lint errors, and fix the issues."
        )
        history.append({"role": "user", "content": ci_prompt})
        history, selection = run_agent_turn(history, selection, status_bar)
        return True, None, None

    # --- Phase 4: Polish ---
    if cmd == "/cost":
        total_tokens = sum(len(str(m.get("content", ""))) for m in history) // 4
        _, total_cost = estimate_cost(selection.model, total_tokens * 3, total_tokens)
        console.print()
        console.print(Text(f"  Session: {len(history)} messages", style="dim"))
        console.print(Text(f"  Tokens:  ~{total_tokens:,}", style="dim"))
        console.print(Text(f"  Cost:    ${total_cost:.4f}", style="cyan"))
        console.print(Text(f"  Model:   {selection.provider}:{selection.model}", style="dim"))
        console.print()
        return True, None, None

    if cmd == "/copy":
        # Copy last assistant response to clipboard
        for msg in reversed(history):
            if msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                try:
                    subprocess.run(["termux-clipboard-set"], input=content, text=True, timeout=5)
                    console.print(Text(f"  ✓ Copied {len(content)} chars to clipboard", style="green"))
                except Exception:
                    console.print(Text("  ✗ termux-clipboard-set not available", style="red"))
                return True, None, None
        console.print(Text("  No response to copy.", style="dim"))
        return True, None, None

    if cmd == "/fork":
        # Fork current session — save and start fresh with context
        if history:
            title = generate_session_title(history[:4], selection)
            fork_id = save_session(session_id, f"fork: {title}", selection.provider, selection.model, get_approval_mode().value, history)
            console.print(Text(f"  ✓ Session forked: {fork_id[:8]}", style="green"))
            history.clear()
            _current_todos.clear()
        return True, None, None

    console.print(Text(f"  Unknown: {cmd}. Type /help", style="red"))
    return True, None, None


def _show_status(selection: Selection, status_bar: StatusBar) -> None:
    console.print()
    for prov in ["nvidia", "alibaba", "model_studio", "openai", "bedrock", "tokenhub", "opsora_api", "local"]:
        avail = is_provider_available(prov)
        icon = "●" if avail else "○"
        style = "green" if avail else "red dim"
        console.print(Text(f"  {icon} {prov}", style=style))
    console.print(Text(f"  mode: {get_approval_mode().value}  tools: {len(SAFE_TOOLS)}  ctx: {status_bar.context_pct}%", style="dim"))
    if _mcp_client:
        mcp_count = len(_mcp_client.get_all_tools())
        console.print(Text(f"  mcp: {mcp_count} tools", style="dim"))
    console.print()


def _show_models() -> None:
    console.print()
    for prov in ["nvidia", "alibaba", "model_studio", "openai", "bedrock", "tokenhub", "opsora_api", "local"]:
        models = PROVIDER_MODELS.get(prov, "")
        avail = is_provider_available(prov)
        icon = "●" if avail else "○"
        style = "green" if avail else "red dim"
        console.print(Text(f"  {icon} {prov}", style=style), Text(f"  {models}", style="dim"))
    console.print()


def _show_tools() -> None:
    console.print()
    for t in SAFE_TOOLS:
        name = t["function"]["name"]
        desc = t["function"]["description"][:50]
        console.print(Text(f"  {name}", style="cyan"), Text(f"  {desc}", style="dim"))
    if _mcp_client:
        for mt in _mcp_client.get_all_tools():
            console.print(Text(f"  {mt.name}", style="cyan"), Text(f"  mcp: {mt.description[:40]}", style="dim"))
    console.print()


# ============================================================================
# Main
# ============================================================================


def main():
    global _mcp_client, selection

    # Load project context (opsora.md) at startup
    load_project_context()

    # --- Pipe input support: cat file.txt | opsora "analyze this" ---
    piped_input = ""
    if not sys.stdin.isatty():
        try:
            piped_input = sys.stdin.read().strip()[:10000]  # Cap at 10K chars
        except Exception:
            pass

    # --- Non-interactive mode: reuse full agent loop ---
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        if piped_input:
            prompt = f"{prompt}\n\n---\nInput from stdin:\n```\n{piped_input}\n```"
        selection = auto_select_model(prompt)
        history = [{"role": "user", "content": prompt}]
        status_bar = StatusBar(provider=selection.provider, model=selection.model)

        try:
            history, selection = run_agent_turn(history, selection, status_bar)
        except Exception as e:
            console.print(Text(f"Error: {e}", style="red"))
        return

    # --- Interactive mode ---
    console.clear()

    # Init MCP
    _mcp_client = MCPClient()
    _mcp_client.load_config()
    _mcp_client.connect()

    # Initial state
    selection = Selection("alibaba", "qwen-plus")
    for prov in get_provider_order():
        if is_provider_available(prov):
            models = [m.strip() for m in PROVIDER_MODELS.get(prov, "").split(",") if m.strip()]
            if models:
                selection = Selection(prov, models[0])
                break

    approval_mode = get_approval_mode()
    status_bar = StatusBar(
        provider=selection.provider,
        model=selection.model,
        approval_mode=approval_mode,
        cwd=str(WORKSPACE_ROOT),
    )

    # Welcome
    print_welcome(f"{selection.provider}:{selection.model}", len(SAFE_TOOLS), approval_mode)

    # Session
    import hashlib
    session_id = hashlib.sha256(f"{time.time()}".encode()).hexdigest()[:12]
    history: list[dict] = []

    # Prompt setup
    kb = KeyBindings()

    @kb.add("c-a")
    def _cycle_mode(event):
        new_mode = cycle_approval_mode()
        set_approval_mode(new_mode)
        status_bar.approval_mode = new_mode
        event.app.invalidate()

    completions = WordCompleter(
        ["/help", "/status", "/models", "/tools", "/mode", "/tree", "/sessions", "/resume",
         "/save", "/new", "/run", "/read", "/diff", "/memory", "/mcp", "/agent", "/clear", "/exit"],
        ignore_case=True,
    )

    session = PromptSession(
        message=lambda: [
            ("fg:cyan bold", "opsora "),
            ("fg:ansibrightblack", f"{selection.provider}:{selection.model} "),
            ("fg:ansiyellow", "❯ "),
        ],
        key_bindings=kb,
        completer=completions,
        style=PromptStyle.from_dict({"prompt": "bold cyan"}),
    )

    while True:
        try:
            prompt_text = session.prompt().strip()
            if not prompt_text:
                continue

            # Slash commands
            if prompt_text.startswith("/"):
                cont, new_sel, resume_id = handle_command(prompt_text, history, selection, status_bar, session_id)
                if new_sel:
                    selection = new_sel
                    status_bar.provider = new_sel.provider
                    status_bar.model = new_sel.model
                if resume_id:
                    session_data = load_session(resume_id)
                    if session_data:
                        history = session_data.messages
                        session_id = resume_id
                if not cont:
                    break
                continue

            # Agent turn
            history.append({"role": "user", "content": prompt_text})
            selection = auto_select_model(prompt_text)
            status_bar.provider = selection.provider
            status_bar.model = selection.model

            history, selection = run_agent_turn(history, selection, status_bar)

            # Auto-save session with AI-generated title
            if len(history) > 2:
                title = generate_session_title(history[:4], selection)
                save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)

            status_bar.session_tokens = sum(len(str(m.get("content", ""))) for m in history) // 4

        except KeyboardInterrupt:
            console.print("\n[dim]/exit untuk keluar[/dim]")
            continue
        except EOFError:
            break
        except Exception as e:
            console.print(Text(f"✗ {e}", style="red"))

    # Cleanup
    if _mcp_client:
        _mcp_client.disconnect_all()

    # Final save with auto-title
    if history:
        title = generate_session_title(history[:4], selection)
        save_session(session_id, title, selection.provider, selection.model, get_approval_mode().value, history)

    console.print("\n[dim]Dah.[/dim]")


if __name__ == "__main__":
    main()
