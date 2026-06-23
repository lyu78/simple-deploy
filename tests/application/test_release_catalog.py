"""Tests for release catalog read/use-case helpers."""

import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"
TEST_BUILD_VERSION = "1.2.4"
TEST_BACKEND_COMMIT = "abc123"
TEST_FRONTEND_COMMIT = "def456"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.application.release_catalog import (  # noqa: E402
    initial_schema_baseline_reference,
    list_build_options,
    resolve_release_commit,
)
from simple_deploy.release.manifest import (  # noqa: E402
    RELEASE_MANIFEST_NAME,
)
from simple_deploy.release.state import (  # noqa: E402
    connect_state_db,
    record_build_attempt_finished,
    record_build_attempt_started,
    record_release,
)


class ReleaseCatalogTests(unittest.TestCase):
    def test_list_build_options_and_resolve_release_commit_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with closing(connect_state_db(db_path)) as connection:
                    record_release(
                        connection,
                        TEST_BUILD_VERSION,
                        TEST_BACKEND_COMMIT,
                        TEST_FRONTEND_COMMIT,
                        {"backend": "backend.tar.gz"},
                    )

                options = list_build_options()
                release_ref = resolve_release_commit(TEST_BUILD_VERSION)

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].build_version, TEST_BUILD_VERSION)
        self.assertEqual(options[0].backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(options[0].frontend_commit, TEST_FRONTEND_COMMIT)
        self.assertEqual(release_ref.source, "registry")
        self.assertEqual(release_ref.backend_commit, TEST_BACKEND_COMMIT)

    def test_resolve_release_commit_falls_back_to_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp) / "releases" / TEST_BUILD_VERSION
            release_dir.mkdir(parents=True)
            (release_dir / RELEASE_MANIFEST_NAME).write_text(
                (
                    '{"repositories": {'
                    f'"backend": {{"commit_sha": "{TEST_BACKEND_COMMIT}"}}, '
                    f'"frontend": {{"commit_sha": "{TEST_FRONTEND_COMMIT}"}}'
                    "}}"
                ),
                encoding="utf-8",
            )
            db_path = Path(tmp) / "state.sqlite3"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                release_ref = resolve_release_commit(
                    TEST_BUILD_VERSION,
                    release_dir=release_dir,
                )

        self.assertEqual(release_ref.source, "manifest")
        self.assertEqual(release_ref.release_dir, release_dir)
        self.assertEqual(release_ref.backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(release_ref.frontend_commit, TEST_FRONTEND_COMMIT)

    def test_build_options_include_successful_attempt_without_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with closing(connect_state_db(db_path)) as connection:
                    success_id = record_build_attempt_started(
                        connection,
                        TEST_BUILD_VERSION,
                        backend_commit=TEST_BACKEND_COMMIT,
                        frontend_commit=TEST_FRONTEND_COMMIT,
                    )
                    record_build_attempt_finished(
                        connection,
                        success_id,
                        "success",
                        backend_commit=TEST_BACKEND_COMMIT,
                        frontend_commit=TEST_FRONTEND_COMMIT,
                    )
                    failed_id = record_build_attempt_started(
                        connection,
                        "1.2.5",
                        backend_commit="fedcba",
                        frontend_commit=TEST_FRONTEND_COMMIT,
                    )
                    record_build_attempt_finished(
                        connection,
                        failed_id,
                        "failed",
                        backend_commit="fedcba",
                        frontend_commit=TEST_FRONTEND_COMMIT,
                    )

                options = list_build_options()
                release_ref = resolve_release_commit(TEST_BUILD_VERSION)

        self.assertEqual(
            [option.build_version for option in options],
            [TEST_BUILD_VERSION],
        )
        self.assertEqual(options[0].source, "build_attempt")
        self.assertEqual(release_ref.source, "build_attempt")
        self.assertEqual(release_ref.backend_commit, TEST_BACKEND_COMMIT)

    def test_initial_schema_baseline_reference_reads_runtime_config(self):
        runtime = {
            "initial_schema_baselines": {
                "prod": {
                    "build_version": "bootstrap-prod",
                    "backend_commit": TEST_BACKEND_COMMIT,
                }
            }
        }

        release_ref = initial_schema_baseline_reference(runtime, "prod")

        self.assertEqual(release_ref.source, "initial_schema_baselines")
        self.assertEqual(release_ref.build_version, "bootstrap-prod")
        self.assertEqual(release_ref.backend_commit, TEST_BACKEND_COMMIT)

    def test_initial_schema_baseline_reference_requires_configured_contour(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            initial_schema_baseline_reference(
                {"initial_schema_baselines": {}},
                "test",
            )


if __name__ == "__main__":
    unittest.main()
