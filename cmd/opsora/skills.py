"""Skill discovery and intent-based skill matching."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from opsora.config import get_paths

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    source: str

    @property
    def instructions(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self.refresh()

    def refresh(self) -> int:
        self._skills.clear()
        for skill in _discover_skills():
            self._skills[skill.name] = skill
        return len(self._skills)

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda item: item.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def match(self, query: str, limit: int = 3) -> list[Skill]:
        cleaned = (query or "").strip().lower()
        if not cleaned:
            return self.all()[:limit]

        tokens = {token for token in re.split(r"[^\w.-]+", cleaned) if len(token) > 2}
        scored: list[tuple[int, Skill]] = []
        for skill in self._skills.values():
            haystack = f"{skill.name} {skill.description} {skill.path.parent.name}".lower()
            score = sum(2 if token in skill.name.lower() else 1 for token in tokens if token in haystack)
            if score:
                scored.append((score, skill))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [skill for _, skill in scored[:limit]]


_registry_instance: SkillRegistry | None = None


def _get_registry() -> SkillRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SkillRegistry()
    return _registry_instance


def list_skills() -> list[Skill]:
    return _get_registry().all()


def match_skills(query: str, limit: int = 3) -> list[Skill]:
    return _get_registry().match(query, limit=limit)


def _parse_frontmatter(text: str) -> tuple[str, str]:
    name = ""
    description = ""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return name, description
    block = match.group(1)
    name_match = _NAME_RE.search(block)
    desc_match = _DESC_RE.search(block)
    if name_match:
        name = name_match.group(1).strip().strip('"').strip("'")
    if desc_match:
        description = desc_match.group(1).strip().strip('"').strip("'")
    return name, description


def _discover_skills() -> list[Skill]:
    paths = get_paths()
    paths.ensure_dirs()
    discovered: dict[str, Skill] = {}

    search_roots: list[tuple[Path, str]] = [
        (paths.skills_dir, "opsora"),
        (Path(__file__).resolve().parent / "bundled_skills", "bundled"),
    ]

    for extra in paths.extra_skill_dirs:
        search_roots.append((extra, "custom"))

    env_home = Path.home()
    cursor_glob = env_home / ".cursor" / "plugins" / "cache"
    if cursor_glob.exists():
        for skill_md in cursor_glob.glob("**/skills/*/SKILL.md"):
            search_roots.append((skill_md.parent, "cursor-plugin"))

    codex_skills = env_home / ".codex" / "skills"
    if codex_skills.exists():
        for skill_md in codex_skills.glob("**/SKILL.md"):
            search_roots.append((skill_md.parent, "codex"))

    for root, source in search_roots:
        if not root.exists():
            continue
        skill_files = [root / "SKILL.md"] if root.is_dir() and (root / "SKILL.md").exists() else list(root.glob("**/SKILL.md"))
        for skill_file in skill_files:
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            name, description = _parse_frontmatter(text)
            if not name:
                name = skill_file.parent.name
            if not description:
                description = f"Skill from {skill_file.parent.name}"
            skill = Skill(name=name, description=description, path=skill_file, source=source)
            discovered[skill.name] = skill

    return list(discovered.values())
