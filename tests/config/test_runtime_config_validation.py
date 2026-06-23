import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.config.runtime_loader import DEFAULT_RUNTIME_CONFIG  # noqa: E402
from simple_deploy.config.validation import (  # noqa: E402
    check_runtime_config,
    is_bare_systemctl_status_command,
    is_disallowed_bare_systemctl_command,
    nginx_systemctl_action,
    systemctl_action,
)


class Reporter:
    def __init__(self):
        self.passed = []
        self.issues = []

    def pass_(self, name: str, detail: str = "") -> None:
        self.passed.append(f"{name}: {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.issues.append(f"{name}: {detail}")


def default_runtime() -> dict:
    return json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))


class RuntimeConfigValidationTests(unittest.TestCase):
    def test_systemctl_parser_handles_sudo_options_and_invalid_shell(self):
        self.assertEqual(
            systemctl_action(
                "sudo -u root --preserve-env=PATH /bin/systemctl restart nginx.service"
            ),
            ("restart", ["nginx.service"]),
        )
        self.assertEqual(
            nginx_systemctl_action("sudo -h host /usr/bin/systemctl stop nginx"),
            "stop",
        )
        self.assertTrue(
            is_bare_systemctl_status_command('systemctl status "app.service"')
        )
        self.assertTrue(
            is_disallowed_bare_systemctl_command("systemctl start app.service")
        )
        self.assertFalse(is_bare_systemctl_status_command('systemctl status "'))
        self.assertIsNone(systemctl_action('sudo /bin/systemctl restart "'))
        self.assertIsNone(systemctl_action(["systemctl", "status"]))

    def test_check_runtime_config_reports_bad_top_level_shapes(self):
        runtime = default_runtime()
        runtime["unknown"] = True
        runtime["backup_enabled"] = "yes"
        runtime["healthcheck_retries"] = True
        runtime["db_psql_bin"] = " "
        runtime["db_maintenance_sql_phase"] = "after_frontend_unpack"
        runtime["db_maintenance_sql"] = ["VACUUM;", ""]
        runtime["healthcheck_commands"] = "curl http://example"
        runtime["outlook_email_recipients"] = ["ops@example.test", ""]
        runtime["outlook_email_subject"] = None
        runtime["sql_scripts"] = {"path": "script.sql"}
        runtime["service_steps"] = {"command": "echo ok"}
        reporter = Reporter()

        self.assertFalse(
            check_runtime_config(
                reporter,
                runtime,
                root=Path.cwd(),
                default_runtime_config=DEFAULT_RUNTIME_CONFIG,
            )
        )

        issues = "\n".join(reporter.issues)
        self.assertIn("unknown key(s): unknown", issues)
        self.assertIn("runtime backup_enabled: expected boolean", issues)
        self.assertIn("runtime healthcheck_retries: expected positive integer", issues)
        self.assertIn("runtime db_psql_bin: expected non-empty string", issues)
        self.assertIn("runtime db_maintenance_sql_phase", issues)
        self.assertIn("runtime db_maintenance_sql", issues)
        self.assertIn("runtime healthcheck_commands: expected list", issues)
        self.assertIn("runtime outlook_email_recipients", issues)
        self.assertIn("runtime outlook_email_subject: expected string", issues)
        self.assertIn("runtime sql_scripts: expected list", issues)
        self.assertIn("runtime service_steps: expected list", issues)

    def test_check_runtime_config_validates_sql_scripts_and_optional_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "scripts" / "maintenance.sql"
            script.parent.mkdir()
            script.write_text("select 1;\n", encoding="utf-8")
            runtime = default_runtime()
            runtime["sql_scripts"] = [
                {"path": "scripts/maintenance.sql", "phase": "before_migrate"},
                {"path": "scripts/missing.sql", "phase": "before_unpack"},
                {"path": "", "phase": "after_migrate"},
                "not an object",
            ]
            runtime["service_steps"] = [
                {
                    "phase": "after_frontend_unpack",
                    "command": "sudo /bin/systemctl stop nginx",
                    "name": 42,
                    "permission_check_command": "systemctl restart nginx",
                },
                {
                    "phase": "later",
                    "command": "",
                    "permission_check_command": 42,
                },
            ]
            reporter = Reporter()

            self.assertFalse(
                check_runtime_config(
                    reporter,
                    runtime,
                    root=root,
                    default_runtime_config=DEFAULT_RUNTIME_CONFIG,
                )
            )

        passed = "\n".join(reporter.passed)
        issues = "\n".join(reporter.issues)
        self.assertIn("runtime sql_scripts #1 path", passed)
        self.assertIn("runtime sql_scripts #2: path not found", issues)
        self.assertIn("runtime sql_scripts #3: path must be", issues)
        self.assertIn("runtime sql_scripts #4: expected object", issues)
        self.assertIn("name must be a string when set", issues)
        self.assertIn("permission_check_command must not use nginx restart/reload", issues)
        self.assertIn("phase must be one of", issues)
        self.assertIn("command must be a non-empty string", issues)


if __name__ == "__main__":
    unittest.main()
