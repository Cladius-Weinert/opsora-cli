"""Opsora plugin system — discover, load, and manage custom tool plugins.

Plugins live in /root/.opsora/plugins/ as .py files implementing OpsoraPlugin.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

PLUGINS_DIR = Path("/root/.opsora/plugins")


class OpsoraPlugin(ABC):
    """Base class for all Opsora plugins."""

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    @abstractmethod
    def schema(self) -> dict:
        """Return OpenAI function-calling schema for this plugin."""

    @abstractmethod
    def execute(self, args: dict[str, Any]) -> str:
        """Run the plugin with given arguments and return output string."""


class PluginManager:
    """Discover, load, and manage Opsora tool plugins."""

    def __init__(self, plugins_dir: Path = PLUGINS_DIR) -> None:
        self._dir = plugins_dir
        self._plugins: dict[str, OpsoraPlugin] = {}

    @property
    def plugins(self) -> dict[str, OpsoraPlugin]:
        """Mapping of loaded plugin name -> plugin instance (read view of `_plugins`)."""
        return self._plugins

    def discover(self) -> list[str]:
        """Scan plugin directory and load .py files. Returns list of plugin names."""
        self._plugins.clear()
        if not self._dir.is_dir():
            self._dir.mkdir(parents=True, exist_ok=True)
            return []

        loaded: list[str] = []
        for fpath in sorted(self._dir.glob("*.py")):
            if fpath.name.startswith("_"):
                continue
            try:
                mod_name = f"opsora_plugin_{fpath.stem}"
                spec = importlib.util.spec_from_file_location(mod_name, fpath)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = mod
                spec.loader.exec_module(mod)

                # Find OpsoraPlugin subclass in module
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if (isinstance(obj, type)
                            and issubclass(obj, OpsoraPlugin)
                            and obj is not OpsoraPlugin):
                        instance = obj()
                        if instance.name:
                            self._plugins[instance.name] = instance
                            loaded.append(instance.name)
                        break  # one plugin per file
            except Exception as exc:
                loaded.append(f"!{fpath.stem}: {exc}")

        return loaded

    def get_schemas(self) -> list[dict]:
        """Return OpenAI function schemas for all loaded plugins."""
        schemas = []
        for plugin in self._plugins.values():
            try:
                schemas.append(plugin.schema())
            except Exception:
                pass
        return schemas

    def execute(self, name: str, args: dict[str, Any]) -> str:
        """Execute a plugin by name."""
        plugin = self._plugins.get(name)
        if not plugin:
            avail = ", ".join(self._plugins.keys()) if self._plugins else "tidak ada"
            return f"❌ Plugin `{name}` tidak ditemukan. Plugin aktif: {avail}"
        try:
            return plugin.execute(args or {})
        except Exception as exc:
            return f"❌ Error di plugin `{name}`: {exc}"

    def reload(self) -> list[str]:
        """Hot-reload all plugins from disk."""
        return self.discover()

    def status(self) -> dict:
        """Return plugin system status."""
        return {
            "plugins_dir": str(self._dir),
            "dir_exists": self._dir.is_dir(),
            "loaded_count": len(self._plugins),
            "plugins": {
                name: {
                    "description": p.description,
                    "version": p.version,
                }
                for name, p in self._plugins.items()
            },
        }


# Module-level convenience instance
_manager = PluginManager()


def discover_plugins() -> list[str]:
    return _manager.discover()


def get_plugin_schemas() -> list[dict]:
    return _manager.get_schemas()


def execute_plugin(name: str, args: dict[str, Any]) -> str:
    return _manager.execute(name, args)


def reload_plugins() -> list[str]:
    return _manager.reload()


def plugin_status() -> dict:
    return _manager.status()
