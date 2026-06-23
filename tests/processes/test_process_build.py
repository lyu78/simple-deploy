"""Тесты build process и build CLI wrapper."""

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

DEFAULT_ENV_FILE = TOOLS_CI_ROOT / ".env"
DEFAULT_SECRETS_FILE = TOOLS_CI_ROOT / "local.secrets.env"

BACKEND_SOURCE_REPO_WINDOWS = r"C:\example\repos\backend-source"
BACKEND_TARGET_REPO_BASH = "/c/example/repos/backend-target"
BACKEND_SOURCE_REPO_BASH = "/c/example/repos/backend-source"
DEV_DOMAIN = "dev.example.local"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.cli.windows_pipeline import build  # noqa: E402
from simple_deploy.core.build_env import prepare_build_env  # noqa: E402
from simple_deploy.core.paths import BUILDER_ROOT  # noqa: E402


class ProcessBuildTests(unittest.TestCase):
    """Проверяет build process без deploy/dry-run сценариев."""

    def test_prepare_build_env_uses_backend_source_repo_for_archive_root(self):
        """Backend archive строится из source repo, а не target repo."""
        build_env = prepare_build_env(
            {
                "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
                "BACKEND_TARGET_REPO_PATH_BASH": BACKEND_TARGET_REPO_BASH,
                "BACKEND_REPO_ROOT_BASH": "/c/wrong",
                "DEV_DOMAIN": DEV_DOMAIN,
            }
        )

        self.assertEqual(
            build_env["BACKEND_REPO_ROOT_BASH"], BACKEND_SOURCE_REPO_BASH
        )
        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], "example_backend_app")
        self.assertEqual(
            build_env["BACKEND_DJANGO_SETTINGS_MODULE"],
            "example_backend_app.settings.base",
        )

    def test_prepare_build_env_sets_pip_defaults(self):
        """Build env получает безопасные pip defaults."""
        with patch.dict("os.environ", {}, clear=True):
            build_env = prepare_build_env(
                {
                    "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
                    "DEV_DOMAIN": DEV_DOMAIN,
                }
            )

        self.assertEqual(build_env["PIP_DISABLE_PIP_VERSION_CHECK"], "1")
        self.assertEqual(
            build_env["PIP_TRUSTED_HOST"],
            "pypi.org files.pythonhosted.org pypi.python.org",
        )

    def test_build_runs_create_release_from_builder_root_with_prepared_env(self):
        """Build wrapper запускает builder/create_release.py из builder root."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            timeout=123,
            include_data_sql=False,
            skip_data_sql_artifacts=False,
        )
        env = {
            "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
            "DEV_DOMAIN": DEV_DOMAIN,
        }
        prepared_env = {"BASE": "1"}

        with patch(
            "simple_deploy.processes.build.load_env", return_value=env
        ) as load_env_mock:
            with patch(
                "simple_deploy.processes.build.prepare_frontend_env_files"
            ) as frontend_env_mock:
                with patch(
                    "simple_deploy.processes.build.prepare_build_env",
                    return_value=prepared_env,
                ) as prepare_env_mock:
                    with patch(
                        "simple_deploy.processes.build.stream_command",
                        return_value=7,
                    ) as stream_mock:
                        self.assertEqual(build(args), 7)

        load_env_mock.assert_called_once_with(
            DEFAULT_ENV_FILE, DEFAULT_SECRETS_FILE, require_secrets=False
        )
        frontend_env_mock.assert_called_once_with(env)
        prepare_env_mock.assert_called_once_with(env)
        stream_mock.assert_called_once()
        self.assertEqual(
            stream_mock.call_args.args[0],
            [sys.executable, "-u", "create_release.py"],
        )
        self.assertEqual(stream_mock.call_args.kwargs["cwd"], BUILDER_ROOT)
        self.assertEqual(stream_mock.call_args.kwargs["timeout"], 123)
        self.assertEqual(stream_mock.call_args.kwargs["env"]["BASE"], "1")
        self.assertEqual(
            stream_mock.call_args.kwargs["env"][
                "SIMPLE_DEPLOY_INCLUDE_DATA_SQL"
            ],
            "1",
        )

    def test_build_enables_data_sql_by_default(self):
        """Build по умолчанию включает генерацию data SQL artifacts."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            timeout=3600,
            include_data_sql=False,
            skip_data_sql_artifacts=False,
        )
        env = {
            "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
            "DEV_DOMAIN": DEV_DOMAIN,
        }
        with patch("simple_deploy.processes.build.load_env", return_value=env):
            with patch("simple_deploy.processes.build.prepare_frontend_env_files"):
                with patch(
                    "simple_deploy.processes.build.stream_command",
                    return_value=0,
                ) as stream_mock:
                    self.assertEqual(build(args), 0)

        build_env = stream_mock.call_args.kwargs["env"]
        self.assertEqual(build_env["SIMPLE_DEPLOY_INCLUDE_DATA_SQL"], "1")

    def test_build_skips_data_sql_with_explicit_flag(self):
        """Build выключает data SQL generation по явному CLI flag."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            timeout=3600,
            include_data_sql=False,
            skip_data_sql_artifacts=True,
        )
        env = {
            "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
            "DEV_DOMAIN": DEV_DOMAIN,
        }
        with patch("simple_deploy.processes.build.load_env", return_value=env):
            with patch("simple_deploy.processes.build.prepare_frontend_env_files"):
                with patch(
                    "simple_deploy.processes.build.stream_command",
                    return_value=0,
                ) as stream_mock:
                    self.assertEqual(build(args), 0)

        build_env = stream_mock.call_args.kwargs["env"]
        self.assertEqual(build_env["SIMPLE_DEPLOY_INCLUDE_DATA_SQL"], "0")


if __name__ == "__main__":
    unittest.main()
