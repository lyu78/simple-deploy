"""Тесты write/use-case команд registry."""

import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
STATE_DB_NAME = "state.sqlite3"
TEST_BUILD_VERSION = "1.2.4"
PREVIOUS_BUILD_VERSION = "1.2.3"
TEST_BACKEND_COMMIT = "abc123"
PREVIOUS_BACKEND_COMMIT = "prev123"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.registry.commands import (
    record_deployment_applied,
    record_deployment_failed,
    set_contour_baseline,
)
from simple_deploy.registry.state import (
    connect_state_db,
    get_contour_state,
    list_deployment_attempts,
)


class RegistryCommandTests(unittest.TestCase):
    """Проверяет write-команды поверх registry state без process/CLI слоя."""

    def test_set_contour_baseline_moves_baseline_without_attempt(self):
        """Baseline command не создает deployment attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                result = set_contour_baseline(
                    "TEST",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                )

            with closing(connect_state_db(db_path)) as connection:
                state = get_contour_state(connection, "test")
                attempts = list_deployment_attempts(connection, contour="test")

        self.assertEqual(result.contour, "test")
        self.assertEqual(result.build_version, TEST_BUILD_VERSION)
        self.assertEqual(result.backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(state.last_success_release, TEST_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts, [])

    def test_record_deployment_applied_moves_baseline_and_records_attempt(self):
        """Applied command двигает baseline и пишет success deployment attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                result = record_deployment_applied(
                    "dev",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                )

            with closing(connect_state_db(db_path)) as connection:
                state = get_contour_state(connection, "dev")
                attempts = list_deployment_attempts(connection, contour="dev")

        self.assertEqual(result.contour, "dev")
        self.assertEqual(state.last_success_release, TEST_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(attempts[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["status"], "success")
        self.assertEqual(attempts[0]["error"], "")

    def test_record_deployment_failed_records_attempt_without_moving_baseline(self):
        """Failed command пишет failed attempt и не меняет baseline."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                set_contour_baseline("prod", PREVIOUS_BUILD_VERSION, PREVIOUS_BACKEND_COMMIT)
                result = record_deployment_failed(
                    "prod",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    "operator rejected",
                )

            with closing(connect_state_db(db_path)) as connection:
                state = get_contour_state(connection, "prod")
                attempts = list_deployment_attempts(connection, contour="prod")

        self.assertEqual(result.contour, "prod")
        self.assertEqual(state.last_success_release, PREVIOUS_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, PREVIOUS_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(attempts[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertEqual(attempts[0]["error"], "operator rejected")


if __name__ == "__main__":
    unittest.main()
