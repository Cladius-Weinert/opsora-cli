"""Opsora CLI package root module."""
# This file makes opsora_cmd a proper package that can be imported.
# Modules inside this package use flat top-level imports of their siblings
# (e.g. `from opsora_tui import ...`), so the package directory must be on
# sys.path whenever the package is imported.
import os as _os
import sys as _sys

_pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
if _pkg_dir not in _sys.path:
    _sys.path.insert(0, _pkg_dir)
