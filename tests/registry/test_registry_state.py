"""Тесты compatibility registry boundary поверх текущего release state."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.registry import state as registry_state
from simple_deploy.release import state as release_state


class RegistryStateTests(unittest.TestCase):
    """Фиксирует новый registry import path без переноса SQLite implementation."""

    def test_registry_state_reexports_current_release_state_api(self):
        """Registry boundary сохраняет те же объекты, что и текущий release.state."""
        self.assertIs(registry_state.connect_state_db, release_state.connect_state_db)
        self.assertIs(registry_state.record_release, release_state.record_release)
        self.assertIs(registry_state.create_job, release_state.create_job)
        self.assertEqual(registry_state.CONTOURS, release_state.CONTOURS)


if __name__ == "__main__":
    unittest.main()
