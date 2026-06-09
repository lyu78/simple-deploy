import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools-ci"))

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
    def test_upsert_contour_state_sets_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "test", "1.2.3", "abc123")
                state = get_contour_state(connection, "test")

        self.assertIsNotNone(state)
        self.assertEqual(state.last_success_release, "1.2.3")
        self.assertEqual(state.last_success_backend_commit, "abc123")

    def test_build_attempts_schema_does_not_remove_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "dev", "1.2.3", "abc123")
                record_attempt(connection, "dev", "1.2.4", "def456", "failed", "deploy error")

            with closing(connect_state_db(db_path)) as connection:
                state = get_contour_state(connection, "dev")
                attempts_count = connection.execute("select count(*) from deployment_attempts").fetchone()[0]
                build_attempts_count = connection.execute("select count(*) from build_attempts").fetchone()[0]

        self.assertEqual(state.last_success_release, "1.2.3")
        self.assertEqual(attempts_count, 1)
        self.assertEqual(build_attempts_count, 0)

    def test_failed_build_attempt_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                attempt_id = record_build_attempt_started(connection, "1.2.4", "abc123", "def456")
                record_build_attempt_finished(
                    connection,
                    attempt_id,
                    "failed",
                    backend_commit="abc123",
                    frontend_commit="def456",
                    error="build error",
                )
                row = connection.execute(
                    "select build_version, status, backend_commit, frontend_commit, error from build_attempts"
                ).fetchone()

        self.assertEqual(row["build_version"], "1.2.4")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["backend_commit"], "abc123")
        self.assertEqual(row["frontend_commit"], "def456")
        self.assertEqual(row["error"], "build error")

    def test_success_build_attempt_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                attempt_id = record_build_attempt_started(connection, "1.2.4")
                record_build_attempt_finished(
                    connection,
                    attempt_id,
                    "success",
                    backend_commit="abc123",
                    frontend_commit="def456",
                )
                row = connection.execute(
                    "select status, backend_commit, frontend_commit, error from build_attempts"
                ).fetchone()

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["backend_commit"], "abc123")
        self.assertEqual(row["frontend_commit"], "def456")
        self.assertEqual(row["error"], "")

    def test_failed_attempt_does_not_move_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "prod", "1.2.3", "abc123")
                record_attempt(connection, "prod", "1.2.4", "def456", "failed", "sql error")
                state = get_contour_state(connection, "prod")

        self.assertEqual(state.last_success_release, "1.2.3")
        self.assertEqual(state.last_success_backend_commit, "abc123")

    def test_recent_release_and_attempt_lists_are_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                record_release(connection, "1.2.4", "abc123", "def456", {"backend": "backend.tar.gz"})
                build_attempt_id = record_build_attempt_started(connection, "1.2.4")
                record_build_attempt_finished(connection, build_attempt_id, "success")
                record_attempt(connection, "dev", "1.2.4", "abc123", "success")
                releases = list_releases(connection)
                build_attempts = list_build_attempts(connection)
                deployment_attempts = list_deployment_attempts(connection, contour="dev")

        self.assertEqual(releases[0]["build_version"], "1.2.4")
        self.assertEqual(build_attempts[0]["status"], "success")
        self.assertEqual(deployment_attempts[0]["contour"], "dev")

    def test_local_job_lifecycle_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                job_id = create_job(
                    connection,
                    "deploy",
                    contour="dev",
                    build_version="1.2.4",
                    payload={"latest": True},
                )
                mark_job_started(connection, job_id, log_path="logs/deploy.log")
                mark_job_finished(connection, job_id, "success")
                job = get_job(connection, job_id)
                jobs = list_jobs(connection)

        self.assertEqual(job.status, "success")
        self.assertEqual(job.contour, "dev")
        self.assertEqual(job.build_version, "1.2.4")
        self.assertEqual(job.log_path, "logs/deploy.log")
        self.assertEqual(jobs[0].id, job_id)

    def test_external_request_lifecycle_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                request_id = create_external_request(
                    connection,
                    contour="test",
                    build_version="1.2.4",
                    request_type="deploy",
                    payload={"package": "release.tar.gz"},
                )
                update_external_request_status(connection, request_id, "submitted", external_id="REQ-123")
                request = get_external_request(connection, request_id)
                requests = list_external_requests(connection, contour="test")

        self.assertEqual(request.status, "submitted")
        self.assertEqual(request.external_id, "REQ-123")
        self.assertEqual(request.contour, "test")
        self.assertEqual(requests[0].id, request_id)

    def test_external_request_rejects_dev_contour(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                with self.assertRaisesRegex(ValueError, "test/prod"):
                    create_external_request(connection, "dev", "1.2.4", "deploy")


if __name__ == "__main__":
    unittest.main()
