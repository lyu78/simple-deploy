"""Compatibility wrapper for the Windows pipeline CLI.

The implementation lives in ``simple_deploy.windows_pipeline``. This module
keeps the historical script path and import path working.
"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_CI_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_CI_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy import windows_pipeline as _implementation  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(_implementation.main())

sys.modules[__name__] = _implementation
