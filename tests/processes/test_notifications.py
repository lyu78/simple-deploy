import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.commands import CommandResult  # noqa: E402
from simple_deploy.processes.notifications import (  # noqa: E402
    git_log_merge_commits,
    merge_request_line,
    release_changelog_text,
    repo_changelog_text,
    send_outlook_success_email,
)
from simple_deploy.release.artifacts import Artifact  # noqa: E402
from simple_deploy.release.manifest import RELEASE_MANIFEST_NAME  # noqa: E402


class NotificationTests(unittest.TestCase):
    def test_git_log_merge_commits_parses_records_and_skips_empty_entries(self):
        stdout = "sha1\x1fMerge branch\x1fTitle\nSee merge request group/repo!42\x1e"

        with patch(
            "simple_deploy.processes.notifications.run_command",
            return_value=CommandResult(0, stdout, ""),
        ) as run_mock:
            commits = git_log_merge_commits("repo", "old", "new")

        self.assertEqual(
            commits,
            [
                {
                    "sha": "sha1",
                    "subject": "Merge branch",
                    "body": "Title\nSee merge request group/repo!42",
                }
            ],
        )
        self.assertIn("--first-parent", run_mock.call_args.args[0])

    def test_git_log_merge_commits_raises_command_detail_on_failure(self):
        with patch(
            "simple_deploy.processes.notifications.run_command",
            return_value=CommandResult(128, "", "bad revision"),
        ):
            with self.assertRaisesRegex(RuntimeError, "bad revision"):
                git_log_merge_commits("repo", "old", "new")

    def test_merge_request_line_uses_body_title(self):
        line = merge_request_line(
            {
                "sha": "abc",
                "subject": "Merge branch feature",
                "body": "Human title\n\nSee merge request group/repo!123",
            }
        )

        self.assertEqual(line, "- !123 Human title")

    def test_merge_request_line_returns_none_without_gitlab_footer(self):
        self.assertIsNone(
            merge_request_line(
                {
                    "sha": "abc",
                    "subject": "Merge branch feature",
                    "body": "No merge request footer",
                }
            )
        )

    def test_repo_changelog_text_handles_common_unavailable_cases(self):
        missing_metadata = repo_changelog_text("Backend", {}, {})
        same_sha = repo_changelog_text(
            "Backend",
            {"commit_sha": "abc"},
            {"commit_sha": "abc"},
        )
        missing_path = repo_changelog_text(
            "Backend",
            {"commit_sha": "def"},
            {"commit_sha": "abc"},
        )

        self.assertIn("Backend:", missing_metadata)
        self.assertIn("недоступен", missing_metadata)
        self.assertIn("Изменений нет", same_sha)
        self.assertIn("source-репозиторию", missing_path)

    def test_repo_changelog_text_returns_mr_lines(self):
        with patch(
            "simple_deploy.processes.notifications.git_log_merge_commits",
            return_value=[
                {
                    "sha": "abc",
                    "subject": "Merge",
                    "body": "Title\nSee merge request group/repo!7",
                }
            ],
        ):
            text = repo_changelog_text(
                "Backend",
                {"commit_sha": "def", "source_repo_path": "repo"},
                {"commit_sha": "abc"},
            )

        self.assertEqual(text, "Backend:\n- !7 Title")

    def test_repo_changelog_text_reports_missing_merge_request_lines_and_git_errors(self):
        with patch(
            "simple_deploy.processes.notifications.git_log_merge_commits",
            return_value=[{"sha": "abc", "subject": "Merge", "body": "No MR"}],
        ):
            no_mrs = repo_changelog_text(
                "Backend",
                {"commit_sha": "def", "source_repo_path": "repo"},
                {"commit_sha": "abc"},
            )
        with patch(
            "simple_deploy.processes.notifications.git_log_merge_commits",
            side_effect=RuntimeError("bad git"),
        ):
            git_error = repo_changelog_text(
                "Backend",
                {"commit_sha": "def", "source_repo_path": "repo"},
                {"commit_sha": "abc"},
            )

        self.assertIn("не найдены", no_mrs)
        self.assertIn("bad git", git_error)

    def test_release_changelog_text_reports_missing_current_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = release_changelog_text(Path(tmp))

        self.assertIn("текущего релиза", text)

    def test_release_changelog_text_reports_previous_release_and_incomplete_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_dir = root / "1.2.2"
            current_dir = root / "1.2.3"
            previous_dir.mkdir()
            current_dir.mkdir()
            (previous_dir / RELEASE_MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "build_version": "1.2.2",
                        "repositories": {
                            "backend": {"commit_sha": "old-backend"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (current_dir / RELEASE_MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "build_version": "1.2.3",
                        "repositories": {
                            "backend": {"commit_sha": "new-backend"},
                            "frontend": {"commit_sha": "new-frontend"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            text = release_changelog_text(current_dir)

        self.assertIn("Предыдущий релиз: 1.2.2", text)
        self.assertIn("Backend:", text)
        self.assertIn("Frontend:", text)
        self.assertIn("Метаданные релиза неполные", text)

    def test_send_outlook_success_email_skips_when_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "simple_deploy.processes.notifications.run_command"
            ) as run_mock:
                send_outlook_success_email(
                    {"DEV_DOMAIN": "dev.example.local"},
                    {"outlook_email_enabled": False},
                    "1.2.3",
                    Path(tmp),
                    [],
                )

        run_mock.assert_not_called()

    def test_send_outlook_success_email_skips_empty_recipient_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "simple_deploy.processes.notifications.run_command"
            ) as run_mock:
                send_outlook_success_email(
                    {"DEV_DOMAIN": "dev.example.local"},
                    {"outlook_email_enabled": True, "outlook_email_recipients": []},
                    "1.2.3",
                    Path(tmp),
                    [],
                )

        run_mock.assert_not_called()

    def test_send_outlook_success_email_non_required_failure_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            with patch(
                "simple_deploy.processes.notifications.release_changelog_text",
                return_value="none",
            ):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(1, "", "outlook failed"),
                ):
                    send_outlook_success_email(
                        {"DEV_DOMAIN": "dev.example.local"},
                        {
                            "outlook_email_enabled": True,
                            "outlook_email_required": False,
                            "outlook_email_recipients": ["dev@example.local"],
                            "outlook_email_subject": "Release {build_version}",
                            "outlook_email_body": "{release_changelog_text}",
                        },
                        "1.2.3",
                        release_dir,
                        [],
                    )

    def test_send_outlook_success_email_required_failure_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            (release_dir / RELEASE_MANIFEST_NAME).write_text("{}", encoding="utf-8")

            with patch(
                "simple_deploy.processes.notifications.release_changelog_text",
                return_value="none",
            ):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(1, "", "outlook failed"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "outlook failed"):
                        send_outlook_success_email(
                            {"DEV_DOMAIN": "dev.example.local"},
                            {
                                "outlook_email_enabled": True,
                                "outlook_email_required": True,
                                "outlook_email_recipients": [
                                    "dev@example.local"
                                ],
                                "outlook_email_subject": "Release {build_version}",
                                "outlook_email_body": "{release_changelog_text}",
                            },
                            "1.2.3",
                            release_dir,
                            [
                                Artifact(
                                    name="backend",
                                    local_path=release_dir / "backend.tar.gz",
                                    remote_archive="/tmp/backend.tar.gz",
                                    extract_path="/opt/backend",
                                )
                            ],
                        )

    def test_send_outlook_success_email_sends_payload_without_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            with patch(
                "simple_deploy.processes.notifications.release_changelog_text",
                return_value="none",
            ):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(
                        {"DEV_DOMAIN": "dev.example.local"},
                        {
                            "outlook_email_enabled": True,
                            "outlook_email_recipients": ["dev@example.local"],
                            "outlook_email_subject": "Release {build_version}",
                            "outlook_email_body": "{stand_url}",
                        },
                        "1.2.3",
                        release_dir,
                        [],
                    )

        payload = json.loads(run_mock.call_args.kwargs["input_text"])
        self.assertEqual(payload["attachments"], [])
        self.assertEqual(payload["subject"], "Release 1.2.3")

    def test_send_outlook_success_email_sends_payload_with_cc_and_manifest_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            (release_dir / RELEASE_MANIFEST_NAME).write_text("{}", encoding="utf-8")
            artifact = Artifact(
                name="frontend",
                local_path=release_dir / "frontend.tar.gz",
                remote_archive="/tmp/frontend.tar.gz",
                extract_path="/opt/frontend",
            )
            with patch(
                "simple_deploy.processes.notifications.release_changelog_text",
                return_value="changes",
            ):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(
                        {"DEV_DOMAIN": "dev.example.local"},
                        {
                            "outlook_email_enabled": True,
                            "outlook_email_recipients": "dev@example.local;ops@example.local",
                            "outlook_email_cc": ["lead@example.local"],
                            "outlook_email_subject": "Release {build_version}",
                            "outlook_email_body": "{artifacts_text}\n{release_changelog_text}",
                        },
                        "1.2.3",
                        release_dir,
                        [artifact],
                    )

        payload = json.loads(run_mock.call_args.kwargs["input_text"])
        self.assertEqual(
            payload["to"],
            ["dev@example.local", "ops@example.local"],
        )
        self.assertEqual(payload["cc"], ["lead@example.local"])
        self.assertEqual(payload["attachments"], [str(release_dir / RELEASE_MANIFEST_NAME)])
        self.assertIn("frontend", payload["body"])
        self.assertIn("changes", payload["body"])
