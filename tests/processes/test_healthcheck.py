import sys
import unittest
from pathlib import Path
from urllib import error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.commands import CommandResult  # noqa: E402
from simple_deploy.processes.healthcheck import (  # noqa: E402
    check_portal_release_version,
    healthcheck,
    script_urls_from_html,
    verify_maintenance_stub_http,
    version_found_in_text,
)


class HealthcheckTests(unittest.TestCase):
    def test_script_urls_from_html_keeps_only_same_origin_scripts(self):
        urls = script_urls_from_html(
            "https://dev.example.local/app/",
            """
            <html>
              <script src="/assets/app.js"></script>
              <script src="chunk.js"></script>
              <script src="https://cdn.example.local/external.js"></script>
            </html>
            """,
        )

        self.assertEqual(
            urls,
            [
                "https://dev.example.local/assets/app.js",
                "https://dev.example.local/app/chunk.js",
            ],
        )

    def test_version_found_in_text_allows_spaced_separators(self):
        self.assertTrue(version_found_in_text("release 1 . 2 - 3", "1.2-3"))

    def test_portal_version_check_scans_assets_after_html_miss(self):
        env = {"DEV_DOMAIN": "dev.example.local"}
        runtime = {
            "portal_version_check_enabled": True,
            "portal_version_asset_limit": 3,
            "healthcheck_validate_certs": False,
        }

        def fake_read(url, _context):
            if url == "https://dev.example.local/":
                return (
                    "<script src='/assets/a.js'></script>"
                    "<script src='https://cdn.example.local/skip.js'></script>"
                )
            if url == "https://dev.example.local/assets/a.js":
                return "window.version = '1.2.3'"
            raise AssertionError(url)

        with patch(
            "simple_deploy.processes.healthcheck.read_http_text",
            side_effect=fake_read,
        ):
            check_portal_release_version(env, runtime, "1.2.3")

    def test_portal_version_check_raises_when_version_missing(self):
        with patch(
            "simple_deploy.processes.healthcheck.read_http_text",
            return_value="<script src='/assets/a.js'></script>",
        ):
            with self.assertRaisesRegex(RuntimeError, "1.2.3 not found"):
                check_portal_release_version(
                    {"DEV_DOMAIN": "dev.example.local"},
                    {
                        "portal_version_check_enabled": True,
                        "portal_version_asset_limit": 1,
                        "healthcheck_validate_certs": False,
                    },
                    "1.2.3",
                )

    def test_maintenance_stub_retries_http_errors_without_sleep_after_last(self):
        http_error = error.HTTPError(
            url="https://dev.example.local/",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=None,
        )

        with patch(
            "simple_deploy.processes.healthcheck.read_http_text",
            side_effect=[http_error, "<html>stub-marker</html>"],
        ):
            with patch("simple_deploy.processes.healthcheck.time.sleep") as sleep_mock:
                verify_maintenance_stub_http(
                    {"DEV_DOMAIN": "dev.example.local"},
                    {
                        "maintenance_stub_verify_enabled": True,
                        "maintenance_stub_verify_marker": "stub-marker",
                        "maintenance_stub_verify_retries": 2,
                        "maintenance_stub_verify_delay": 5,
                        "healthcheck_validate_certs": False,
                    },
                )

        sleep_mock.assert_called_once_with(5)

    def test_healthcheck_accepts_http_error_403_and_runs_remote_commands(self):
        http_error = error.HTTPError(
            url="https://dev.example.local/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

        with patch(
            "simple_deploy.processes.healthcheck.request.urlopen",
            side_effect=http_error,
        ):
            with patch(
                "simple_deploy.processes.healthcheck.check_portal_release_version"
            ) as version_mock:
                with patch(
                    "simple_deploy.processes.healthcheck.ssh_command",
                    return_value=CommandResult(0, "ok", ""),
                ) as ssh_mock:
                    with patch(
                        "simple_deploy.processes.healthcheck.run_or_raise"
                    ) as raise_mock:
                        healthcheck(
                            {
                                "DEV_DOMAIN": "dev.example.local",
                                "APP_VM_USER": "deploy",
                                "APP_VM_HOST": "app.example.local",
                            },
                            {
                                "healthcheck_retries": 1,
                                "healthcheck_delay": 0,
                                "healthcheck_validate_certs": False,
                                "healthcheck_commands": ["systemctl status app"],
                            },
                            expected_version="1.2.3",
                        )

        version_mock.assert_called_once()
        ssh_mock.assert_called_once()
        raise_mock.assert_called_once()
