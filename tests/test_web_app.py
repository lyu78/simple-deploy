"""Тесты read-only FastAPI dashboard/API поверх локальной state DB.

Модуль проверяет, что web слой читает ту же SQLite-базу, что и CLI, и не имеет
собственной модели состояния.
"""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
STATE_DB_NAME = "state.sqlite3"
TEST_BUILD_VERSION = "1.2.4"
TEST_BACKEND_COMMIT = "abc123"
TEST_FRONTEND_COMMIT = "def456"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.release.state import connect_state_db, create_job, record_release, upsert_contour_state
from simple_deploy.web.app import app


class WebAppTests(unittest.TestCase):
    """Проверяет локальный dashboard/API без запуска внешнего сервера."""

    def test_dashboard_and_state_api_use_local_state_db(self):
        """Dashboard и /api/state читают releases, contour state и jobs из SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "dev", TEST_BUILD_VERSION, TEST_BACKEND_COMMIT)
                record_release(
                    connection,
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    TEST_FRONTEND_COMMIT,
                    {"backend": "backend.tar.gz"},
                )
                create_job(connection, "deploy", contour="dev", build_version=TEST_BUILD_VERSION)

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                client = TestClient(app)
                health_response = client.get("/api/health")
                state_response = client.get("/api/state")
                dashboard_response = client.get("/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(state_response.json()["contours"]["dev"]["last_success_release"], TEST_BUILD_VERSION)
        self.assertEqual(state_response.json()["releases"][0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(state_response.json()["jobs"][0]["kind"], "deploy")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("simple-deploy", dashboard_response.text)
        self.assertIn(TEST_BUILD_VERSION, dashboard_response.text)


if __name__ == "__main__":
    unittest.main()
