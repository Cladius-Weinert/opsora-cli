"""Opsora Intent Router — Smart model routing based on prompt analysis."""
from __future__ import annotations
import re
import os
from typing import Optional

# Import provider models dynamically
try:
    from opsora_v2 import PROVIDER_MODELS, get_provider_order, is_provider_available
except ImportError:
    PROVIDER_MODELS = {}
    def get_provider_order():
        return ["alibaba", "nvidia", "bedrock", "openai", "tokenhub", "local"]
    def is_provider_available(provider: str) -> bool:
        return True

# Intent patterns — regex-based classification (Tier 1 & 2)
_PATTERNS: dict[str, list[re.Pattern]] = {
    "code": [re.compile(p, re.I) for p in [
        r"\b(write|create|generate|buat|bikin)\s+(a\s+|an\s+)?(\w+\s+){0,2}(function|class|script|code|program|kode|fungsi|dockerfile|docker-compose|makefile|config|yaml|yml|query|schema|regex|endpoint|api)\b",
        r"\b(debug|fix|perbaiki|benerin|betulkan)\b", r"\b(refactor|optimize|clean\s*up|rapikan)\b",
        r"\b(python|javascript|typescript|rust|golang|java|c\+\+|bash)\b",
        r"\b(import |def |class |function |const |let |var )\b",
        r"\b(api|endpoint|route|handler|middleware)\b", r"\b(bug|error|traceback|exception)\b",
        r"\b(git|commit|push|pull|merge|branch|rebase)\b",
        r"\b(docker|dockerfile|container)\b", r"\b(test|unittest|pytest|jest)\b",
    ]],
    "quick": [re.compile(p, re.I) for p in [
        r"^(yes|no|ok|oke|ya|tidak|lanjut|skip|batal|stop|cancel)\b",
        r"\b(translate|terjemah|artikan)\b",
        r"\b(what is|apa itu|definisi|arti)\b.{0,30}\?$",
        r"\b(how to|gimana|gimana cara|cara)\b.{0,40}\?$",
        r"\b(convert|konversi|ubah)\b.{0,20}\b(to|ke)\b",
        r"\b(tldr|summary|ringkasan|intisari)\b",
    ]],
    "analysis": [re.compile(p, re.I) for p in [
        r"\b(analyze|analisis|analisa|evaluate|evaluasi)\b",
        r"\b(compare|bandingkan|vs|versus)\b", r"\b(review|tinjau|audit)\b",
        r"\b(explain|jelasin|jelaskan|uraikan)\b",
        r"\b(research|riset|investigate|selidiki)\b",
        r"\b(architecture|arsitektur|design|desain)\b",
        r"\b(security|keamanan|vulnerability)\b",
        r"\b(performance|performa|optimization|optimasi)\b",
    ]],
    "cloud": [re.compile(p, re.I) for p in [
        r"\b(aws|azure|gcp|google\s*cloud|alibaba\s*cloud)\b",
        r"\b(ec2|s3|lambda|rds|ecs|eks|fargate)\b", r"\b(deploy|deployment)\b",
        r"\b(kubernetes|k8s|helm|istio)\b",
        r"\b(fly\.io|vercel|render|heroku|netlify)\b",
        r"\b(vps|server|instance|vm|virtual\s*machine)\b",
        r"\b(cdn|load\s*balancer|dns|ssl|tls)\b",
        r"\b(orchestrat\w*)\b",
    ]],
    "creative": [re.compile(p, re.I) for p in [
        r"\b(write|tulis|buat|bikin|create|generate)\s+(a\s+|an\s+)?(\w+\s+){0,2}(story|cerita|poem|puisi|blog|article|artikel|novel|essay|haiku|post)\b",
        r"\b(creative|kreatif|imagine|bayangkan)\b",
        r"\b(marketing|copywriting|tagline|slogan|headline)\b",
        r"\b(brand|branding|nama)\b.{0,30}\b(suggest\w*|saran|ide)\b",
    ]],
    "vision": [re.compile(p, re.I) for p in [
        r"\b(image|img|screenshot|picture|photo|foto|gambar)\b",
        r"\b(diagram|chart|graph|grafik)\b",
        r"\b(ocr|read|extract)\s+(text|teks)\b",
        r"\b(visual|ui|ux|interface|tampilan)\b",
    ]],
}

# Definitional questions ("what is X?", "apa itu X?") are quick lookups even
# when their subject is a technical noun (Python, API, ...).
_DEFINITIONAL_QUESTION = re.compile(r"\b(what is|apa itu|definisi|arti)\b.{0,30}\?$", re.I)

# Tie-break priority: when categories score equally, intent-verb categories
# (analysis/creative) beat artifact-noun categories (code/cloud). Vision is
# unambiguous and ranks first.
_PRIORITY = ["vision", "quick", "analysis", "creative", "code", "cloud"]

# Scoring weights — higher = stronger signal per match
_WEIGHTS: dict[str, float] = {
    "code": 2.0, "quick": 1.5, "analysis": 2.0, "cloud": 2.5, "creative": 2.0, "vision": 4.5,
}

# Model capability map — single source of truth for capability-aware
# selection and fallback. Values are substrings matched against model names,
# derived from the verified model tiers (POWER/FAST/REASONING/CODING_MODELS
# in opsora_v2.py) and the NVIDIA/Alibaba model catalogs.
_MODEL_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "vision": ("vision", "multimodal", "neva", "omni"),
    "coding": ("coding", "coder", "code", "granite", "starcoder"),
    "reasoning": ("reasoning", "ultra", "super", "max"),
    "fast": ("flash", "mini", "nano", "8b", "turbo"),
}

# Aliases so callers may pass intent names and capability names
# interchangeably (e.g. "code" vs "coding", "quick" vs "fast").
_CAPABILITY_ALIASES: dict[str, str] = {
    "vision": "vision", "multimodal": "vision",
    "code": "coding", "coding": "coding",
    "reasoning": "reasoning", "reason": "reasoning", "analysis": "reasoning",
    "fast": "fast", "speed": "fast", "quick": "fast",
}

# Intents that impose a HARD capability requirement on routing/fallback.
# Only binary capabilities belong here: a model either accepts image input or
# it cannot serve a vision task at all. Coding/reasoning/speed are matters of
# degree handled by scoring — a general model can still serve those tasks,
# so hard-filtering them would wrongly exclude capable models.
_INTENT_REQUIRED_CAPABILITY: dict[str, str] = {
    "vision": "vision",
}


class NoCapableModelError(RuntimeError):
    """A required capability was demanded but no available model provides it.

    Raised instead of silently routing to an incapable model (e.g. a
    text-only model for a vision task) so callers can surface the gap to the
    user rather than produce a wrong-modality answer.
    """

# Default model costs per 1M tokens (input, output) in USD
_DEFAULT_COSTS: dict[str, tuple[float, float]] = {
    "qwen-plus": (0.40, 1.20),
    "qwen-turbo": (0.05, 0.20),
    "qwen-max": (2.00, 6.00),
    "qwen3-coder-flash": (0.15, 0.60),
    "qwen3-coder-plus": (0.40, 1.20),
    "qwen3.7-max": (1.50, 4.50),
    "qwen3.7-plus": (0.40, 1.20),
    "qwen3.7-flash": (0.10, 0.30),
    "meta/llama-3.1-8b-instruct": (0.00, 0.00),
    "meta/llama-3.1-70b-instruct": (0.00, 0.00),
    "nvidia/nemotron-3-super-120b-a12b": (0.00, 0.00),
    "nvidia/nemotron-3-ultra-550b-a55b": (0.00, 0.00),
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": (0.00, 0.00),
    "nvidia/nemotron-3-nano-30b-a3b": (0.00, 0.00),
    "nvidia/nvidia-nemotron-nano-9b-v2": (0.00, 0.00),
    "nvidia/nemotron-mini-4b-instruct": (0.00, 0.00),
    "mistralai/mistral-nemotron": (0.00, 0.00),
    "mistralai/mistral-medium-3.5-128b": (0.00, 0.00),
    "stepfun-ai/step-3.7-flash": (0.00, 0.00),
}

class IntentRouter:
    """Classify user prompts into intent categories for smart routing."""

    def __init__(self):
        self._pattern_cache: dict[str, list[re.Pattern]] = {}

    def classify(self, prompt: str) -> str:
        """Classify a prompt into: code, quick, analysis, cloud, creative, vision, general.
        Uses regex/keyword matching (Tier 1) and pattern scoring (Tier 2)."""
        if not prompt or not prompt.strip():
            return "general"
        p = prompt.strip()
        # Tier 1: Very short prompts are almost always "quick"
        if len(p) < 10 and not any(kw in p.lower() for kw in ("fix", "debug", "code", "buat", "bikin", "vision", "image")):
            return "quick"
        # Tier 1.5: Definitional questions are quick lookups, even when the
        # subject is a technical noun ("what is Python?", "apa itu API?").
        if _DEFINITIONAL_QUESTION.search(p):
            return "quick"
        # Tier 2: Score-based classification
        scores = {cat: 0.0 for cat in _PATTERNS}
        for category, patterns in _PATTERNS.items():
            w = _WEIGHTS.get(category, 1.0)
            for pat in patterns:
                if pat.search(p):
                    scores[category] += w
        best_score = max(scores.values())
        if best_score < 1.5:
            return "general"
        # Tie-break by priority so intent-verb categories beat noun mentions.
        tied = [cat for cat, sc in scores.items() if sc == best_score]
        if len(tied) == 1:
            return tied[0]
        for cat in _PRIORITY:
            if cat in tied:
                return cat
        return tied[0]

def _get_available_models() -> dict[str, list[str]]:
    """Get available models grouped by provider."""
    available = {}
    for provider in get_provider_order():
        if is_provider_available(provider):
            models = [m.strip() for m in PROVIDER_MODELS.get(provider, "").split(",") if m.strip()]
            if models:
                available[provider] = models
    return available

def resolve_capability(capability: Optional[str]) -> Optional[str]:
    """Normalize a capability name to its canonical key (or None if empty).

    Known aliases map onto _MODEL_CAPABILITIES keys; unknown strings are
    lowercased and kept as-is (they match as literal substrings, preserving
    the legacy behavior for arbitrary capability names).
    """
    if not capability or not capability.strip():
        return None
    key = capability.strip().lower()
    return _CAPABILITY_ALIASES.get(key, key)


def model_has_capability(model: str, capability: str) -> bool:
    """True if `model` provides `capability`.

    Known capabilities match via _MODEL_CAPABILITIES keywords against the
    model name; unknown capability strings fall back to a literal substring
    match (backward compatible with the legacy filter).
    """
    cap = resolve_capability(capability)
    if not cap:
        return True  # no constraint — everything passes
    model_lower = model.lower()
    keywords = _MODEL_CAPABILITIES.get(cap)
    if keywords:
        return any(kw in model_lower for kw in keywords)
    return cap in model_lower


def resolve_required_capability(
    required_capability: Optional[str], intent: Optional[str]
) -> Optional[str]:
    """Resolve the hard capability requirement for a routing decision.

    An explicit `required_capability` wins; otherwise a hard requirement is
    derived from the intent (_INTENT_REQUIRED_CAPABILITY — currently only
    vision, the sole binary capability).
    """
    if required_capability:
        return resolve_capability(required_capability)
    return _INTENT_REQUIRED_CAPABILITY.get(intent or "")


def _score_model(intent: str, model: str, prefer_cost: bool, prefer_speed: bool) -> float:
    """Score a single model for an intent. Higher = better fit."""
    score = 0.0
    model_lower = model.lower()

    # Intent matching (soft preference — keywords from the capability map)
    if intent == "vision" and any(kw in model_lower for kw in _MODEL_CAPABILITIES["vision"]):
        score += 10
    elif intent == "code" and any(kw in model_lower for kw in _MODEL_CAPABILITIES["coding"]):
        score += 10
    elif intent == "analysis" and any(kw in model_lower for kw in _MODEL_CAPABILITIES["reasoning"]):
        score += 8
    elif intent == "quick" and any(kw in model_lower for kw in _MODEL_CAPABILITIES["fast"]):
        score += 8

    # Cost preference
    if prefer_cost:
        cost = _DEFAULT_COSTS.get(model, (1.0, 2.0))
        score += 5.0 / (cost[0] + cost[1] + 0.1)

    # Speed preference
    if prefer_speed and any(kw in model_lower for kw in _MODEL_CAPABILITIES["fast"]):
        score += 5

    return score


def _select_best_model(
    intent: str,
    available: dict[str, list[str]],
    prefer_cost: bool = False,
    prefer_speed: bool = False,
    required_capability: Optional[str] = None,
) -> tuple[str, str]:
    """Select the best model based on intent, availability, and preferences.

    Capability-aware: the required capability (explicit, or derived from the
    intent for binary capabilities like vision) hard-filters the candidates.
    When no capable model exists this raises NoCapableModelError instead of
    silently routing to an incapable model.
    """
    capability = resolve_required_capability(required_capability, intent)

    # Build candidate list with scores
    candidates = []
    for provider, models in available.items():
        for model in models:
            # Hard capability filter — incapable models never become fallbacks
            if capability and not model_has_capability(model, capability):
                continue
            score = _score_model(intent, model, prefer_cost, prefer_speed)
            candidates.append((score, provider, model))

    if not candidates:
        # A required capability was requested but no available model provides
        # it — fail loudly instead of silently picking a wrong-modality model.
        if capability:
            considered = [m for models in available.values() for m in models]
            raise NoCapableModelError(
                f"No available model provides required capability "
                f"'{capability}' (intent='{intent}'). "
                f"Considered {len(considered)} model(s): "
                f"{', '.join(considered[:8]) or 'none'}"
            )
        # No capability constraint — fall back to first available
        for provider, models in available.items():
            if models:
                return provider, models[0]
        return "alibaba", "qwen3-coder-flash"

    # Sort by score descending
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]

def route(
    prompt: str,
    available_providers: Optional[dict[str, list[str]]] = None,
    prefer_cost: bool = False,
    prefer_speed: bool = False,
    required_capability: Optional[str] = None,
) -> tuple[str, str]:
    """Route a prompt to the best (provider, model) based on intent + availability.
    Returns (provider, model) tuple.

    Capability-aware: an explicit `required_capability` — or, for binary
    capabilities, the intent itself (vision) — hard-filters candidates. If
    no capable model exists, raises NoCapableModelError rather than silently
    picking an incapable model. Behavior is unchanged when no capability
    constraint applies.
    """
    intent = IntentRouter().classify(prompt)

    if not available_providers:
        available_providers = _get_available_models()

    if not available_providers:
        capability = resolve_required_capability(required_capability, intent)
        if capability:
            raise NoCapableModelError(
                f"No providers available to satisfy required capability "
                f"'{capability}' (intent='{intent}')"
            )
        # Ultimate fallback
        return "alibaba", "qwen3-coder-flash"

    return _select_best_model(
        intent,
        available_providers,
        prefer_cost=prefer_cost,
        prefer_speed=prefer_speed,
        required_capability=required_capability,
    )


def fallback_candidates(
    prompt: str,
    available_providers: Optional[dict[str, list[str]]] = None,
    exclude: Optional[list[tuple[str, str]]] = None,
    required_capability: Optional[str] = None,
    prefer_cost: bool = False,
    prefer_speed: bool = False,
) -> list[tuple[str, str]]:
    """Capability-aware fallback candidates after a primary (provider, model) fails.

    Classifies the prompt's intent, resolves the hard capability requirement
    (explicit `required_capability` wins; a vision intent requires a vision
    model), drops incapable models and already-failed (provider, model)
    pairs, and returns the remaining candidates best-scored first.

    Raises NoCapableModelError when the requirement cannot be satisfied —
    callers must surface that gap instead of picking a wrong-modality model.
    """
    intent = IntentRouter().classify(prompt)
    if not available_providers:
        available_providers = _get_available_models()
    capability = resolve_required_capability(required_capability, intent)
    excluded = {(p, m) for p, m in (exclude or [])}

    scored = []
    for provider, models in available_providers.items():
        for model in models:
            if (provider, model) in excluded:
                continue
            if capability and not model_has_capability(model, capability):
                continue
            score = _score_model(intent, model, prefer_cost, prefer_speed)
            scored.append((score, provider, model))

    if not scored:
        if capability:
            raise NoCapableModelError(
                f"No fallback model provides required capability "
                f"'{capability}' (intent='{intent}') after excluding "
                f"failed candidates"
            )
        raise NoCapableModelError(
            "No fallback candidates available (all providers/models excluded)"
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(provider, model) for _, provider, model in scored]
