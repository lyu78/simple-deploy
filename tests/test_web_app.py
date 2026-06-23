"""Тесты FastAPI dashboard/API поверх локальной базы состояния.

Модуль проверяет, что web слой читает ту же SQLite-базу, что и CLI, и создает
локальные jobs через общий API без собственной модели состояния.
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
REACT_INDEX_HTML = (
    '<title>simple-deploy</title><div id="root"></div>'
    '<script src="/assets/app.js"></script>'
)

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.release.state import (
    connect_state_db,
    create_external_request,
    create_job,
    mark_job_finished,
    mark_job_started,
    record_attempt,
    record_build_attempt_finished,
    record_build_attempt_started,
    record_release,
    update_external_request_status,
    upsert_contour_state,
)
from simple_deploy.registry.commands import record_worker_heartbeat
import simple_deploy.web.app as web_app
from simple_deploy.web.app import app


def write_react_index_fixture(directory: str) -> Path:
    """Создает минимальную React shell fixture для HTML routes."""
    web_index = Path(directory) / "index.html"
    web_index.write_text(REACT_INDEX_HTML, encoding="utf-8")
    return web_index


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
                with tempfile.TemporaryDirectory() as web_tmp:
                    web_index = write_react_index_fixture(web_tmp)
                    with patch.object(web_app, "WEB_UI_INDEX", web_index):
                        record_worker_heartbeat(
                            status="idle",
                            message="test worker heartbeat",
                        )
                        client = TestClient(app)
                        health_response = client.get("/api/health")
                        worker_response = client.get("/api/worker")
                        state_response = client.get("/api/state")
                        releases_response = client.get("/api/releases")
                        jobs_response = client.get("/api/jobs")
                        created_job_response = client.post(
                            "/api/jobs",
                            json={
                                "kind": "build",
                                "payload": {
                                    "env_file": str(TOOLS_CI_ROOT / ".env"),
                                    "secrets_file": str(
                                        TOOLS_CI_ROOT / "local.secrets.env"
                                    ),
                                    "timeout": 77,
                                    "skip_data_sql_artifacts": True,
                                },
                            },
                        )
                        created_deploy_job_response = client.post(
                            "/api/jobs",
                            json={
                                "kind": "deploy",
                                "payload": {
                                    "contour": "dev",
                                    "build_version": "",
                                    "latest": True,
                                    "include_set_default_sql": False,
                                    "app_only": False,
                                },
                            },
                        )
                        requests_response = client.get("/api/requests")
                        dashboard_response = client.get("/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(worker_response.status_code, 200)
        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(releases_response.status_code, 200)
        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(created_job_response.status_code, 201)
        self.assertEqual(created_deploy_job_response.status_code, 201)
        self.assertEqual(requests_response.status_code, 200)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        worker_json = worker_response.json()
        self.assertEqual(worker_json["status"], "idle")
        self.assertEqual(worker_json["heartbeat"]["status"], "idle")
        self.assertEqual(
            worker_json["heartbeat"]["message"], "test worker heartbeat"
        )
        self.assertGreaterEqual(worker_json["queued_jobs"], 1)
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
        created_job = created_job_response.json()
        self.assertEqual(created_job["kind"], "build")
        self.assertEqual(created_job["status"], "queued")
        self.assertIn("skip_data_sql_artifacts", created_job["payload_json"])
        created_deploy_job = created_deploy_job_response.json()
        self.assertEqual(created_deploy_job["kind"], "deploy")
        self.assertEqual(created_deploy_job["contour"], "dev")
        self.assertIn("include_set_default_sql", created_deploy_job["payload_json"])
        self.assertEqual(requests_response.json(), state_json["external_requests"])
        self.assertIn("simple-deploy", dashboard_response.text)
        self.assertIn('id="root"', dashboard_response.text)
        self.assertIn("/assets/", dashboard_response.text)

    def test_job_websocket_streams_log_file_for_terminal_job(self):
        """WebSocket читает статус из SQLite и строки из job log file."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            log_path = Path(tmp) / "job.log"
            log_path.write_text(
                "RUN LOG job.log\nWORKER finished job\n",
                encoding="utf-8",
            )
            with closing(connect_state_db(db_path)) as connection:
                job_id = create_job(
                    connection,
                    "build",
                    build_version=TEST_BUILD_VERSION,
                )
                mark_job_started(connection, job_id, log_path=str(log_path))
                mark_job_finished(connection, job_id, "success")

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                with tempfile.TemporaryDirectory() as web_tmp:
                    web_index = write_react_index_fixture(web_tmp)
                    with patch.object(web_app, "WEB_UI_INDEX", web_index):
                        client = TestClient(app)
                        page_response = client.get(f"/jobs/{job_id}")
                        missing_page_response = client.get("/jobs/999999")
                        with client.websocket_connect(
                            f"/ws/jobs/{job_id}?poll_interval=0.1"
                        ) as websocket:
                            snapshot = websocket.receive_json()
                            log_chunk = websocket.receive_json()
                            done = websocket.receive_json()

        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(snapshot["job"]["id"], job_id)
        self.assertEqual(snapshot["job"]["status"], "success")
        self.assertEqual(log_chunk["type"], "log")
        self.assertIn("WORKER finished job", log_chunk["text"])
        self.assertEqual(done, {"type": "done", "status": "success"})
        self.assertEqual(page_response.status_code, 200)
        self.assertIn('id="root"', page_response.text)
        self.assertIn("/assets/", page_response.text)
        self.assertEqual(missing_page_response.status_code, 404)

    def test_job_api_updates_lifecycle_status_via_patch(self):
        """PATCH /api/jobs/{id} выполняет REST transition состояния job."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                queued_id = create_job(
                    connection,
                    "build",
                    build_version=TEST_BUILD_VERSION,
                )
                running_id = create_job(
                    connection,
                    "build",
                    build_version=FAILED_BUILD_VERSION,
                )
                mark_job_started(connection, running_id)
                failed_id = create_job(
                    connection,
                    "deploy",
                    contour="dev",
                    build_version=TEST_BUILD_VERSION,
                )
                mark_job_started(
                    connection, failed_id, log_path="logs/failed.log"
                )
                mark_job_finished(connection, failed_id, "failed", "boom")

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                client = TestClient(app)
                get_response = client.get(f"/api/jobs/{queued_id}")
                cancel_response = client.patch(
                    f"/api/jobs/{queued_id}",
                    json={"status": "cancelled"},
                )
                running_cancel_response = client.patch(
                    f"/api/jobs/{running_id}",
                    json={"status": "cancelled"},
                )
                requeue_response = client.patch(
                    f"/api/jobs/{failed_id}",
                    json={"status": "queued"},
                )
                invalid_target_response = client.patch(
                    f"/api/jobs/{failed_id}",
                    json={"status": "running"},
                )
                missing_get_response = client.get("/api/jobs/999999")
                missing_patch_response = client.patch(
                    "/api/jobs/999999",
                    json={"status": "cancelled"},
                )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["id"], queued_id)
        self.assertEqual(cancel_response.status_code, 200)
        cancelled = cancel_response.json()
        self.assertEqual(cancelled["id"], queued_id)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertNotEqual(cancelled["finished_at"], "")
        self.assertEqual(running_cancel_response.status_code, 409)
        self.assertEqual(requeue_response.status_code, 200)
        requeued = requeue_response.json()
        self.assertEqual(requeued["id"], failed_id)
        self.assertEqual(requeued["status"], "queued")
        self.assertEqual(requeued["log_path"], "")
        self.assertEqual(requeued["error"], "")
        self.assertEqual(requeued["started_at"], "")
        self.assertEqual(requeued["finished_at"], "")
        self.assertEqual(invalid_target_response.status_code, 409)
        self.assertEqual(missing_get_response.status_code, 404)
        self.assertEqual(missing_patch_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
