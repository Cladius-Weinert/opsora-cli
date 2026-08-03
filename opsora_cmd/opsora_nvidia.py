"""Opsora NVIDIA Services — Embedding, Safety, Translation, Vision.

All serverless via NVIDIA NIM API. Free tier (Developer Program).
Verified working models (2026-07-31):
  - Embedding: nv-embedqa-e5-v5 (1024d), nemotron-3-embed-1b (2048d)
  - Safety: nemoguard-8b-content-safety, nemotron-safety-guard-8b-v3
  - Translation: riva-translate-4b-instruct-v2 (EN↔ID)
  - Vision: llama-3.2-11b-vision, nemotron-nano-vl-8b, nemotron-nano-12b-v2-vl
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

NVIDIA_URL = "https://integrate.api.nvidia.com/v1"

def _get_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        try:
            for line in Path("/root/.opsora/qwen-code/secrets.env").read_text().splitlines():
                if "NVIDIA_API_KEY" in line and "=" in line:
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    return key

def _nvidia_post(endpoint: str, payload: dict, timeout: int = 15) -> dict:
    """POST to the NVIDIA NIM API.

    Uses attribute access on urllib.request so callers/tests can patch
    ``urllib.request.urlopen``. Always returns a dict; transport errors are
    reported as {"error": ...} instead of raising.
    """
    key = _get_key()
    if not key:
        return {"error": "NVIDIA_API_KEY not set"}
    req = urllib.request.Request(
        f"{NVIDIA_URL}/{endpoint}", data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Connection error: {e.reason}"}
    except Exception as e:  # noqa: BLE001 — transport boundary, report upward as data
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


# ============================================================================
# EMBEDDING — for semantic memory search
# ============================================================================

def generate_embedding(text: str, model: str = "nvidia/nv-embedqa-e5-v5") -> list[float] | None:
    """Generate embedding vector (1024d default). Returns None on failure."""
    try:
        data = _nvidia_post("embeddings", {
            "model": model,
            "input": [text[:4096]],
            "input_type": "query",
        })
        return data["data"][0]["embedding"]
    except Exception:
        return None


# ============================================================================
# SAFETY GUARD — check commands before execution
# ============================================================================

_SAFETY_MODEL = "nvidia/llama-3.1-nemotron-safety-guard-8b-v3"

# Dangerous patterns — matched against the lowercased command. Literals must
# be lowercase; regexes handle spacing/flag variants.
_DANGEROUS_PATTERNS: list[str | re.Pattern] = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", "> /dev/sd",
    ":(){:|:&};:", "format c:", "del /f /s",
    re.compile(r"chmod\s+(-\w+\s+)*777\s+/"),
    # Piping a download or file into a shell interpreter executes remote code.
    re.compile(r"\|\s*(bash|sh|zsh|dash)\b"),
    re.compile(r"\beval\b"),
    re.compile(r"\bexec\b"),
]

# Read-only / everyday commands that are approved without an LLM round-trip.
# Only applied when the command contains no shell metacharacters.
_SAFE_COMMANDS = {
    "ls", "git", "pip", "pip3", "python", "python3", "pwd", "which",
    "date", "uname", "hostname", "whoami", "pytest",
}
_SHELL_METACHARACTERS = set("|&;$`<>(){}")

def check_command_safety(command: str) -> dict:
    """Check if a shell command is safe to execute.
    Returns: {"safe": bool, "reason": str, "model": str}
    """
    cmd_lower = command.lower()

    # Rule-based check first (fast, no API call)
    for pat in _DANGEROUS_PATTERNS:
        matched = pat.search(cmd_lower) if isinstance(pat, re.Pattern) else (pat in cmd_lower)
        if matched:
            label = pat.pattern if isinstance(pat, re.Pattern) else pat
            return {"safe": False, "reason": f"Dangerous pattern: {label}", "model": "rule-based"}

    # Known-safe first word with no shell metacharacters → approve without LLM
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    if first_word in _SAFE_COMMANDS and not (_SHELL_METACHARACTERS & set(command)):
        return {"safe": True, "reason": f"Known safe command: {first_word}", "model": "rule-based"}

    # LLM-based check (more nuanced)
    try:
        data = _nvidia_post("chat/completions", {
            "model": _SAFETY_MODEL,
            "messages": [
                {"role": "system", "content": "You are a command safety checker. Analyze if the shell command is safe. Reply JSON: {\"safe\": true/false, \"reason\": \"brief explanation\"}"},
                {"role": "user", "content": f"Is this safe to run on a Linux server? {command}"},
            ],
            "max_tokens": 50,
            "temperature": 0.1,
        })
        result = data["choices"][0]["message"]["content"].strip()
        # Parse JSON response
        if "{" in result:
            parsed = json.loads(result[result.index("{"):result.rindex("}") + 1])
            return {
                "safe": parsed.get("safe", True),
                "reason": parsed.get("reason", "No issues detected"),
                "model": _SAFETY_MODEL,
            }
        return {"safe": "unsafe" not in result.lower(), "reason": result[:100], "model": _SAFETY_MODEL}
    except Exception as e:
        # If API fails, allow the command (fail-open for non-critical)
        return {"safe": True, "reason": f"Safety check unavailable: {str(e)[:50]}", "model": "fallback"}


# ============================================================================
# TRANSLATION — EN↔ID via Riva Translate
# ============================================================================

_TRANSLATE_MODEL = "nvidia/riva-translate-4b-instruct-v2"

def translate_text(text: str, target_lang: str = "Indonesian") -> str:
    """Translate text to target language using NVIDIA Riva."""
    try:
        data = _nvidia_post("chat/completions", {
            "model": _TRANSLATE_MODEL,
            "messages": [
                {"role": "user", "content": f"Translate to {target_lang}: {text}"},
            ],
            "max_tokens": 1024,
            "temperature": 0.1,
        })
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Translation failed: {e}"


# ============================================================================
# VISION — Screenshot/image analysis
# ============================================================================

_VISION_MODELS = [
    "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
    "nvidia/nemotron-nano-12b-v2-vl",
    "meta/llama-3.2-11b-vision-instruct",
]

def analyze_image(image_path: str, prompt: str = "Describe this image in detail.") -> str:
    """Analyze an image using NVIDIA vision models."""
    path = Path(image_path)
    if not path.exists():
        return f"File not found: {image_path}"

    # Read and encode image (open with the original path string)
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    # Determine MIME type
    ext = path.suffix.lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(ext.lstrip("."), "image/jpeg")

    for model in _VISION_MODELS:
        try:
            data = _nvidia_post("chat/completions", {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                "max_tokens": 2048,
                "temperature": 0.3,
            })
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return "All vision models failed."


def analyze_screenshot(prompt: str = "Analyze this terminal screenshot. What do you see? Any errors or issues?") -> str:
    """Find and analyze the latest screenshot."""
    # Search common screenshot locations
    search_dirs = [
        "/mnt/sdcard/DCIM/Screenshots",
        "/sdcard/DCIM/Screenshots",
        "/sdcard/Pictures/Screenshots",
    ]
    latest = None
    latest_time = 0

    for d in search_dirs:
        p = Path(d)
        if p.exists():
            for f in p.iterdir():
                if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.stat().st_mtime > latest_time:
                    latest_time = f.stat().st_mtime
                    latest = f

    if not latest:
        return "No screenshots found."
    return f"[{latest.name}]\n\n{analyze_image(str(latest), prompt)}"
