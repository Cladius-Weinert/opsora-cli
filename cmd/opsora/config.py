"""Central path and environment configuration for Opsora."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _expand_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    return Path(value).expanduser().resolve()


def _csv_paths(value: str | None) -> list[Path]:
    if not value:
        return []
    return [_expand_path(part.strip(), Path(part.strip())) for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class OpsoraPaths:
    workspace_root: Path
    opsora_dir: Path
    memory_db: Path
    cache_db: Path
    skills_dir: Path
    session_dir: Path
    graphify_root: Path
    extra_skill_dirs: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> OpsoraPaths:
        home = Path.home()
        workspace = _expand_path(
            os.environ.get("OPSORA_WORKSPACE_ROOT"),
            Path.cwd(),
        )
        opsora_dir = _expand_path(
            os.environ.get("OPSORA_DIR"),
            home / ".opsora",
        )
        return cls(
            workspace_root=workspace,
            opsora_dir=opsora_dir,
            memory_db=_expand_path(
                os.environ.get("OPSORA_MEMORY_DB"),
                opsora_dir / "memory.db",
            ),
            cache_db=_expand_path(
                os.environ.get("OPSORA_CACHE_DB"),
                opsora_dir / "cache.db",
            ),
            skills_dir=_expand_path(
                os.environ.get("OPSORA_SKILLS_DIR"),
                opsora_dir / "skills",
            ),
            session_dir=_expand_path(
                os.environ.get("OPSORA_SESSION_DIR"),
                opsora_dir / "sessions",
            ),
            graphify_root=_expand_path(
                os.environ.get("GRAPHIFY_ROOT"),
                home / "graphify-out",
            ),
            extra_skill_dirs=tuple(_csv_paths(os.environ.get("OPSORA_SKILLS_DIRS"))),
        )

    def ensure_dirs(self) -> None:
        for path in (
            self.opsora_dir,
            self.skills_dir,
            self.session_dir,
            self.memory_db.parent,
            self.cache_db.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


_default_paths: OpsoraPaths | None = None


def get_paths() -> OpsoraPaths:
    global _default_paths
    if _default_paths is None:
        _default_paths = OpsoraPaths.from_env()
        _default_paths.ensure_dirs()
    return _default_paths
