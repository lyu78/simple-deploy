import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.commands import (  # noqa: E402
    CommandResult,
    decode_subprocess_output,
    run_command,
    run_or_raise,
    stream_command,
)


class CommandTests(unittest.TestCase):
    def test_decode_subprocess_output_falls_back_to_windows_encodings(self):
        self.assertEqual(
            decode_subprocess_output("привет".encode("cp1251")),
            "привет",
        )

    def test_run_command_masks_stdout_and_stderr(self):
        result = run_command(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "print('token=secret'); "
                    "print('err=secret', file=sys.stderr)"
                ),
            ],
            mask=["secret"],
        )

        self.assertEqual(result.rc, 0)
        self.assertEqual(result.stdout.strip(), "token=***")
        self.assertEqual(result.stderr.strip(), "err=***")

    def test_run_command_reports_missing_executable(self):
        result = run_command(["simple-deploy-definitely-missing-command"])

        self.assertEqual(result.rc, 127)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)

    def test_run_command_converts_timeout_to_result(self):
        with patch(
            "simple_deploy.core.commands.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["slow"],
                timeout=3,
                output=b"partial stdout",
                stderr=b"",
            ),
        ):
            result = run_command(["slow"], timeout=3)

        self.assertEqual(result.rc, 124)
        self.assertEqual(result.stdout, "partial stdout")
        self.assertEqual(result.stderr, "timeout after 3s")

    def test_run_or_raise_masks_secrets_in_failure_detail(self):
        with self.assertRaisesRegex(RuntimeError, r"stdout:\nvisible \*\*\*"):
            run_or_raise(
                "sample",
                CommandResult(1, "visible secret", "hidden secret"),
                mask=["secret"],
            )

    def test_stream_command_logs_masked_output(self):
        with patch("simple_deploy.core.commands._log_line") as log_mock:
            rc = stream_command(
                [
                    sys.executable,
                    "-c",
                    "print('token=secret')",
                ],
                mask=["secret"],
            )

        self.assertEqual(rc, 0)
        logged = "\n".join(call.args[0] for call in log_mock.call_args_list)
        self.assertIn("token=***", logged)
        self.assertNotIn("token=secret", logged)
