"""Тесты write/use-case команд registry."""

from concurrent.futures import ThreadPoolExecutor
import os
import sys
import tempfile
import threading
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
    cancel_local_job,
    claim_next_local_job,
    create_local_job,
    create_release_external_request,
    finish_build_attempt,
    finish_local_job,
    mark_local_job_started,
    record_deployment_applied,
    record_deployment_failed,
    record_release_bundle,
    record_worker_heartbeat,
    requeue_local_job,
    set_contour_baseline,
    set_local_job_log_path,
    start_build_attempt,
    update_release_external_request_status,
)
from simple_deploy.registry.state import (
    connect_state_db,
    get_contour_state,
    list_build_attempts,
    list_deployment_attempts,
    list_external_requests,
    list_jobs,
    list_releases,
    get_worker_heartbeat,
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

    def test_build_attempt_commands_record_lifecycle(self):
        """Build attempt commands пишут started и terminal status."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                started = start_build_attempt(
                    TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit="front-start",
                )
                finished = finish_build_attempt(
                    started.attempt_id,
                    "SUCCESS",
                    build_version=TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit="front-final",
                )

            with closing(connect_state_db(db_path)) as connection:
                attempts = list_build_attempts(connection)

        self.assertEqual(started.build_version, TEST_BUILD_VERSION)
        self.assertEqual(started.status, "started")
        self.assertEqual(finished.build_version, TEST_BUILD_VERSION)
        self.assertEqual(finished.status, "success")
        self.assertEqual(attempts[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(attempts[0]["status"], "success")
        self.assertEqual(attempts[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["frontend_commit"], "front-final")
        self.assertEqual(attempts[0]["error"], "")

    def test_record_release_bundle_command_records_release_row(self):
        """Release bundle command пишет release metadata в registry state."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                result = record_release_bundle(
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    "front-final",
                    {"backend": "backend.tar.gz"},
                )

            with closing(connect_state_db(db_path)) as connection:
                releases = list_releases(connection)

        self.assertEqual(result.build_version, TEST_BUILD_VERSION)
        self.assertEqual(result.backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(result.frontend_commit, "front-final")
        self.assertEqual(releases[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(releases[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(releases[0]["frontend_commit"], "front-final")
        self.assertEqual(releases[0]["artifacts_json"], '{"backend": "backend.tar.gz"}')

    def test_local_job_commands_record_lifecycle(self):
        """Local job commands создают queued job и двигают его lifecycle."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_local_job(
                    "DEPLOY",
                    contour="DEV",
                    build_version=TEST_BUILD_VERSION,
                    payload={"latest": True},
                )
                started = mark_local_job_started(created.job.id, log_path="logs/deploy.log")
                finished = finish_local_job(created.job.id, "SUCCESS")

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(created.job.status, "queued")
        self.assertEqual(started.job.status, "running")
        self.assertEqual(started.job.log_path, "logs/deploy.log")
        self.assertEqual(finished.job.status, "success")
        self.assertEqual(finished.job.kind, "deploy")
        self.assertEqual(finished.job.contour, "dev")
        self.assertEqual(finished.job.build_version, TEST_BUILD_VERSION)
        self.assertEqual(jobs[0].id, created.job.id)

    def test_claim_next_local_job_is_atomic_across_workers(self):
        """Два worker-а не могут забрать одну queued job одновременно."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_local_job("BUILD", build_version=TEST_BUILD_VERSION)
                barrier = threading.Barrier(3)

                def claim_job() -> int | None:
                    barrier.wait()
                    result = claim_next_local_job()
                    return result.job.id if result is not None else None

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(claim_job) for _ in range(2)]
                    barrier.wait()
                    claimed_ids = [future.result() for future in futures]

                updated = set_local_job_log_path(
                    created.job.id, "logs/claimed.log"
                )

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(claimed_ids.count(created.job.id), 1)
        self.assertEqual(claimed_ids.count(None), 1)
        self.assertEqual(updated.job.status, "running")
        self.assertEqual(updated.job.log_path, "logs/claimed.log")
        self.assertEqual(jobs[0].status, "running")

    def test_create_contour_scoped_job_requires_contour(self):
        """Registry command отклоняет contour-scoped job без контура."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                with self.assertRaisesRegex(ValueError, "requires contour"):
                    create_local_job("DEPLOY", build_version=TEST_BUILD_VERSION)

    def test_worker_heartbeat_command_records_status(self):
        """Worker heartbeat пишется в SQLite как отдельный operator status."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_local_job(
                    "BUILD", build_version=TEST_BUILD_VERSION
                )
                result = record_worker_heartbeat(
                    status="RUNNING",
                    current_job_id=created.job.id,
                    message="claimed test job",
                )

            with closing(connect_state_db(db_path)) as connection:
                heartbeat = get_worker_heartbeat(connection)

        self.assertEqual(result.heartbeat.worker_id, "local")
        self.assertEqual(result.heartbeat.status, "running")
        self.assertEqual(result.heartbeat.current_job_id, created.job.id)
        self.assertEqual(result.heartbeat.message, "claimed test job")
        self.assertIsNotNone(heartbeat)
        self.assertEqual(heartbeat.status, "running")

    def test_cancel_local_job_only_allows_queued_jobs(self):
        """Cancel transition переводит только queued job в cancelled."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                queued = create_local_job(
                    "BUILD",
                    build_version=TEST_BUILD_VERSION,
                    payload={"timeout": 77},
                )
                cancelled = cancel_local_job(
                    queued.job.id, error="operator cancelled"
                )

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(cancelled.job.id, queued.job.id)
        self.assertEqual(cancelled.job.status, "cancelled")
        self.assertEqual(cancelled.job.error, "operator cancelled")
        self.assertEqual(cancelled.job.started_at, "")
        self.assertNotEqual(cancelled.job.finished_at, "")
        self.assertEqual(jobs[0].status, "cancelled")

    def test_cancel_local_job_rejects_non_queued_jobs(self):
        """Cancel transition не трогает running job."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                running = create_local_job(
                    "BUILD", build_version=TEST_BUILD_VERSION
                )
                mark_local_job_started(running.job.id)

                with self.assertRaisesRegex(ValueError, "Cannot cancel"):
                    cancel_local_job(running.job.id)

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(jobs[0].id, running.job.id)
        self.assertEqual(jobs[0].status, "running")

    def test_requeue_local_job_moves_failed_or_cancelled_job_to_queued(self):
        """Requeue возвращает тот же job в queued и чистит runtime-поля."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                failed = create_local_job(
                    "DEPLOY",
                    contour="DEV",
                    build_version=TEST_BUILD_VERSION,
                    payload={"latest": True},
                    log_path="logs/old.log",
                )
                finish_local_job(failed.job.id, "FAILED", error="deploy failed")
                requeued_failed = requeue_local_job(failed.job.id)

                queued = create_local_job(
                    "BUILD",
                    build_version=PREVIOUS_BUILD_VERSION,
                    payload={"timeout": 10},
                )
                cancelled = cancel_local_job(queued.job.id)
                requeued_cancelled = requeue_local_job(cancelled.job.id)

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(requeued_failed.job.id, failed.job.id)
        self.assertEqual(requeued_failed.job.status, "queued")
        self.assertEqual(requeued_failed.job.kind, "deploy")
        self.assertEqual(requeued_failed.job.contour, "dev")
        self.assertEqual(requeued_failed.job.build_version, TEST_BUILD_VERSION)
        self.assertEqual(requeued_failed.job.payload_json, '{"latest": true}')
        self.assertEqual(requeued_failed.job.log_path, "")
        self.assertEqual(requeued_failed.job.error, "")
        self.assertEqual(requeued_failed.job.started_at, "")
        self.assertEqual(requeued_failed.job.finished_at, "")
        self.assertEqual(requeued_cancelled.job.id, cancelled.job.id)
        self.assertEqual(requeued_cancelled.job.status, "queued")
        self.assertEqual(requeued_cancelled.job.payload_json, '{"timeout": 10}')
        self.assertEqual(jobs[0].id, requeued_cancelled.job.id)

    def test_requeue_local_job_rejects_non_terminal_jobs(self):
        """Requeue transition разрешен только после failed/cancelled."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                queued = create_local_job(
                    "BUILD", build_version=TEST_BUILD_VERSION
                )

                with self.assertRaisesRegex(ValueError, "Cannot requeue"):
                    requeue_local_job(queued.job.id)

            with closing(connect_state_db(db_path)) as connection:
                jobs = list_jobs(connection)

        self.assertEqual(jobs[0].id, queued.job.id)
        self.assertEqual(jobs[0].status, "queued")

    def test_external_request_commands_record_lifecycle(self):
        """External request commands создают request и обновляют его статус."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_release_external_request(
                    "TEST",
                    TEST_BUILD_VERSION,
                    "DEPLOY",
                    payload={"package": "release.tar.gz"},
                )
                updated = update_release_external_request_status(
                    created.request.id,
                    "SUBMITTED",
                    external_id="REQ-123",
                )

            with closing(connect_state_db(db_path)) as connection:
                requests = list_external_requests(connection, contour="test")

        self.assertEqual(created.request.status, "draft")
        self.assertEqual(created.request.request_type, "deploy")
        self.assertEqual(updated.request.status, "submitted")
        self.assertEqual(updated.request.external_id, "REQ-123")
        self.assertEqual(updated.request.contour, "test")
        self.assertEqual(updated.request.build_version, TEST_BUILD_VERSION)
        self.assertEqual(requests[0].id, created.request.id)

    def test_external_request_rejects_dev_contour(self):
        """External request command не принимает DEV-контур."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                with self.assertRaisesRegex(ValueError, "test/prod"):
                    create_release_external_request(
                        "DEV",
                        TEST_BUILD_VERSION,
                        "DEPLOY",
                    )


if __name__ == "__main__":
    unittest.main()
