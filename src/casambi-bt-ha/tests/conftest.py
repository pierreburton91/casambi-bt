"""Pytest configuration for casambi-bt-ha tests.

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

import pytest

# Add src/ to sys.path so `CasambiBt` is importable, same as tests/conftest.py.
_SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_SRC_DIR))

_LOGIC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "casambi_bt", "_logic.py"
)


@pytest.fixture(scope="session")
def logic():
    """Load _logic.py directly, bypassing the casambi_bt package's __init__.py."""
    spec = importlib.util.spec_from_file_location("casambi_bt_logic", _LOGIC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' ClassVar detection looks the module up via sys.modules to
    # resolve string annotations (from __future__ import annotations) - it
    # must be registered there before exec_module() runs the class bodies.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
