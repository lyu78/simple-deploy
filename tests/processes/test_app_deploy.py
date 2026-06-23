import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import sentinel, patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.processes.app_deploy import (  # noqa: E402
    backup_app_artifacts,
    deploy_summary_lines,
    management_commands,
    remote_clean_unpack_command,
    run_service_steps,
    unpack_app_artifact,
    upload_app_artifacts,
)
from simple_deploy.release.artifacts import Artifact  # noqa: E402


def artifact(name: str = "backend") -> Artifact:
    return Artifact(
        name=name,
        local_path=Path(f"C:/release/{name}.tar.gz"),
        remote_archive=f"/tmp/release/{name}.tar.gz",
        extract_path=f"/opt/{name}",
    )


class AppDeployTests(unittest.TestCase):
    def test_management_commands_use_configured_or_default_commands(self):
        self.assertEqual(
            management_commands(
                {"APP_MANAGE_PY_PATH": "/opt/app/manage.py"},
                {"management_commands": ["python manage.py migrate"]},
            ),
            ["python manage.py migrate"],
        )

        self.assertEqual(
            management_commands(
                {"APP_MANAGE_PY_PATH": "/opt/app/manage.py"},
                {"management_commands": []},
            ),
            [
                "python '/opt/app/manage.py' migrate --fake",
                "python '/opt/app/manage.py' sync_action_role",
            ],
        )

    def test_remote_clean_unpack_command_rejects_unsafe_roots(self):
        for extract_path in ("", "/", "////"):
            with self.subTest(extract_path=extract_path):
                unsafe = artifact()
                unsafe.extract_path = extract_path

                with self.assertRaisesRegex(RuntimeError, "Unsafe extract path"):
                    remote_clean_unpack_command(unsafe)

    def test_remote_clean_unpack_command_preserves_env_and_unpacks_archive(self):
        command = remote_clean_unpack_command(artifact())

        self.assertIn('find "$target" -mindepth 1 -maxdepth 1 ! -name ".env"', command)
        self.assertIn("tar -xzf \"$archive\" -C \"$target\" --strip-components=1", command)
        self.assertIn("archive='/tmp/release/backend.tar.gz'", command)

    def test_upload_app_artifacts_creates_remote_dir_and_uploads_each_artifact(self):
        artifacts = [artifact("backend"), artifact("frontend")]
        env = {"APP_VM_USER": "deploy", "APP_VM_HOST": "app.example.local"}

        with patch(
            "simple_deploy.processes.app_deploy.ssh_command",
            return_value=sentinel.mkdir_result,
        ) as ssh_mock:
            with patch(
                "simple_deploy.processes.app_deploy.scp_file",
                side_effect=[sentinel.backend_upload, sentinel.frontend_upload],
            ) as scp_mock:
                with patch("simple_deploy.processes.app_deploy.run_or_raise") as raise_mock:
                    upload_app_artifacts(env, artifacts, "/tmp/release/1.2.3")

        ssh_mock.assert_called_once_with(
            env,
            "deploy",
            "app.example.local",
            "mkdir -p '/tmp/release/1.2.3'",
            "APP",
        )
        self.assertEqual(scp_mock.call_count, 2)
        self.assertEqual(raise_mock.call_count, 3)
        self.assertEqual(raise_mock.call_args_list[0].args[0], "create remote release dir")
        self.assertEqual(raise_mock.call_args_list[1].args[0], "upload backend")
        self.assertEqual(raise_mock.call_args_list[2].args[0], "upload frontend")

    def test_backup_app_artifacts_skips_disabled_and_runs_enabled_backup(self):
        env = {
            "APP_VM_USER": "deploy",
            "APP_VM_HOST": "app.example.local",
            "BACKUP_ROOT_BASE": "/backup/",
        }
        app_artifact = artifact("backend")

        with patch("simple_deploy.processes.app_deploy.ssh_command") as ssh_mock:
            backup_app_artifacts(env, {"backup_enabled": False}, "1.2.3", [app_artifact])
        ssh_mock.assert_not_called()

        with patch(
            "simple_deploy.processes.app_deploy.ssh_command",
            side_effect=[sentinel.mkdir_result, sentinel.backup_result],
        ) as ssh_mock:
            with patch("simple_deploy.processes.app_deploy.run_or_raise") as raise_mock:
                backup_app_artifacts(
                    env,
                    {"backup_enabled": True},
                    "1.2.3",
                    [app_artifact],
                )

        self.assertEqual(ssh_mock.call_count, 2)
        self.assertIn("mkdir -p '/backup/1.2.3'", ssh_mock.call_args_list[0].args[3])
        backup_command = ssh_mock.call_args_list[1].args[3]
        self.assertIn("tar -czf '/backup/1.2.3/backend.tar.gz'", backup_command)
        self.assertIn("-C '/opt' 'backend'", backup_command)
        self.assertEqual(ssh_mock.call_args_list[1].kwargs["timeout"], 120)
        self.assertEqual(raise_mock.call_count, 2)

    def test_unpack_app_artifact_runs_remote_clean_unpack_command(self):
        env = {"APP_VM_USER": "deploy", "APP_VM_HOST": "app.example.local"}
        app_artifact = artifact("frontend")

        with patch(
            "simple_deploy.processes.app_deploy.ssh_command",
            return_value=sentinel.unpack_result,
        ) as ssh_mock:
            with patch("simple_deploy.processes.app_deploy.run_or_raise") as raise_mock:
                unpack_app_artifact(env, app_artifact)

        command = ssh_mock.call_args.args[3]
        self.assertIn("/tmp/release/frontend.tar.gz", command)
        self.assertIn("/opt/frontend", command)
        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 120)
        raise_mock.assert_called_once_with("unpack frontend", sentinel.unpack_result)

    def test_run_service_steps_filters_by_phase_and_uses_name_or_command_label(self):
        env = {"APP_VM_USER": "deploy", "APP_VM_HOST": "app.example.local"}
        runtime = {
            "service_steps": [
                {"phase": "before_unpack", "name": "stop app", "command": "sudo systemctl stop app"},
                {"command": "sudo systemctl restart worker"},
                {"phase": "after_unpack", "command": "echo skip"},
            ]
        }

        with patch(
            "simple_deploy.processes.app_deploy.ssh_command",
            side_effect=[sentinel.stop_result, sentinel.worker_result],
        ) as ssh_mock:
            with patch("simple_deploy.processes.app_deploy.run_or_raise") as raise_mock:
                run_service_steps(env, runtime, "before_unpack")
                run_service_steps(env, runtime, "after_migrate")

        self.assertEqual(ssh_mock.call_count, 2)
        self.assertEqual(raise_mock.call_args_list[0].args[0], "service before_unpack: stop app")
        self.assertEqual(
            raise_mock.call_args_list[1].args[0],
            "service after_migrate: sudo systemctl restart worker",
        )

    def test_run_service_steps_logs_skip_when_empty(self):
        with patch("simple_deploy.processes.app_deploy.job_log") as log_mock:
            run_service_steps({}, {"service_steps": []}, "after_migrate")

        log_mock.assert_called_once_with("SKIP service steps after_migrate: empty")

    def test_deploy_summary_lines_lists_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            lines = deploy_summary_lines(
                "1.2.3",
                release_dir,
                [artifact("backend"), artifact("frontend")],
            )

        self.assertEqual(lines[0], "build_version: 1.2.3")
        self.assertEqual(lines[1], f"release_dir: {release_dir}")
        self.assertIn("backend:", lines[2])
        self.assertIn("frontend:", lines[3])


if __name__ == "__main__":
    unittest.main()
