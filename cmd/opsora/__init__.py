"""Opsora core — memory, cache, context, and skills for terminal AI agents."""

from opsora.config import OpsoraPaths, get_paths
from opsora.context import ContextEngine, prepare_turn
from opsora.memory import add_memory, memory_stats, search_memory
from opsora.skills import SkillRegistry, list_skills, match_skills

__all__ = [
    "OpsoraPaths",
    "get_paths",
    "ContextEngine",
    "prepare_turn",
    "add_memory",
    "memory_stats",
    "search_memory",
    "SkillRegistry",
    "list_skills",
    "match_skills",
]

__version__ = "2.1.0"
