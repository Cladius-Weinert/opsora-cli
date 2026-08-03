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

# Model capability tags
_MODEL_CAPABILITIES: dict[str, list[str]] = {
    "vision": ["vision", "multimodal"],
    "code": ["coding", "code"],
    "reasoning": ["reasoning", "analysis"],
    "fast": ["fast", "speed"],
}

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

def _select_best_model(
    intent: str,
    available: dict[str, list[str]],
    prefer_cost: bool = False,
    prefer_speed: bool = False,
    required_capability: Optional[str] = None,
) -> tuple[str, str]:
    """Select the best model based on intent, availability, and preferences."""
    
    # Capability-aware model selection
    capability_keywords = {
        "vision": ["vision", "multimodal"],
        "code": ["coding", "coder", "code"],
        "reasoning": ["reasoning", "ultra", "super", "max"],
        "fast": ["flash", "mini", "nano", "8b", "turbo"],
    }
    
    # Build candidate list with scores
    candidates = []
    for provider, models in available.items():
        for model in models:
            score = 0.0
            model_lower = model.lower()
            
            # Intent matching
            if intent == "vision" and any(kw in model_lower for kw in capability_keywords["vision"]):
                score += 10
            elif intent == "code" and any(kw in model_lower for kw in capability_keywords["code"]):
                score += 10
            elif intent == "analysis" and any(kw in model_lower for kw in capability_keywords["reasoning"]):
                score += 8
            elif intent == "quick" and any(kw in model_lower for kw in capability_keywords["fast"]):
                score += 8
            
            # Cost preference
            if prefer_cost:
                cost = _DEFAULT_COSTS.get(model, (1.0, 2.0))
                score += 5.0 / (cost[0] + cost[1] + 0.1)
            
            # Speed preference
            if prefer_speed and any(kw in model_lower for kw in capability_keywords["fast"]):
                score += 5
            
            # Required capability
            if required_capability and required_capability not in model_lower:
                continue
            
            candidates.append((score, provider, model))
    
    if not candidates:
        # A required capability was requested but no available model provides
        # it — do not silently route to an incapable model; use the ultimate
        # fallback instead.
        if required_capability:
            return "alibaba", "qwen3-coder-flash"
        # Fallback to first available
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
    Returns (provider, model) tuple."""
    intent = IntentRouter().classify(prompt)
    
    if not available_providers:
        available_providers = _get_available_models()
    
    if not available_providers:
        # Ultimate fallback
        return "alibaba", "qwen3-coder-flash"
    
    return _select_best_model(
        intent,
        available_providers,
        prefer_cost=prefer_cost,
        prefer_speed=prefer_speed,
        required_capability=required_capability,
    )
