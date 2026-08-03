"""Opsora Self-Reflection v2 — Real LLM-powered reflection before tool execution."""
from __future__ import annotations
import json, os, re

_DANGEROUS_PATTERNS = [
    (r"\brm\s+-rf\b", "rm -rf terdeteksi — bisa hapus semua file!"),
    (r"\brm\s+--no-preserve-root", "rm tanpa preserve-root — sangat berbahaya!"),
    (r"\bdd\s+.*of=/dev/", "dd ke device — bisa overwrite disk!"),
    (r"\bmkfs\b", "mkfs terdeteksi — akan format filesystem!"),
    (r"\bsudo\s+", "sudo terdeteksi — akses root, hati-hati!"),
    (r"\b(DROP|TRUNCATE)\s+(TABLE|DATABASE)\b", "SQL destructif — data bisa hilang permanen!"),
    (r"\bdelete\s+from\b", "SQL DELETE — pastikan WHERE clause benar!"),
    (r"\boverwrite\b", "Operasi overwrite — data lama bisa hilang!"),
    (r"\bformat\s+[a-z]:", "Format disk terdeteksi!"),
    (r"\b(shutdown|reboot|poweroff)\b", "System power command — pastikan ini disengaja!"),
    (r"\bcurl\b.*\|\s*(bash|sh)\b", "Pipe ke shell dari curl — risiko kode berbahaya!"),
    (r"\bwget\b.*\|\s*(bash|sh)\b", "Pipe ke shell dari wget — risiko kode berbahaya!"),
    (r"\bchmod\s+777\b", "chmod 777 — permission terlalu terbuka!"),
]
_SYSTEM_PROMPT = (
    "Kamu adalah safety analyzer untuk CLI assistant. "
    "Analisis perintah dan berikan penilaian keamanan. "
    'Jawab HANYA dalam JSON valid: {"safe": bool, "risks": [...], "improvement": "saran", "confidence": 0.0-1.0}. '
    "safe=false jika ada risiko data hilang, system damage, atau privasi. "
    "risks dalam Bahasa Indonesia. confidence: seberapa yakin (0.0-1.0)."
)

def _rule_based_reflect(user_input: str, tool_calls: list[dict]) -> dict:
    """Fallback reflection using regex pattern matching."""
    combined = user_input + " " + " ".join(
        str(tc.get("arguments", "")) for tc in (tool_calls or [])
    )
    risks = [msg for pat, msg in _DANGEROUS_PATTERNS if re.search(pat, combined, re.IGNORECASE)]
    return {
        "safe": len(risks) == 0, "risks": risks,
        "improvement": "Tambahkan --dry-run jika tersedia" if risks else "Oke, lanjut!",
        "confidence": 0.7 if not risks else 0.9, "method": "rule-based",
    }

def _get_fast_client():
    """Return (OpenAI client, model_name) using the fastest available provider."""
    from openai_lite import OpenAI
    dash_key = os.environ.get("DASHSCOPE_API_KEY", "")
    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    if dash_key:
        return OpenAI(api_key=dash_key, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", timeout=10), "qwen-turbo"
    if nvidia_key:
        return OpenAI(api_key=nvidia_key, base_url="https://integrate.api.nvidia.com/v1", timeout=10), "meta/llama-3.1-8b-instruct"
    return None, None

def reflect(user_input: str, tool_calls: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    """Run LLM-powered reflection. Falls back to rule-based if LLM unavailable."""
    tool_calls = tool_calls or []
    history = history or []
    fallback = _rule_based_reflect(user_input, tool_calls)
    # Build concise context for the LLM
    tc_summary = json.dumps(
        [{"name": tc.get("name", "?"), "args": str(tc.get("arguments", ""))[:200]} for tc in tool_calls[:5]],
        ensure_ascii=False,
    )[:400]
    recent = ""
    if history:
        recent = json.dumps(
            [{"role": m.get("role", ""), "content": str(m.get("content", ""))[:100]} for m in history[-4:]],
            ensure_ascii=False,
        )[:400]
    user_msg = (
        f"User minta: {user_input[:300]}\n"
        f"Tool calls: {tc_summary}\nKonteks terakhir: {recent}\nAnalisis keamanan dan berikan saran."
    )
    client, model = _get_fast_client()
    if client is None:
        return fallback
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
            temperature=0.1, max_tokens=256,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        for key in ("safe", "risks", "improvement", "confidence"):
            result.setdefault(key, fallback[key])
        result["method"] = "llm"
        result["model"] = model
        # If LLM says safe but rules say dangerous, trust the rules
        if result.get("safe") and not fallback["safe"]:
            result["safe"] = False
            result["risks"] = fallback["risks"] + result.get("risks", [])
            result["confidence"] = max(result.get("confidence", 0.5), 0.85)
        return result
    except Exception:
        fallback["method"] = "rule-based-fallback"
        return fallback
