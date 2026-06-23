import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.build_env import (  # noqa: E402
    data_sql_artifacts_enabled,
    prepare_build_env,
    prepare_frontend_env_files,
    set_env_line,
)


class BuildEnvTests(unittest.TestCase):
    def test_prepare_build_env_preserves_explicit_overrides(self):
        with patch.dict(os.environ, {"EXISTING": "1"}, clear=True):
            build_env = prepare_build_env(
                {
                    "BACKEND_SOURCE_REPO_PATH": r"C:\repos\backend",
                    "BACKEND_APP_ROOT_DIR": "custom_app",
                    "BACKEND_DJANGO_SETTINGS_MODULE": "custom.settings",
                    "RELEASE_ROOT_WINDOWS": r"D:\releases",
                    "RELEASE_ROOT_BASH": "/custom/releases",
                    "FRONTEND_DEV_SERVER_NAME": "dev.local",
                    "DEV_DOMAIN": "dev.example.local",
                }
            )

        self.assertEqual(build_env["EXISTING"], "1")
        self.assertEqual(build_env["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], "custom_app")
        self.assertEqual(
            build_env["BACKEND_DJANGO_SETTINGS_MODULE"],
            "custom.settings",
        )
        self.assertEqual(build_env["RELEASE_ROOT_WINDOWS"], r"D:\releases")
        self.assertEqual(build_env["RELEASE_ROOT_BASH"], "/custom/releases")
        self.assertEqual(build_env["FRONTEND_DEV_SERVER_NAME"], "dev.local")
        self.assertEqual(build_env["BACKEND_REPO_ROOT_BASH"], "/c/repos/backend")

    def test_set_env_line_replaces_first_key_or_appends_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("A=1\nB=2\n", encoding="utf-8")

            set_env_line(path, "B", "updated")
            set_env_line(path, "C", "3")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "A=1\nB=updated\nC=3\n",
            )

    def test_prepare_frontend_env_files_generates_domain_specific_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder_root = Path(tmp) / "builder"
            for dirname in ("frontend_dev", "frontend_test", "frontend_prod"):
                directory = builder_root / "settings" / dirname
                directory.mkdir(parents=True)
                (directory / ".env.template").write_text(
                    "\n".join(
                        [
                            "REACT_APP_BASE_BACKEND_URL=",
                            "VITE_BASE_BACKEND_URL=",
                            "REACT_APP_FILE_PROXY_SERVICE_URL=",
                            "VITE_FILE_PROXY_SERVICE_URL=",
                            "REACT_APP_FILTERS_SERVICE_URL=",
                            "VITE_FILTERS_SERVICE_URL=",
                            "VITE_BUILD_VERSION=old",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

            env = {
                "DEV_DOMAIN": "dev.example.local",
                "TEST_DOMAIN": "test.example.local",
                "PROD_DOMAIN": "prod.example.local",
            }
            with patch("simple_deploy.core.build_env.BUILDER_ROOT", builder_root):
                prepare_frontend_env_files(env, build_version="1.2.3")

            dev_env = (
                builder_root / "settings" / "frontend_dev" / ".env"
            ).read_text(encoding="utf-8")
            test_env = (
                builder_root / "settings" / "frontend_test" / ".env"
            ).read_text(encoding="utf-8")
            prod_env = (
                builder_root / "settings" / "frontend_prod" / ".env"
            ).read_text(encoding="utf-8")

        self.assertIn("REACT_APP_BASE_BACKEND_URL=https://dev.example.local", dev_env)
        self.assertIn("VITE_FILE_PROXY_SERVICE_URL=https://dev.example.local/file/", dev_env)
        self.assertIn("VITE_FILTERS_SERVICE_URL=https://dev.example.local/filters/", dev_env)
        self.assertIn("VITE_BUILD_VERSION=1.2.3", dev_env)
        self.assertIn("https://test.example.local", test_env)
        self.assertIn("https://prod.example.local", prod_env)

    def test_prepare_frontend_env_files_reports_missing_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder_root = Path(tmp) / "builder"
            (builder_root / "settings" / "frontend_dev").mkdir(parents=True)
            env = {
                "DEV_DOMAIN": "dev.example.local",
                "TEST_DOMAIN": "test.example.local",
                "PROD_DOMAIN": "prod.example.local",
            }

            with patch("simple_deploy.core.build_env.BUILDER_ROOT", builder_root):
                with self.assertRaisesRegex(RuntimeError, "Не найден frontend template"):
                    prepare_frontend_env_files(env)

    def test_data_sql_artifacts_enabled_is_inverse_of_skip_flag(self):
        self.assertTrue(data_sql_artifacts_enabled(False))
        self.assertFalse(data_sql_artifacts_enabled(True))


if __name__ == "__main__":
    unittest.main()
