"""Opsora Cost Tracker — Real token/cost tracking from API responses."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Optional

# Pricing: (input $/M tokens, output $/M tokens)
MODEL_COSTS: dict[str, tuple[float, float]] = {
    "qwen-plus": (0.40, 1.20), "qwen-turbo": (0.05, 0.20), "qwen-max": (2.00, 6.00),
    "qwen3-coder-flash": (0.15, 0.60),
    "meta/llama-3.1-70b-instruct": (0.35, 0.70), "meta/llama-3.1-8b-instruct": (0.05, 0.10),
    "hy3": (0.132, 0.132), "kimi-k3": (0.20, 0.60), "deepseek-v4-flash": (0.02, 0.02),
}
_DEFAULT_COST = (0.30, 0.60)

@dataclass
class _Entry:
    model: str; prompt_tokens: int; completion_tokens: int
    total_tokens: int; cost_usd: float; timestamp: float

def extract_usage(response: Any) -> dict:
    """Extract token usage from an OpenAI-compatible API response.
    Returns dict with prompt_tokens, completion_tokens, total_tokens or empty dict."""
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {}
    def _get(obj, key, default=0):
        v = getattr(obj, key, None) if hasattr(obj, key) else (obj.get(key) if isinstance(obj, dict) else None)
        return v or default
    pt, ct = _get(usage, "prompt_tokens"), _get(usage, "completion_tokens")
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": _get(usage, "total_tokens") or (pt + ct)}

def _compute_cost(model: str, pt: int, ct: int) -> float:
    r = MODEL_COSTS.get(model, _DEFAULT_COST)
    return (pt * r[0] + ct * r[1]) / 1_000_000

class CostTracker:
    """In-memory cost tracker for a single CLI session."""
    def __init__(self) -> None:
        self._entries: list[_Entry] = []

    def record(self, model: str, usage_dict: dict) -> Optional[_Entry]:
        """Record a response's token usage. Returns entry or None if empty.

        total_tokens is computed from prompt + completion tokens when the
        upstream response omits it.
        """
        if not usage_dict:
            return None
        pt = usage_dict.get("prompt_tokens", 0) or 0
        ct = usage_dict.get("completion_tokens", 0) or 0
        total = usage_dict.get("total_tokens") or (pt + ct)
        if not total:
            return None
        entry = _Entry(model=model, prompt_tokens=pt, completion_tokens=ct,
                       total_tokens=total,
                       cost_usd=_compute_cost(model, pt, ct), timestamp=time.time())
        self._entries.append(entry)
        return entry

    def record_response(self, response: Any) -> Optional[_Entry]:
        """Extract usage from a response and record it."""
        model = getattr(response, "model", "") or ""
        usage = extract_usage(response)
        return self.record(model, usage) if usage else None

    def session_total(self) -> dict:
        """Return aggregated totals: total_tokens, total_cost, by_model breakdown."""
        total_tokens, total_cost, by_model = 0, 0.0, {}
        for e in self._entries:
            total_tokens += e.total_tokens; total_cost += e.cost_usd
            b = by_model.setdefault(e.model, {"tokens": 0, "cost": 0.0, "calls": 0})
            b["tokens"] += e.total_tokens; b["cost"] += e.cost_usd; b["calls"] += 1
        return {"total_tokens": total_tokens, "total_cost": total_cost,
                "total_calls": len(self._entries), "by_model": by_model}

    def render_summary(self) -> str:
        """Return a human-readable cost summary string (for Rich print)."""
        t = self.session_total()
        if t["total_calls"] == 0:
            return "[dim]Belum ada usage yang tercatat.[/dim]"
        lines = [f"[bold cyan]💰 Session Cost Summary[/bold cyan]",
                 f"  Total calls  : {t['total_calls']}", f"  Total tokens : {t['total_tokens']:,}",
                 f"  Total cost   : [green]${t['total_cost']:.4f}[/green]", "", "[bold]Per model:[/bold]"]
        for model, info in sorted(t["by_model"].items()):
            lines.append(f"  {model}: {info['tokens']:,} tokens, {info['calls']} calls, ${info['cost']:.4f}")
        return "\n".join(lines)
