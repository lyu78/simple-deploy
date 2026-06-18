"""Тесты read/query boundary поверх registry state."""

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
FAILED_BUILD_VERSION = "1.2.5"
TEST_BACKEND_COMMIT = "abc123"
TEST_FRONTEND_COMMIT = "def456"
TEST_EXTERNAL_ID = "REQ-123"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.registry import queries as registry_queries
from simple_deploy.registry import state as registry_state
from simple_deploy.web import app as web_app


class RegistryQueryTests(unittest.TestCase):
    """Проверяет сборку read models вне web/API слоя."""

    def test_registry_queries_build_state_snapshot_read_model(self):
        """Registry query слой читает SQLite state и собирает dashboard-проекцию."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(registry_state.connect_state_db(db_path)) as connection:
                registry_state.upsert_contour_state(
                    connection,
                    "dev",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                )
                registry_state.record_release(
                    connection,
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    TEST_FRONTEND_COMMIT,
                    {"backend": "backend.tar.gz"},
                )
                build_attempt_id = registry_state.record_build_attempt_started(
                    connection,
                    TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                registry_state.record_build_attempt_finished(
                    connection,
                    build_attempt_id,
                    "success",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                failed_build_attempt_id = registry_state.record_build_attempt_started(
                    connection,
                    FAILED_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                registry_state.record_build_attempt_finished(
                    connection,
                    failed_build_attempt_id,
                    "failed",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    error="build error",
                )
                registry_state.record_attempt(
                    connection,
                    "dev",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    "success",
                )
                registry_state.create_job(
                    connection,
                    "deploy",
                    contour="dev",
                    build_version=TEST_BUILD_VERSION,
                )
                request_id = registry_state.create_external_request(
                    connection,
                    "test",
                    TEST_BUILD_VERSION,
                    "deploy",
                    payload={"package": "release.tar.gz"},
                )
                registry_state.update_external_request_status(
                    connection,
                    request_id,
                    "submitted",
                    external_id=TEST_EXTERNAL_ID,
                )

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                snapshot = registry_queries.state_snapshot_read_model(limit=50)
                releases = registry_queries.release_read_models_from_state(limit=50)
                jobs = registry_queries.job_read_models_from_state(limit=50)
                requests = registry_queries.external_request_read_models_from_state(limit=50)

        self.assertEqual(snapshot.contours["dev"].last_success_release, TEST_BUILD_VERSION)
        self.assertEqual(
            snapshot.contours["dev"].last_success_release_ref.backend_commit,
            TEST_BACKEND_COMMIT,
        )
        self.assertEqual(
            {attempt.build_version: attempt.status for attempt in snapshot.build_attempts},
            {TEST_BUILD_VERSION: "success", FAILED_BUILD_VERSION: "failed"},
        )
        self.assertEqual(snapshot.deployment_attempts[0].contour, "dev")
        self.assertEqual(snapshot.jobs[0].kind, "deploy")
        self.assertEqual(snapshot.external_requests[0].external_id, TEST_EXTERNAL_ID)
        releases_by_version = {release.build_version: release for release in releases}
        self.assertEqual(releases_by_version[TEST_BUILD_VERSION].build_status, "success")
        self.assertEqual(releases_by_version[FAILED_BUILD_VERSION].build_status, "failed")
        self.assertEqual(jobs[0].build_version, TEST_BUILD_VERSION)
        self.assertEqual(requests[0].external_id, TEST_EXTERNAL_ID)

    def test_web_app_keeps_snapshot_helper_as_adapter(self):
        """Web helper остается совместимым adapter-ом над registry query слоем."""
        with patch.object(web_app, "_state_snapshot_read_model") as query:
            query.return_value = "snapshot"

            self.assertEqual(web_app.state_snapshot_model(limit=7), "snapshot")

        query.assert_called_once_with(limit=7)
        self.assertFalse(hasattr(web_app, "release_read_models"))


if __name__ == "__main__":
    unittest.main()
