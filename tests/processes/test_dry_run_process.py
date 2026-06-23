import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.application.requests import DryRunRequest  # noqa: E402
from simple_deploy.processes.dry_run import dry_run, required_env_keys  # noqa: E402


class DryRunProcessTests(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        env = {key: f"value-{key}" for key in required_env_keys()}
        env["GIT_BASH_PATH"] = sys.executable
        return env

    def test_required_env_keys_app_only_excludes_db_connection_keys(self):
        keys = set(required_env_keys(app_only=True))

        self.assertNotIn("DB_VM_HOST", keys)
        self.assertNotIn("DB_VM_USER", keys)
        self.assertNotIn("DB_PORT", keys)
        self.assertNotIn("DB_NAME", keys)
        self.assertIn("APP_VM_HOST", keys)

    def test_dry_run_returns_config_failure_when_env_loading_fails(self):
        with patch(
            "simple_deploy.processes.dry_run.load_env",
            side_effect=RuntimeError("bad env"),
        ):
            result = dry_run(DryRunRequest())

        self.assertFalse(result.ok)
        self.assertEqual(result.details["stage"], "config")

    def test_dry_run_app_only_skips_db_and_succeeds_when_app_ssh_unavailable(self):
        env = self._env()
        runtime = {
            "healthcheck_enabled": True,
            "maintenance_stub_enabled": True,
            "outlook_email_enabled": False,
        }

        with patch("simple_deploy.processes.dry_run.load_env", return_value=env) as load_env_mock:
            with patch(
                "simple_deploy.processes.dry_run.load_runtime_config",
                return_value=(runtime, []),
            ):
                with patch(
                    "simple_deploy.processes.dry_run.check_runtime_config",
                    return_value=True,
                ):
                    with patch(
                        "simple_deploy.processes.dry_run.check_ssh_runtime",
                        return_value={"app": False, "db": False},
                    ):
                        with self._patched_read_only_checks() as calls:
                            result = dry_run(DryRunRequest(app_only=True))

        self.assertTrue(result.ok)
        load_env_mock.assert_called_once()
        self.assertTrue(load_env_mock.call_args.kwargs["require_secrets"] is False)
        calls["check_maintenance_stub_archive"].assert_not_called()
        calls["check_db_psql_login"].assert_not_called()

    def test_dry_run_skips_data_insert_check_when_data_sql_disabled(self):
        env = self._env()
        runtime = {
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "outlook_email_enabled": False,
        }

        with patch("simple_deploy.processes.dry_run.load_env", return_value=env):
            with patch(
                "simple_deploy.processes.dry_run.load_runtime_config",
                return_value=(runtime, []),
            ):
                with patch(
                    "simple_deploy.processes.dry_run.check_runtime_config",
                    return_value=True,
                ):
                    with patch(
                        "simple_deploy.processes.dry_run.check_ssh_runtime",
                        return_value={"app": False, "db": False},
                    ):
                        with self._patched_read_only_checks() as calls:
                            result = dry_run(
                                DryRunRequest(skip_data_sql_artifacts=True)
                            )

        self.assertTrue(result.ok)
        calls["check_backend_data_insert_idempotency"].assert_not_called()

    def test_dry_run_records_failure_when_ssh_runtime_raises(self):
        env = self._env()
        runtime = {
            "healthcheck_enabled": True,
            "maintenance_stub_enabled": False,
            "outlook_email_enabled": False,
        }

        with patch("simple_deploy.processes.dry_run.load_env", return_value=env):
            with patch(
                "simple_deploy.processes.dry_run.load_runtime_config",
                return_value=(runtime, []),
            ):
                with patch(
                    "simple_deploy.processes.dry_run.check_runtime_config",
                    return_value=True,
                ):
                    with patch(
                        "simple_deploy.processes.dry_run.check_ssh_runtime",
                        side_effect=RuntimeError("ssh unavailable"),
                    ):
                        with self._patched_read_only_checks():
                            result = dry_run(DryRunRequest())

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "dry-run checks failed")

    def _patched_read_only_checks(self):
        return _PatchedDryRunChecks()


class _PatchedDryRunChecks:
    def __enter__(self):
        names = [
            "check_command",
            "check_windows_command",
            "check_ssh_key_files",
            "check_repo",
            "check_origin_network",
            "check_backend_build_inputs",
            "check_backend_data_insert_idempotency",
            "check_outlook_email_config",
            "check_maintenance_stub_archive",
            "check_app_deploy_directories",
            "check_app_manage_py",
            "check_service_permissions",
            "check_http",
            "check_db_psql_login",
        ]
        self._patches = [
            patch(f"simple_deploy.processes.dry_run.{name}") for name in names
        ]
        self.calls = {
            name: patcher.start()
            for name, patcher in zip(names, self._patches)
        }
        self.calls["check_repo"].return_value = ""
        return self.calls

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self._patches):
            patcher.stop()
        return False
