"""Тесты инфраструктурных helper-ов builder-а.

Модуль фиксирует формат build version, который используется как часть имен
release artifacts и записей локальной SQLite state.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
BUILDER_ROOT = TOOLS_CI_ROOT / "builder"
BUILD_VERSION_BASE = "1.2.3"

sys.path.insert(0, str(BUILDER_ROOT))

from src.infra import get_new_build_version  # noqa: E402


class InfraTests(unittest.TestCase):
    """Проверяет небольшие infra-функции builder-а."""

    def test_new_build_version_includes_minutes(self):
        """Build version включает дату и минуты, но не секунды."""
        with patch("src.infra.get_required_env", return_value=BUILD_VERSION_BASE):
            with patch("src.infra.datetime") as datetime_mock:
                datetime_mock.now.return_value = datetime(2026, 5, 30, 14, 37, 12)

                self.assertEqual(get_new_build_version(), f"{BUILD_VERSION_BASE}.30052026_1437")


if __name__ == "__main__":
    unittest.main()
