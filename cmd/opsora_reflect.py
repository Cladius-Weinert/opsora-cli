from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from opsora_tools import graphify_query
from opsora_memory import add_memory


def self_reflect(
    user_input: str,
    history: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]] = None,
    tool_outputs: List[str] = None,
) -> str:
    """
    Generate structured self-reflection before ACT/VERIFY.
    Uses graphify_query for context grounding and logs to memory.
    """
    # 1. Ground in project knowledge
    context = ""
    if user_input.strip():
        context = graphify_query(user_input.strip(), depth=1)
    
    # 2. Build reflection prompt
    reflection_prompt = f"""
User request: {user_input[:200]}

History (last 2 turns): {json.dumps(history[-2:], ensure_ascii=False)[:300]}

Tool calls planned: {json.dumps(tool_calls, ensure_ascii=False)[:200] if tool_calls else 'none'}

Context from workspace (graphify): {context[:500] if context else 'none'}

---
Reflect: Is this plan safe, complete, and aligned with Opsora’s goals? What could go wrong? Suggest one improvement.
"""
    
    # 3. Simulate LLM reflection (stub — will be replaced with real call later)
    # For now: deterministic fallback
    reflection = "Reflection: Plan looks valid. No critical risks detected. Proceeding."
    if "rm -rf" in user_input or "delete" in user_input.lower():
        reflection = "Reflection: HIGH-RISK command detected. Require explicit confirmation before execution."
    
    # 4. Log reflection
    log_entry = f"REFLECT | {time.time():.0f} | {user_input[:60]}… → {reflection[:80]}…"
    add_memory(log_entry, source="self_reflect")
    
    return reflection
