"""Opsora Cost Tracker — Real token/cost tracking from API responses.

Per-model pricing lives in ``config/model_costs.json`` at the repository
root and is loaded at import time. If that file is missing or malformed the
module falls back to the built-in pricing table below (logging a warning),
so tracker behavior never crashes on configuration problems.
"""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Path to the external pricing config. Tests may monkeypatch this.
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "model_costs.json"
# Single source — preferred over legacy CONFIG_PATH
_SINGLE_SOURCE_CANDIDATES = [
    Path.home() / "config" / "pricing.json",
    Path("/root/config/pricing.json"),
    Path(__file__).resolve().parents[2] / "config" / "pricing.json",
]

# Pricing: (input $/M tokens, output $/M tokens)
# Built-in fallback table, mirroring config/model_costs.json, used when the
# config file is missing or malformed so behavior stays unchanged.
_BUILTIN_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "qwen-plus": (0.40, 1.20), "qwen-turbo": (0.05, 0.20), "qwen-max": (2.00, 6.00),
    "qwen3-coder-flash": (0.15, 0.60),
    "nvidia/llama-3.1-nemotron-70b-instruct": (0.35, 0.70), "nvidia/mistral-nemo-minitron-8b-8k-instruct": (0.05, 0.10),
    "hy3": (0.132, 0.132), "kimi-k3": (0.20, 0.60), "deepseek-v4-flash": (0.02, 0.02),
}
_BUILTIN_DEFAULT_COST: tuple[float, float] = (0.30, 0.60)


def _valid_rate(value: Any) -> bool:
    """True when ``value`` is a non-negative number usable as a $/M-token rate."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _resolve_pricing_path() -> Path | None:
    """Return the pricing file path to load.

    Priority order:
    1. CONFIG_PATH (config/model_costs.json) — canonical CLI pricing source.
       If it exists on disk, use it directly.
    2. If CONFIG_PATH has been monkeypatched to a non-existent path (test
       scenario), return it so the caller's FileNotFoundError branch triggers
       and built-in defaults are used — without falling through to pricing.json.
    3. Single-source candidates (~/config/pricing.json etc.) — used only when
       the default CONFIG_PATH does not exist on disk.
    4. Return None if nothing found (caller uses built-in defaults).
    """
    # Primary: CONFIG_PATH (model_costs.json) always wins when present.
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    # If CONFIG_PATH was monkeypatched to a non-existent/bad path, return it
    # so the caller's error-handling fires and uses built-in defaults.
    _default_config_path = Path(__file__).resolve().parent.parent / "config" / "model_costs.json"
    if CONFIG_PATH != _default_config_path:
        return CONFIG_PATH  # intentionally non-existent — triggers fallback
    # Fallback: single-source candidates when default config is absent
    for p in _SINGLE_SOURCE_CANDIDATES:
        if p.exists():
            return p
    return None


def _load_model_costs(path: Optional[Path] = None) -> tuple[dict[str, tuple[float, float]], tuple[float, float]]:
    """Load per-model pricing from ``path`` (default: single-source or CONFIG_PATH)."""
    if path is not None:
        target = Path(path)
    else:
        resolved = _resolve_pricing_path()
        target = resolved if resolved is not None else CONFIG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Model cost config not found at %s; using built-in defaults", target)
        return dict(_BUILTIN_MODEL_COSTS), _BUILTIN_DEFAULT_COST
    except (OSError, ValueError) as e:  # ValueError covers json.JSONDecodeError
        logger.warning("Model cost config at %s is unreadable or malformed (%s); using built-in defaults", target, e)
        return dict(_BUILTIN_MODEL_COSTS), _BUILTIN_DEFAULT_COST

    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        logger.warning(
            "Model cost config at %s has unexpected structure (need an object with a 'models' object); "
            "using built-in defaults", target)
        return dict(_BUILTIN_MODEL_COSTS), _BUILTIN_DEFAULT_COST

    costs = dict(_BUILTIN_MODEL_COSTS)
    for model, rates in data["models"].items():
        # Support both shapes: array [in,out] and object {input,output}
        if isinstance(rates, dict) and "input" in rates and "output" in rates:
            rates = [rates["input"], rates["output"]]
        if (isinstance(rates, (list, tuple)) and len(rates) == 2 and all(_valid_rate(v) for v in rates)):
            costs[str(model)] = (float(rates[0]), float(rates[1]))
        else:
            logger.warning("Skipping malformed pricing entry for model %r in %s", model, target)

    default_cost = _BUILTIN_DEFAULT_COST
    dc = data.get("default_cost")
    # single-source uses "default_cost" array too — also accept {input,output}
    if isinstance(dc, dict) and "input" in dc and "output" in dc:
        dc = [dc["input"], dc["output"]]
    if dc is not None:
        if isinstance(dc, (list, tuple)) and len(dc) == 2 and all(_valid_rate(v) for v in dc):
            default_cost = (float(dc[0]), float(dc[1]))
        else:
            logger.warning("Skipping malformed 'default_cost' entry in %s", target)

    return costs, default_cost


MODEL_COSTS, _DEFAULT_COST = _load_model_costs()

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
