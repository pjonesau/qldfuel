"""Registers this repo as the ``qldfuel`` package for tests.

The integration's files live at the repo root (not under
custom_components/), and use relative imports (e.g. `from .const import
...` in origin_manager.py) that only resolve inside a real package. This
registers the root __init__.py as package "qldfuel" in sys.modules before
any test imports it, regardless of what the checkout directory is named.
"""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parent

if "qldfuel" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "qldfuel", _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["qldfuel"] = _module
    _spec.loader.exec_module(_module)
