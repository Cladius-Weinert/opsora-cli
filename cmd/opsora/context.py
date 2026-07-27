"""Context compression, prefetch, and dynamic system prompt assembly."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from opsora.cache import get_cached, set_cached
from opsora.config import get_paths
from opsora.memory import search_memory
from opsora.skills import match_skills

DEFAULT_MAX_CONTEXT_TOKENS = int(
    __import__("os").environ.get("OPSORA_MAX_CONTEXT_TOKENS", "24000")
)
KEEP_RECENT_MESSAGES = int(__import__("os").environ.get("OPSORA_KEEP_RECENT_MESSAGES", "8"))


@dataclass
class ContextBundle:
    user_message: str
    memory_hits: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, str]] = field(default_factory=list)
    workspace_hint: str = ""
    compressed_count: int = 0

    def to_prompt_block(self) -> str:
        sections: list[str] = []
        if self.memory_hits:
            lines = [f"- [{hit['source']}] {hit['text']}" for hit in self.memory_hits[:5]]
            sections.append("## Relevant memory\n" + "\n".join(lines))
        if self.skills:
            lines = [f"- **{skill['name']}**: {skill['description']}" for skill in self.skills]
            sections.append("## Active skills\n" + "\n".join(lines))
            for skill in self.skills[:2]:
                excerpt = skill.get("excerpt", "")
                if excerpt:
                    sections.append(f"### Skill: {skill['name']}\n{excerpt}")
        if self.workspace_hint:
            sections.append(f"## Workspace\n{self.workspace_hint}")
        if self.compressed_count:
            sections.append(
                f"## Session note\nEarlier conversation compressed ({self.compressed_count} messages)."
            )
        return "\n\n".join(sections)


class ContextEngine:
    def __init__(self, base_system_prompt: str) -> None:
        self.base_system_prompt = base_system_prompt

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total_chars = 0
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                total_chars += len(content)
            elif content is not None:
                total_chars += len(json.dumps(content, ensure_ascii=False))
        return max(1, total_chars // 4)

    def prefetch(self, user_message: str) -> ContextBundle:
        cached = get_cached("context_prefetch", {"q": user_message})
        if cached:
            data = json.loads(cached)
            return ContextBundle(**data)

        bundle = ContextBundle(user_message=user_message)
        bundle.memory_hits = search_memory(user_message, limit=5)
        matched = match_skills(user_message, limit=3)
        bundle.skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "excerpt": _skill_excerpt(skill.instructions),
            }
            for skill in matched
        ]
        bundle.workspace_hint = _workspace_hint()
        set_cached(
            "context_prefetch",
            {"q": user_message},
            json.dumps(bundle.__dict__, ensure_ascii=False),
            ttl_seconds=900,
        )
        return bundle

    def compress_history(self, history: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        if self.estimate_tokens(history) <= DEFAULT_MAX_CONTEXT_TOKENS:
            return history, 0

        if len(history) <= KEEP_RECENT_MESSAGES:
            return history, 0

        older = history[:-KEEP_RECENT_MESSAGES]
        recent = history[-KEEP_RECENT_MESSAGES:]
        summary = _summarize_messages(older)
        compressed = [{"role": "system", "content": summary}]
        return compressed + recent, len(older)

    def build_system_prompt(self, bundle: ContextBundle | None = None) -> str:
        if not bundle:
            return self.base_system_prompt
        appendix = bundle.to_prompt_block()
        if not appendix:
            return self.base_system_prompt
        return f"{self.base_system_prompt}\n\n---\n\n# Session context (auto-loaded)\n{appendix}"

    def prepare_turn(
        self,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]], ContextBundle]:
        bundle = self.prefetch(user_message)
        compressed_history, compressed_count = self.compress_history(history)
        bundle.compressed_count = compressed_count
        system_prompt = self.build_system_prompt(bundle)
        return system_prompt, compressed_history, bundle


def prepare_turn(
    user_message: str,
    history: list[dict[str, Any]],
    base_system_prompt: str,
) -> tuple[str, list[dict[str, Any]], ContextBundle]:
    return ContextEngine(base_system_prompt).prepare_turn(user_message, history)


def _skill_excerpt(text: str, max_chars: int = 1200) -> str:
    cleaned = _FRONTMATTER_RE.sub("", text, count=1).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."


def _summarize_messages(messages: list[dict[str, Any]]) -> str:
    user_points: list[str] = []
    assistant_points: list[str] = []
    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content") or "").strip()
        if not content or content.startswith("[Previous conversation"):
            continue
        if role == "user":
            user_points.append(content[:180])
        elif role == "assistant":
            assistant_points.append(content[:180])

    lines = ["[Compressed session summary]"]
    if user_points:
        lines.append("User topics: " + " | ".join(user_points[-4:]))
    if assistant_points:
        lines.append("Assistant actions: " + " | ".join(assistant_points[-4:]))
    return "\n".join(lines)


def _workspace_hint() -> str:
    paths = get_paths()
    root = paths.workspace_root
    try:
        children = sorted(p.name for p in root.iterdir() if p.is_dir())[:12]
    except OSError:
        children = []
    return f"Root: {root}\nTop-level dirs: {', '.join(children) if children else '(none)'}"


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
