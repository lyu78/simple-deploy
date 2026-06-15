"""Тесты FastAPI dashboard/API только для чтения поверх локальной базы состояния.

Модуль проверяет, что web слой читает ту же SQLite-базу, что и CLI, и не имеет
собственной модели состояния.
"""

import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
STATE_DB_NAME = "state.sqlite3"
TEST_BUILD_VERSION = "1.2.4"
FAILED_BUILD_VERSION = "1.2.5"
TEST_BACKEND_COMMIT = "abc123"
TEST_FRONTEND_COMMIT = "def456"
TEST_EXTERNAL_ID = "REQ-123"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.release.state import (
    connect_state_db,
    create_external_request,
    create_job,
    record_attempt,
    record_build_attempt_finished,
    record_build_attempt_started,
    record_release,
    update_external_request_status,
    upsert_contour_state,
)
from simple_deploy.web.app import app


class WebAppTests(unittest.TestCase):
    """Проверяет локальный dashboard/API без запуска внешнего сервера."""

    def test_dashboard_and_state_api_use_local_state_db(self):
        """Dashboard и API читают состояние через стабильный JSON-контракт."""
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
                build_attempt_id = record_build_attempt_started(
                    connection,
                    TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                record_build_attempt_finished(
                    connection,
                    build_attempt_id,
                    "success",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                failed_build_attempt_id = record_build_attempt_started(
                    connection,
                    FAILED_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                record_build_attempt_finished(
                    connection,
                    failed_build_attempt_id,
                    "failed",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    error="build error",
                )
                record_attempt(
                    connection,
                    "dev",
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    "success",
                )
                create_job(connection, "deploy", contour="dev", build_version=TEST_BUILD_VERSION)
                request_id = create_external_request(
                    connection,
                    "test",
                    TEST_BUILD_VERSION,
                    "deploy",
                    payload={"package": "release.tar.gz"},
                )
                update_external_request_status(
                    connection,
                    request_id,
                    "submitted",
                    external_id=TEST_EXTERNAL_ID,
                )

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                client = TestClient(app)
                health_response = client.get("/api/health")
                state_response = client.get("/api/state")
                releases_response = client.get("/api/releases")
                jobs_response = client.get("/api/jobs")
                requests_response = client.get("/api/requests")
                dashboard_response = client.get("/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(releases_response.status_code, 200)
        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(requests_response.status_code, 200)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        state_json = state_response.json()
        self.assertEqual(state_json["contours"]["dev"]["last_success_release"], TEST_BUILD_VERSION)
        self.assertEqual(
            state_json["contours"]["dev"]["last_success_release_ref"]["build_version"],
            TEST_BUILD_VERSION,
        )
        self.assertEqual(
            state_json["contours"]["dev"]["last_success_release_ref"]["backend_commit"],
            TEST_BACKEND_COMMIT,
        )
        self.assertEqual(
            state_json["contours"]["dev"]["last_success_release_ref"]["build_status"],
            "success",
        )
        self.assertEqual(
            {attempt["build_version"]: attempt["status"] for attempt in state_json["build_attempts"]},
            {TEST_BUILD_VERSION: "success", FAILED_BUILD_VERSION: "failed"},
        )
        self.assertEqual(state_json["deployment_attempts"][0]["contour"], "dev")
        self.assertEqual(state_json["jobs"][0]["kind"], "deploy")
        self.assertEqual(state_json["external_requests"][0]["external_id"], TEST_EXTERNAL_ID)
        releases_by_version = {release["build_version"]: release for release in state_json["releases"]}
        successful_release = releases_by_version[TEST_BUILD_VERSION]
        failed_release = releases_by_version[FAILED_BUILD_VERSION]
        self.assertEqual(successful_release["build_status"], "success")
        self.assertIsNotNone(successful_release["bundle"])
        self.assertEqual(successful_release["bundle"]["artifacts_json"], '{"backend": "backend.tar.gz"}')
        self.assertEqual(successful_release["build_attempts"][0]["status"], "success")
        self.assertEqual(successful_release["deployment_attempts"][0]["contour"], "dev")
        self.assertEqual(successful_release["external_requests"][0]["external_id"], TEST_EXTERNAL_ID)
        self.assertEqual(failed_release["build_status"], "failed")
        self.assertIsNone(failed_release["bundle"])
        self.assertEqual(failed_release["build_attempts"][0]["error"], "build error")
        self.assertEqual(
            set(successful_release),
            {
                "build_version",
                "build_status",
                "backend_commit",
                "frontend_commit",
                "bundle",
                "build_attempts",
                "deployment_attempts",
                "external_requests",
            },
        )
        self.assertEqual(releases_response.json(), state_json["releases"])
        self.assertEqual(jobs_response.json(), state_json["jobs"])
        self.assertEqual(requests_response.json(), state_json["external_requests"])
        self.assertIn("simple-deploy", dashboard_response.text)
        self.assertIn(TEST_BUILD_VERSION, dashboard_response.text)


if __name__ == "__main__":
    unittest.main()
