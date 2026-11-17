"""Pytest configuration for CasambiBt tests."""

import os
import sys

# The library lives only in the HA integration (custom_components/casambi_bt/CasambiBt)
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "casambi_bt")
)
