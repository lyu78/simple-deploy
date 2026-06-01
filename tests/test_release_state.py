import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools-ci"))

from builder.src.release_state import (
    connect_state_db,
    get_contour_state,
    record_build_attempt_finished,
    record_build_attempt_started,
    record_attempt,
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


if __name__ == "__main__":
    unittest.main()
