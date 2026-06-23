"""Tests for WindowsPipelineRuntimeConfigTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineRuntimeConfigTests(WindowsPipelineTestCase):

    def test_windows_pipeline_example_runtime_config_is_valid(self):
        """Фиксирует, что example runtime config остается валидным шаблоном."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_runtime_config_rejects_bad_maintenance_timeout(self):
        """Отклоняет нечисловой timeout maintenance SQL до запуска deploy."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["db_maintenance_sql_timeout_seconds"] = "900s"
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("db_maintenance_sql_timeout_seconds" in issue for issue in reporter.issues))

    def test_runtime_config_checks_sql_script_shape(self):
        """Проверяет форму записей sql_scripts в runtime config."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["sql_scripts"] = [{"path": "missing.sql", "phase": "after_unpack"}]
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("sql_scripts #1" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_bare_systemctl_service_step(self):
        """Запрещает service step с systemctl mutation без sudo."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "stop celerybeat",
                "phase": "before_unpack",
                "command": "systemctl stop celerybeat_local.service",
            }
        ]
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("systemctl service commands except status must use sudo" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_stop_nginx_before_frontend_unpack(self):
        """Запрещает stop nginx до выкладки frontend, чтобы не раскрыть основной UI."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "stop nginx",
                "phase": "before_unpack",
                "command": "sudo /bin/systemctl stop nginx",
                "permission_check_command": "sudo /bin/systemctl stop nginx",
            }
        ]
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("after_frontend_unpack" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_nginx_stop_start_before_frontend_unpack(self):
        """Запрещает любые stop/start nginx фазы раньше after_frontend_unpack."""
        for verb in ("stop", "start"):
            with self.subTest(verb=verb):
                runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
                runtime["service_steps"] = [
                    {
                        "name": f"{verb} nginx early",
                        "phase": "after_migrate",
                        "command": f"sudo /bin/systemctl {verb} nginx.service",
                    }
                ]
                reporter = Reporter()

                self.assertFalse(check_runtime_config(reporter, runtime))
                self.assertTrue(any("after_frontend_unpack" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_nginx_restart_reload(self):
        """Запрещает restart/reload nginx вместо контролируемой пары stop/start."""
        for verb in ("restart", "reload", "try-restart", "reload-or-restart", "reload-or-try-restart"):
            with self.subTest(verb=verb):
                runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
                runtime["service_steps"] = [
                    {
                        "name": f"{verb} nginx after frontend",
                        "phase": "after_frontend_unpack",
                        "command": f"sudo /bin/systemctl {verb} nginx.service",
                    }
                ]
                reporter = Reporter()

                self.assertFalse(check_runtime_config(reporter, runtime))
                self.assertTrue(any("restart/reload" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_nginx_stop_without_later_start(self):
        """Запрещает stop nginx без последующего start в after_frontend_unpack."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "stop nginx after frontend",
                "phase": "after_frontend_unpack",
                "command": "sudo /bin/systemctl stop nginx",
                "permission_check_command": "sudo /bin/systemctl stop nginx",
            }
        ]
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("must be followed by nginx start" in issue for issue in reporter.issues))

    def test_runtime_config_accepts_nginx_stop_start_after_frontend_unpack(self):
        """Принимает безопасный порядок stop/start/status nginx после frontend unpack."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "stop nginx after frontend",
                "phase": "after_frontend_unpack",
                "command": "sudo /bin/systemctl stop nginx",
                "permission_check_command": "sudo /bin/systemctl stop nginx",
            },
            {
                "name": "start nginx after frontend",
                "phase": "after_frontend_unpack",
                "command": "sudo /bin/systemctl start nginx",
                "permission_check_command": "sudo /bin/systemctl start nginx",
            },
            {
                "name": "status nginx after frontend",
                "phase": "after_frontend_unpack",
                "command": "systemctl status nginx",
                "permission_check_command": "systemctl status nginx",
            },
        ]
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_runtime_config_accepts_bare_systemctl_status_service_step(self):
        """Разрешает systemctl status без sudo, потому что команда read-only."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "status celerybeat",
                "phase": "after_frontend_unpack",
                "command": "systemctl status celerybeat_local.service",
                "permission_check_command": "systemctl status celerybeat_local.service",
            }
        ]
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_runtime_config_accepts_sudo_systemctl_service_step(self):
        """Разрешает mutation service step, когда команда явно выполняется через sudo."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "stop celerybeat",
                "phase": "before_unpack",
                "command": "sudo /bin/systemctl stop celerybeat_local.service",
                "permission_check_command": "sudo /bin/systemctl stop celerybeat_local.service",
            }
        ]
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_check_ssh_runtime_app_only_skips_db_vm(self):
        """В app-only режиме dry-run не требует доступности DB VM."""
        reporter = Reporter()
        env = {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
        }

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            return_value=CommandResult(0, "ok\n", ""),
        ) as ssh_mock:
            result = check_ssh_runtime(reporter, env, app_only=True)

        self.assertEqual(result, {"app": True, "db": False})
        self.assertEqual(ssh_mock.call_count, 1)
        self.assertTrue(any("DB VM SSH/psql" in item for item in reporter.skipped))

    def test_service_permission_accepts_readable_inactive_systemctl_status(self):
        """Считает readable inactive unit достаточным результатом проверки status."""
        reporter = Reporter()
        env = {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
        }
        runtime = {
            "service_steps": [
                {
                    "name": "status keydb",
                    "command": "systemctl status keydb_local.service",
                    "permission_check_command": "systemctl status keydb_local.service",
                }
            ]
        }
        status_output = "keydb_local.service - Key DB local\nActive: inactive (dead)\n"

        with patch.object(reporter, "pass_", wraps=reporter.pass_) as pass_mock:
            with patch(
                "simple_deploy.processes.dry_run_checks.ssh_command",
                return_value=CommandResult(3, status_output, ""),
            ):
                check_service_permissions(reporter, env, runtime)

        self.assertEqual(reporter.issues, [])
        self.assertTrue(
            any("status readable; unit may be inactive" in call.args[1] for call in pass_mock.call_args_list)
        )

    def test_load_runtime_config_reports_defaulted_keys(self):
        """Фиксирует список runtime ключей, которые были взяты из defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / DEFAULT_CONFIG_FILE.name
            config_path.write_text('{"backup_enabled": true}\n', encoding="utf-8")

            runtime, defaulted_keys = load_runtime_config(config_path)

        self.assertTrue(runtime["backup_enabled"])
        self.assertIn("db_maintenance_sql_timeout_seconds", defaulted_keys)
        self.assertNotIn("backup_enabled", defaulted_keys)
