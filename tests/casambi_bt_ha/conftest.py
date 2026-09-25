"""Pytest configuration for custom_components/casambi_bt tests.

These tests are deliberately dependency-free: they exercise only the
framework-agnostic helpers in custom_components/casambi_bt/_logic.py, never the
platform modules themselves (which import `homeassistant`, not installed here).
`_logic.py` is loaded directly from its file path rather than via
`from casambi_bt import _logic`, since importing the `casambi_bt` package would
run its `__init__.py`, which does import `homeassistant`.
"""

import importlib.util
import os
import sys
import types

import pytest

_INTEGRATION_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "custom_components", "casambi_bt"
)
_LOGIC_PATH = os.path.join(_INTEGRATION_DIR, "_logic.py")
_LOGIC_MODULE_NAME = "custom_components.casambi_bt._logic"

# _logic.py imports the vendored CasambiBt via a relative import
# (`from .CasambiBt import ...`), which only resolves if its parent package is
# registered in sys.modules. So the parent chain is stubbed here (with
# __path__ pointing at the real directories) instead of importing the real
# custom_components.casambi_bt package, which would run its __init__.py and
# pull in `homeassistant`. This runs at collection time (not lazily in the
# `logic` fixture below) so test modules can import CasambiBt types via
# `custom_components.casambi_bt.CasambiBt` too - the same class objects
# _logic.py uses, rather than a second, distinct copy via `src/`.
for _name, _path in (
    ("custom_components", os.path.join(_INTEGRATION_DIR, "..")),
    ("custom_components.casambi_bt", _INTEGRATION_DIR),
):
    if _name not in sys.modules:
        _stub = types.ModuleType(_name)
        _stub.__path__ = [os.path.abspath(_path)]
        sys.modules[_name] = _stub


@pytest.fixture(scope="session")
def logic():
    """Load _logic.py directly, bypassing the casambi_bt package's __init__.py."""
    spec = importlib.util.spec_from_file_location(_LOGIC_MODULE_NAME, _LOGIC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' ClassVar detection looks the module up via sys.modules to
    # resolve string annotations (from __future__ import annotations) - it
    # must be registered there before exec_module() runs the class bodies.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
