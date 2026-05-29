import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from builder.src.release_state import (
    connect_state_db,
    get_contour_state,
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
