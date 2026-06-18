"""Compatibility shim for the release state module.

The SQLite state implementation now lives in ``simple_deploy.registry.state``.
This module keeps historical ``src.release_state`` imports working for the
builder scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_CI_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_CI_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.registry.state import *  # noqa: F401,F403,E402
