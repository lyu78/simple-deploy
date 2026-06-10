"""Тесты интеграции builder create_release с локальной SQLite state.

Модуль фиксирует запись build attempts и release manifest без реальной сборки
backend/frontend. Все версии, commits и имена временной БД вынесены в константы,
чтобы тестовые данные не были размазаны по сценариям.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
BUILDER_ROOT = TOOLS_CI_ROOT / "builder"
STATE_DB_NAME = "state.sqlite3"
TEST_BUILD_VERSION = "1.2.3"
TEST_BRANCH = "feature/test"
TEST_BACKEND_COMMIT = "backend-sha"
TEST_FRONTEND_COMMIT = "frontend-sha"

sys.path.insert(0, str(BUILDER_ROOT))

os.environ.setdefault("FRONTEND_DEV_SERVER_NAME", "dev")
os.environ.setdefault("FRONTEND_TEST_SERVER_NAME", "test")
os.environ.setdefault("FRONTEND_PROD_SERVER_NAME", "prod")

import create_release


class CreateReleaseStateTests(unittest.TestCase):
    """Проверяет state side effects вокруг builder entrypoint create_release."""

    def test_main_records_failed_build_attempt(self):
        """RuntimeError во время build_backend записывает failed build attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            env = {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}

            with patch.dict(os.environ, env, clear=True):
                with patch("create_release.get_new_build_version", return_value=TEST_BUILD_VERSION):
                    with patch("create_release.get_new_branch_name", return_value=TEST_BRANCH):
                        with patch("create_release.build_backend", side_effect=RuntimeError("backend failed")):
                            with self.assertRaisesRegex(RuntimeError, "backend failed"):
                                create_release.main()

            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "select build_version, status, error from build_attempts"
                ).fetchone()

        self.assertEqual(row, (TEST_BUILD_VERSION, "failed", "backend failed"))

    def test_main_records_system_exit_build_attempt(self):
        """SystemExit во время build_backend тоже фиксируется как failed attempt."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            env = {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}

            with patch.dict(os.environ, env, clear=True):
                with patch("create_release.get_new_build_version", return_value=TEST_BUILD_VERSION):
                    with patch("create_release.get_new_branch_name", return_value=TEST_BRANCH):
                        with patch("create_release.build_backend", side_effect=SystemExit(1)):
                            with self.assertRaises(SystemExit):
                                create_release.main()

            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "select build_version, status, error from build_attempts"
                ).fetchone()

        self.assertEqual(row, (TEST_BUILD_VERSION, "failed", "1"))

    def test_main_records_success_build_attempt(self):
        """Успешный create_release записывает success attempt с commits из manifest."""
        manifest = {
            "repositories": {
                "backend": {"commit_sha": TEST_BACKEND_COMMIT},
                "frontend": {"commit_sha": TEST_FRONTEND_COMMIT},
            },
            "artifacts": {"backend_db": {}},
        }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            env = {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}

            with patch.dict(os.environ, env, clear=True):
                with patch("create_release.get_new_build_version", return_value=TEST_BUILD_VERSION):
                    with patch("create_release.get_new_branch_name", return_value=TEST_BRANCH):
                        with patch("create_release.build_backend", return_value={}):
                            with patch("create_release.build_frontend"):
                                with patch("create_release.write_release_manifest", return_value=manifest):
                                    self.assertEqual(create_release.main(), 0)

            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "select build_version, status, backend_commit, frontend_commit, error from build_attempts"
                ).fetchone()

        self.assertEqual(row, (TEST_BUILD_VERSION, "success", TEST_BACKEND_COMMIT, TEST_FRONTEND_COMMIT, ""))

    def test_write_release_manifest_keeps_release_record_behavior(self):
        """write_release_manifest пишет manifest file и release row в SQLite."""
        backend_repo = {
            "source_repo_path": "backend",
            "source_remote_url": "https://example/backend.git",
            "branch": "dev",
            "commit_sha": TEST_BACKEND_COMMIT,
            "commit_short_sha": TEST_BACKEND_COMMIT,
        }
        frontend_repo = {
            "source_repo_path": "frontend",
            "source_remote_url": "https://example/frontend.git",
            "branch": "dev",
            "commit_sha": TEST_FRONTEND_COMMIT,
            "commit_short_sha": TEST_FRONTEND_COMMIT,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / STATE_DB_NAME
            release_root = root / "releases"
            env = {
                "SIMPLE_DEPLOY_STATE_DB": str(db_path),
                "RELEASE_ROOT_WINDOWS": str(release_root),
                "BACKEND_SOURCE_REPO_PATH": "backend",
                "FRONTEND_SOURCE_REPO_PATH": "frontend",
            }

            with patch.dict(os.environ, env, clear=True):
                with patch("create_release.repo_manifest", side_effect=[backend_repo, frontend_repo]):
                    manifest = create_release.write_release_manifest(
                        TEST_BUILD_VERSION,
                        backend_artifacts={"db_data_sql_enabled": False},
                    )

            with closing(sqlite3.connect(db_path)) as connection:
                row = connection.execute(
                    "select build_version, backend_commit, frontend_commit from releases"
                ).fetchone()
            manifest_path_exists = (release_root / TEST_BUILD_VERSION / "release_manifest.json").is_file()

        self.assertEqual(row, (TEST_BUILD_VERSION, TEST_BACKEND_COMMIT, TEST_FRONTEND_COMMIT))
        self.assertEqual(manifest["artifacts"]["backend_db"], {"db_data_sql_enabled": False})
        self.assertTrue(manifest_path_exists)


if __name__ == "__main__":
    unittest.main()
