"""Tests for WindowsPipelineNotificationTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineNotificationTests(WindowsPipelineTestCase):

    def test_outlook_success_email_attaches_release_manifest(self):
        """Проверяет HTML-письмо Outlook и attachment release_manifest.json."""
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
            env = {"DEV_DOMAIN": DEV_DOMAIN}
            artifacts = [
                Artifact(
                    name="backend",
                    local_path=release_dir / "backend.tar.gz",
                    remote_archive="/tmp/backend.tar.gz",
                    extract_path=BACKEND_RELEASE_PATH,
                )
            ]

            with patch("simple_deploy.processes.notifications.release_changelog_text", return_value="none"):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(env, runtime, TEST_BUILD_VERSION, release_dir, artifacts)

            payload = json.loads(run_mock.call_args.kwargs["input_text"])
            self.assertEqual(payload["attachments"], [str(manifest)])
            powershell = run_mock.call_args.args[0][-1]
            self.assertIn("font-family: Arial", powershell)
            self.assertIn("font-size: 10pt", powershell)
            self.assertIn("HtmlEncode", powershell)
            self.assertIn("<br>", powershell)
