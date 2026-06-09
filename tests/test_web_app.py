import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools-ci"))

from simple_deploy.release.state import connect_state_db, create_job, record_release, upsert_contour_state
from simple_deploy.web.app import app


class WebAppTests(unittest.TestCase):
    def test_dashboard_and_state_api_use_local_state_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "dev", "1.2.4", "abc123")
                record_release(connection, "1.2.4", "abc123", "def456", {"backend": "backend.tar.gz"})
                create_job(connection, "deploy", contour="dev", build_version="1.2.4")

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                client = TestClient(app)
                health_response = client.get("/api/health")
                state_response = client.get("/api/state")
                dashboard_response = client.get("/")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json(), {"status": "ok"})
        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(state_response.json()["contours"]["dev"]["last_success_release"], "1.2.4")
        self.assertEqual(state_response.json()["releases"][0]["build_version"], "1.2.4")
        self.assertEqual(state_response.json()["jobs"][0]["kind"], "deploy")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("simple-deploy", dashboard_response.text)
        self.assertIn("1.2.4", dashboard_response.text)


if __name__ == "__main__":
    unittest.main()
