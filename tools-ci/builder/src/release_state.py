"""Compatibility shim для release state module.

SQLite state implementation теперь находится в
``simple_deploy.registry.state``. Этот модуль сохраняет исторические imports
``src.release_state`` для builder scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_CI_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_CI_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.registry.state import *  # noqa: F401,F403,E402
