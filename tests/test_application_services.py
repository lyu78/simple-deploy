"""Tests for application service wrappers."""

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import sentinel, patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.application import services


class ApplicationServiceTests(unittest.TestCase):
    """Checks that application services are the stable entrypoint above processes."""

    def test_build_service_delegates_to_process(self):
        args = Namespace(command="build")
        with patch("simple_deploy.application.services._build_process", return_value=11) as process_mock:
            self.assertEqual(services.build(args), 11)

        process_mock.assert_called_once_with(args)

    def test_deploy_service_delegates_to_process(self):
        args = Namespace(command="deploy")
        with patch("simple_deploy.application.services._deploy_process", return_value=0) as process_mock:
            self.assertEqual(services.deploy(args), 0)

        process_mock.assert_called_once_with(args)

    def test_mark_services_delegate_to_processes(self):
        args = Namespace(command="mark")
        cases = [
            ("set_baseline", "_set_baseline_process"),
            ("mark_applied", "_mark_applied_process"),
            ("mark_failed", "_mark_failed_process"),
        ]

        for public_name, process_name in cases:
            with self.subTest(public_name=public_name):
                patch_target = f"simple_deploy.application.services.{process_name}"
                with patch(patch_target, return_value=sentinel.rc) as process_mock:
                    self.assertIs(getattr(services, public_name)(args), sentinel.rc)

                process_mock.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
