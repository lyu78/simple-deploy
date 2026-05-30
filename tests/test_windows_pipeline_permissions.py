import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.windows_pipeline import (
    Artifact,
    CommandResult,
    DbSqlArtifact,
    derive_service_permission_check,
    is_sudo_command,
    resolve_db_schema_artifact,
    run_db_schema_summary,
    scp_file,
    send_outlook_success_email,
    sudo_list_command,
)


class WindowsPipelinePermissionTests(unittest.TestCase):
    def test_derive_service_permission_check_keeps_sudo_command(self):
        command = "sudo /bin/systemctl restart nginx"

        self.assertEqual(derive_service_permission_check(command), command)

    def test_sudo_list_command_checks_payload_without_running_it(self):
        self.assertEqual(
            sudo_list_command("sudo /bin/systemctl restart nginx"),
            "sudo -n -l '/bin/systemctl' 'restart' 'nginx'",
        )

    def test_sudo_list_command_strips_sudo_options(self):
        self.assertEqual(
            sudo_list_command("sudo -n -u root /bin/systemctl start example-backend"),
            "sudo -n -l '/bin/systemctl' 'start' 'example-backend'",
        )

    def test_is_sudo_command(self):
        self.assertTrue(is_sudo_command("sudo /bin/systemctl restart nginx"))
        self.assertFalse(is_sudo_command("/bin/systemctl restart nginx"))

    def test_resolve_db_schema_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            artifact_path = release_dir / "db_schema_dev_r_1.2.3-c_abc123.tar.gz"
            artifact_path.write_text("", encoding="utf-8")

            artifact = resolve_db_schema_artifact(
                {"REMOTE_TMP_ROOT": "/tmp/simple-deploy"},
                "1.2.3",
                release_dir,
            )

            self.assertEqual(artifact.local_path, artifact_path)
            self.assertEqual(artifact.remote_archive, "/tmp/simple-deploy/1.2.3/db_schema_dev.tar.gz")
            self.assertEqual(artifact.remote_extract_path, "/tmp/simple-deploy/1.2.3/db_schema_dev")
            self.assertEqual(artifact.entrypoint_dir, ".")
            self.assertEqual(artifact.entrypoint_pattern, "summary_sql_dev_*.sql")

    def test_scp_file_uses_requested_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "db_schema.tar.gz"
            local_path.write_text("", encoding="utf-8")

            with patch("tools.windows_pipeline.ssh_key_args", return_value=["DB_KEY"]) as key_mock:
                with patch(
                    "tools.windows_pipeline.run_command",
                    return_value=CommandResult(0, "", ""),
                ) as run_mock:
                    scp_file({}, local_path, "db-user", "db.example.local", "/tmp/db_schema.tar.gz", scope="DB")

            key_mock.assert_called_once_with({}, "DB")
            command = run_mock.call_args.args[0]
            self.assertIn("DB_KEY", command)
            self.assertIn(f"db-user@db.example.local:/tmp/db_schema.tar.gz", command)

    def test_run_db_schema_summary_uses_single_transaction(self):
        artifact = DbSqlArtifact(
            name="db_schema_dev",
            local_path=Path("db_schema_dev.tar.gz"),
            remote_archive="/tmp/simple-deploy/1.2.3/db_schema_dev.tar.gz",
            remote_extract_path="/tmp/simple-deploy/1.2.3/db_schema_dev",
            entrypoint_dir=".",
            entrypoint_pattern="summary_sql_dev_*.sql",
        )
        env = {
            "DB_VM_USER": "db-user",
            "DB_VM_HOST": "db.example.local",
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }

        with patch("tools.windows_pipeline.scp_file", return_value=CommandResult(0, "", "")):
            with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
                run_db_schema_summary(env, {}, artifact)

        final_command = ssh_mock.call_args_list[-1].args[3]
        self.assertIn("--set=ON_ERROR_STOP=1", final_command)
        self.assertIn("--single-transaction", final_command)
        self.assertIn('-f "$sql_file"', final_command)

    def test_ansible_schema_migration_uses_single_transaction(self):
        role_path = Path(__file__).resolve().parents[1] / "roles" / "db_migrations" / "tasks" / "main.yml"
        content = role_path.read_text(encoding="utf-8")

        self.assertIn("--set=ON_ERROR_STOP=1 --single-transaction", content)

    def test_outlook_success_email_attaches_release_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = release_dir / "release_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            runtime = {
                "outlook_email_enabled": True,
                "outlook_email_recipients": ["dev-team@example.local"],
                "outlook_email_subject": "Release {build_version}",
                "outlook_email_body": "Artifacts:\n{artifacts_text}",
            }
            env = {"DEV_DOMAIN": "dev.example.local"}
            artifacts = [
                Artifact(
                    name="backend",
                    local_path=release_dir / "backend.tar.gz",
                    remote_archive="/tmp/backend.tar.gz",
                    extract_path="/opt/backend",
                )
            ]

            with patch("tools.windows_pipeline.release_changelog_text", return_value="none"):
                with patch(
                    "tools.windows_pipeline.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(env, runtime, "1.2.3", release_dir, artifacts)

            payload = json.loads(run_mock.call_args.kwargs["input_text"])
            self.assertEqual(payload["attachments"], [str(manifest)])
            powershell = run_mock.call_args.args[0][-1]
            self.assertIn("font-family: Arial", powershell)
            self.assertIn("font-size: 10pt", powershell)
            self.assertIn("HtmlEncode", powershell)
            self.assertIn("<br>", powershell)


if __name__ == "__main__":
    unittest.main()
