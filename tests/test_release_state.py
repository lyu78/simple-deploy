"""Тесты SQLite state layer для release, deploy attempts, jobs и requests.

Модуль фиксирует контракт локальной базы как источника истины для контуров,
истории build/deploy и web jobs. Тестовые версии и коммиты вынесены в константы,
чтобы дальнейшее разбиение тестов по директориям не требовало поиска литералов.
"""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
STATE_DB_NAME = "state.sqlite3"
TEST_BUILD_VERSION = "1.2.4"
PREVIOUS_BUILD_VERSION = "1.2.3"
TEST_BACKEND_COMMIT = "abc123"
TEST_NEXT_BACKEND_COMMIT = "def456"
TEST_FRONTEND_COMMIT = "def456"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.release.state import (
    connect_state_db,
    create_external_request,
    create_job,
    get_external_request,
    get_contour_state,
    get_job,
    list_build_attempts,
    list_deployment_attempts,
    list_external_requests,
    list_jobs,
    list_releases,
    mark_job_finished,
    mark_job_started,
    record_build_attempt_finished,
    record_build_attempt_started,
    record_attempt,
    record_release,
    update_external_request_status,
    upsert_contour_state,
)


class ReleaseStateTests(unittest.TestCase):
    """Проверяет сохранение baseline, attempts, local jobs и external requests."""

    def test_upsert_contour_state_sets_last_success(self):
        """upsert_contour_state двигает baseline контура на успешный релиз."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "test", PREVIOUS_BUILD_VERSION, TEST_BACKEND_COMMIT)
                state = get_contour_state(connection, "test")

        self.assertIsNotNone(state)
        self.assertEqual(state.last_success_release, PREVIOUS_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)

    def test_build_attempts_schema_does_not_remove_existing_state(self):
        """Инициализация build_attempts не удаляет существующий deploy state."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "dev", PREVIOUS_BUILD_VERSION, TEST_BACKEND_COMMIT)
                record_attempt(connection, "dev", TEST_BUILD_VERSION, TEST_NEXT_BACKEND_COMMIT, "failed", "deploy error")

            with closing(connect_state_db(db_path)) as connection:
                state = get_contour_state(connection, "dev")
                attempts_count = connection.execute("select count(*) from deployment_attempts").fetchone()[0]
                build_attempts_count = connection.execute("select count(*) from build_attempts").fetchone()[0]

        self.assertEqual(state.last_success_release, PREVIOUS_BUILD_VERSION)
        self.assertEqual(attempts_count, 1)
        self.assertEqual(build_attempts_count, 0)

    def test_failed_build_attempt_is_recorded(self):
        """Failed build attempt сохраняет status, commits и error text."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                attempt_id = record_build_attempt_started(
                    connection,
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    TEST_FRONTEND_COMMIT,
                )
                record_build_attempt_finished(
                    connection,
                    attempt_id,
                    "failed",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    error="build error",
                )
                row = connection.execute(
                    "select build_version, status, backend_commit, frontend_commit, error from build_attempts"
                ).fetchone()

        self.assertEqual(row["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(row["frontend_commit"], TEST_FRONTEND_COMMIT)
        self.assertEqual(row["error"], "build error")

    def test_success_build_attempt_is_recorded(self):
        """Success build attempt сохраняет commits и пустой error."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                attempt_id = record_build_attempt_started(connection, TEST_BUILD_VERSION)
                record_build_attempt_finished(
                    connection,
                    attempt_id,
                    "success",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                )
                row = connection.execute(
                    "select status, backend_commit, frontend_commit, error from build_attempts"
                ).fetchone()

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(row["frontend_commit"], TEST_FRONTEND_COMMIT)
        self.assertEqual(row["error"], "")

    def test_failed_attempt_does_not_move_last_success(self):
        """Failed deploy attempt не двигает baseline контура."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "prod", PREVIOUS_BUILD_VERSION, TEST_BACKEND_COMMIT)
                record_attempt(connection, "prod", TEST_BUILD_VERSION, TEST_NEXT_BACKEND_COMMIT, "failed", "sql error")
                state = get_contour_state(connection, "prod")

        self.assertEqual(state.last_success_release, PREVIOUS_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)

    def test_recent_release_and_attempt_lists_are_returned(self):
        """list_* методы возвращают последние releases/build/deployment attempts."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                record_release(
                    connection,
                    TEST_BUILD_VERSION,
                    TEST_BACKEND_COMMIT,
                    TEST_FRONTEND_COMMIT,
                    {"backend": "backend.tar.gz"},
                )
                build_attempt_id = record_build_attempt_started(connection, TEST_BUILD_VERSION)
                record_build_attempt_finished(connection, build_attempt_id, "success")
                record_attempt(connection, "dev", TEST_BUILD_VERSION, TEST_BACKEND_COMMIT, "success")
                releases = list_releases(connection)
                build_attempts = list_build_attempts(connection)
                deployment_attempts = list_deployment_attempts(connection, contour="dev")

        self.assertEqual(releases[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(build_attempts[0]["status"], "success")
        self.assertEqual(deployment_attempts[0]["contour"], "dev")

    def test_local_job_lifecycle_is_recorded(self):
        """Local job проходит queued -> running -> terminal status с log path."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                job_id = create_job(
                    connection,
                    "DEPLOY",
                    contour="dev",
                    build_version=TEST_BUILD_VERSION,
                    payload={"latest": True},
                )
                mark_job_started(connection, job_id, log_path="logs/deploy.log")
                mark_job_finished(connection, job_id, "success")
                job = get_job(connection, job_id)
                jobs = list_jobs(connection)

        self.assertEqual(job.status, "success")
        self.assertEqual(job.kind, "deploy")
        self.assertEqual(job.contour, "dev")
        self.assertEqual(job.build_version, TEST_BUILD_VERSION)
        self.assertEqual(job.log_path, "logs/deploy.log")
        self.assertEqual(jobs[0].id, job_id)

    def test_local_job_contour_scope_is_explicit(self):
        """Unscoped job допустим для build, но deploy требует contour."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                build_job_id = create_job(connection, "BUILD")
                build_job = get_job(connection, build_job_id)

                with self.assertRaisesRegex(ValueError, "requires contour"):
                    create_job(connection, "DEPLOY")

        self.assertEqual(build_job.kind, "build")
        self.assertEqual(build_job.contour, "")

    def test_external_request_lifecycle_is_recorded(self):
        """External request для test/prod хранит payload, status и external id."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                request_id = create_external_request(
                    connection,
                    contour="test",
                    build_version=TEST_BUILD_VERSION,
                    request_type="DEPLOY",
                    payload={"package": "release.tar.gz"},
                )
                update_external_request_status(connection, request_id, "submitted", external_id="REQ-123")
                request = get_external_request(connection, request_id)
                requests = list_external_requests(connection, contour="test")

        self.assertEqual(request.status, "submitted")
        self.assertEqual(request.request_type, "deploy")
        self.assertEqual(request.external_id, "REQ-123")
        self.assertEqual(request.contour, "test")
        self.assertEqual(requests[0].id, request_id)

    def test_external_request_rejects_dev_contour(self):
        """External request запрещен для dev, где deploy выполняется напрямую."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                with self.assertRaisesRegex(ValueError, "test/prod"):
                    create_external_request(connection, "dev", TEST_BUILD_VERSION, "deploy")

    def test_job_and_external_request_reject_unknown_types(self):
        """State helpers отклоняют неизвестные kind и request_type до записи в SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with closing(connect_state_db(db_path)) as connection:
                with self.assertRaisesRegex(ValueError, "Unknown job kind"):
                    create_job(connection, "rollback")
                with self.assertRaisesRegex(ValueError, "Unknown external request type"):
                    create_external_request(connection, "test", TEST_BUILD_VERSION, "rollback")


if __name__ == "__main__":
    unittest.main()
