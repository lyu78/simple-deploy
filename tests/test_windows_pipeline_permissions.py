import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.windows_pipeline import (
    Artifact,
    CommandResult,
    create_backend_summary_mr,
    derive_service_permission_check,
    is_sudo_command,
    resolve_db_schema_artifact,
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
            artifact_path = release_dir / "db_schema_r_1.2.3-c_abc123.tar.gz"
            artifact_path.write_text("", encoding="utf-8")

            artifact = resolve_db_schema_artifact(
                {"REMOTE_TMP_ROOT": "/tmp/simple-deploy"},
                "1.2.3",
                release_dir,
            )

            self.assertEqual(artifact.local_path, artifact_path)
            self.assertEqual(artifact.remote_archive, "/tmp/simple-deploy/1.2.3/db_schema.tar.gz")
            self.assertEqual(artifact.remote_extract_path, "/tmp/simple-deploy/1.2.3/db_schema")
            self.assertEqual(artifact.entrypoint_dir, "docs/database/summary")
            self.assertEqual(artifact.entrypoint_pattern, "summary_sql_*.sql")

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

    def test_create_backend_summary_mr_commits_only_summary_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp)
            responses = [
                CommandResult(0, "?? docs/database/summary/summary_sql_2026.sql\n", ""),
                CommandResult(0, "", ""),
                CommandResult(0, "", ""),
                CommandResult(0, "[feature/db-summary] commit\n", ""),
                CommandResult(0, "remote: See merge request backend!1\n", ""),
                CommandResult(0, "", ""),
            ]

            with patch("tools.windows_pipeline.run_command", side_effect=responses) as run_mock:
                create_backend_summary_mr(
                    {"BACKEND_SOURCE_REPO_PATH": str(repo_path)},
                    "1.2.3",
                )

            commands = [call.args[0] for call in run_mock.call_args_list]
            self.assertEqual(commands[0], ["git", "status", "--porcelain", "--", "docs/database/summary"])
            self.assertEqual(commands[2], ["git", "add", "docs/database/summary"])
            self.assertEqual(commands[3], ["git", "commit", "-m", "Add DB summary SQL for 1.2.3"])
            self.assertIn("merge_request.create", commands[4])
            self.assertIn("merge_request.target=dev", commands[4])
            self.assertEqual(commands[5], ["git", "switch", "dev"])

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
