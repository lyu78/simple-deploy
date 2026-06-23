"""Tests for WindowsPipelineAdapterTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineAdapterTests(WindowsPipelineTestCase):

    def test_reporter_warn_does_not_fail_result(self):
        """Фиксирует, что предупреждения Reporter не переводят dry-run в ошибку."""
        reporter = Reporter()

        reporter.warn("runtime db_maintenance_sql_timeout_seconds", "missing; using default 900")

        self.assertEqual(reporter.issues, [])
        self.assertTrue(reporter.result())
        self.assertIn("runtime db_maintenance_sql_timeout_seconds", reporter.warnings[0])

    def test_default_management_commands_fake_migrations(self):
        """Проверяет дефолтные management-команды без пользовательского runtime override."""
        commands = management_commands({"APP_MANAGE_PY_PATH": "manage.py"}, {"management_commands": []})

        self.assertEqual(
            commands,
            [
                "python 'manage.py' migrate --fake",
                "python 'manage.py' sync_action_role",
            ],
        )

    def test_derive_service_permission_check_keeps_sudo_command(self):
        """Фиксирует, что явная sudo-команда остается проверкой прав без преобразований."""
        command = "sudo /bin/systemctl restart nginx"

        self.assertEqual(derive_service_permission_check(command), command)

    def test_sudo_list_command_checks_payload_without_running_it(self):
        """Проверяет, что sudo -l строится как безопасная проверка разрешения команды."""
        self.assertEqual(
            sudo_list_command("sudo /bin/systemctl restart nginx"),
            "sudo -n -l '/bin/systemctl' 'restart' 'nginx'",
        )

    def test_sudo_list_command_strips_sudo_options(self):
        """Проверяет, что служебные sudo options не попадают в проверяемый payload."""
        self.assertEqual(
            sudo_list_command("sudo -n -u root /bin/systemctl start example-backend"),
            "sudo -n -l '/bin/systemctl' 'start' 'example-backend'",
        )

    def test_is_sudo_command(self):
        """Разделяет команды с sudo-префиксом и обычные systemctl вызовы."""
        self.assertTrue(is_sudo_command("sudo /bin/systemctl restart nginx"))
        self.assertFalse(is_sudo_command("/bin/systemctl restart nginx"))

    def test_resolve_db_schema_artifact(self):
        """Фиксирует имя, remote path и entrypoint schema SQL артефакта для DEV."""
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            artifact_path = release_dir / f"db_schema_dev_r_{TEST_BUILD_VERSION}-c_{TEST_BACKEND_COMMIT}.tar.gz"
            artifact_path.write_text("", encoding="utf-8")

            artifact = resolve_db_schema_artifact(
                {"REMOTE_TMP_ROOT": REMOTE_TMP_ROOT},
                TEST_BUILD_VERSION,
                release_dir,
            )

            self.assertEqual(artifact.local_path, artifact_path)
            self.assertEqual(artifact.remote_archive, REMOTE_DB_SCHEMA_ARCHIVE)
            self.assertEqual(artifact.remote_extract_path, REMOTE_DB_SCHEMA_DIR)
            self.assertEqual(artifact.entrypoint_dir, ".")
            self.assertEqual(artifact.entrypoint_pattern, "summary_sql_dev_*.sql")

    def test_resolve_db_data_artifact_insert_update_and_set_default(self):
        """Фиксирует remote paths и entrypoint patterns для data SQL архивов."""
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            insert_path = release_dir / f"db_insert_r_{TEST_BUILD_VERSION}-c_{TEST_BACKEND_COMMIT}.tar.gz"
            update_path = release_dir / f"db_update_parallel_r_{TEST_BUILD_VERSION}-c_{TEST_BACKEND_COMMIT}.tar.gz"
            set_default_path = release_dir / (
                f"db_set_default_parallel_r_{TEST_BUILD_VERSION}-c_{TEST_BACKEND_COMMIT}.tar.gz"
            )
            insert_path.write_text("", encoding="utf-8")
            update_path.write_text("", encoding="utf-8")
            set_default_path.write_text("", encoding="utf-8")

            insert = resolve_db_data_artifact({"REMOTE_TMP_ROOT": REMOTE_TMP_ROOT}, TEST_BUILD_VERSION, release_dir, "insert")
            update = resolve_db_data_artifact(
                {"REMOTE_TMP_ROOT": REMOTE_TMP_ROOT},
                TEST_BUILD_VERSION,
                release_dir,
                "update_parallel",
            )
            set_default = resolve_db_data_artifact(
                {"REMOTE_TMP_ROOT": REMOTE_TMP_ROOT},
                TEST_BUILD_VERSION,
                release_dir,
                "set_default_parallel",
            )

        self.assertEqual(insert.local_path, insert_path)
        self.assertEqual(insert.remote_archive, REMOTE_DB_INSERT_ARCHIVE)
        self.assertEqual(insert.remote_extract_path, REMOTE_DB_INSERT_DIR)
        self.assertEqual(insert.entrypoint_pattern, "run_all_insert_*.sql")
        self.assertEqual(update.local_path, update_path)
        self.assertEqual(update.remote_archive, REMOTE_DB_UPDATE_PARALLEL_ARCHIVE)
        self.assertEqual(update.remote_extract_path, REMOTE_DB_UPDATE_PARALLEL_DIR)
        self.assertEqual(update.entrypoint_pattern, "run_all_update_parallel_*.sh")
        self.assertEqual(set_default.local_path, set_default_path)
        self.assertEqual(
            set_default.remote_archive,
            REMOTE_DB_SET_DEFAULT_PARALLEL_ARCHIVE,
        )
        self.assertEqual(
            set_default.remote_extract_path,
            REMOTE_DB_SET_DEFAULT_PARALLEL_DIR,
        )
        self.assertEqual(
            set_default.entrypoint_pattern,
            "run_all_set_default_parallel_*.sh",
        )

    def test_resolve_maintenance_stub_uses_fixed_archive_path(self):
        """Проверяет, что maintenance stub берется из фиксированного локального архива."""
        with tempfile.TemporaryDirectory() as tmp:
            stub_path = Path(tmp) / "maintenance_stub.tar.gz"
            stub_path.write_text("", encoding="utf-8")
            artifact = resolve_maintenance_stub_artifact(
                {
                    "REMOTE_TMP_ROOT": REMOTE_TMP_ROOT,
                    "FRONTEND_RELEASE_PATH": FRONTEND_RELEASE_PATH,
                },
                {"maintenance_stub_archive_path": str(stub_path)},
                TEST_BUILD_VERSION,
            )

        self.assertEqual(artifact.name, "maintenance_stub")
        self.assertEqual(artifact.local_path, stub_path)
        self.assertEqual(artifact.remote_archive, REMOTE_MAINTENANCE_STUB_ARCHIVE)
        self.assertEqual(artifact.extract_path, FRONTEND_RELEASE_PATH)

    def test_check_maintenance_stub_archive_fails_before_deploy_when_missing(self):
        """Гарантирует preflight-ошибку, если включенный maintenance stub не собран."""
        reporter = Reporter()

        check_maintenance_stub_archive(
            reporter,
            {
                "maintenance_stub_enabled": True,
                "maintenance_stub_archive_path": str(MISSING_MAINTENANCE_STUB_ARCHIVE),
            },
        )

        self.assertTrue(any("maintenance stub archive" in issue for issue in reporter.issues))

    def test_verify_maintenance_stub_http_accepts_marker(self):
        """Принимает maintenance страницу только при наличии ожидаемого marker."""
        env = {"DEV_DOMAIN": DEV_DOMAIN}
        runtime = {
            "maintenance_stub_verify_enabled": True,
            "maintenance_stub_verify_marker": "Плановые технические работы",
            "maintenance_stub_verify_retries": 1,
            "maintenance_stub_verify_delay": 1,
            "healthcheck_validate_certs": False,
        }

        with patch(
            "simple_deploy.processes.healthcheck.read_http_text",
            return_value="<html><h1>Плановые технические работы</h1></html>",
        ) as read_mock:
            verify_maintenance_stub_http(env, runtime)

        self.assertIn(f"https://{DEV_DOMAIN}/?simple_deploy_maintenance_check=", read_mock.call_args.args[0])

    def test_verify_maintenance_stub_http_rejects_main_content(self):
        """Отклоняет основной портал, если после unpack stub marker не найден."""
        env = {"DEV_DOMAIN": DEV_DOMAIN}
        runtime = {
            "maintenance_stub_verify_enabled": True,
            "maintenance_stub_verify_marker": "Плановые технические работы",
            "maintenance_stub_verify_retries": 1,
            "maintenance_stub_verify_delay": 1,
            "healthcheck_validate_certs": False,
        }

        with patch("simple_deploy.processes.healthcheck.read_http_text", return_value="<html><h1>Основной портал</h1></html>"):
            with self.assertRaisesRegex(RuntimeError, "maintenance stub HTTP check failed"):
                verify_maintenance_stub_http(env, runtime)

    def test_scp_file_uses_requested_scope(self):
        """Фиксирует, что scp берет SSH key по переданному scope, а не по умолчанию."""
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "db_schema.tar.gz"
            local_path.write_text("", encoding="utf-8")

            with patch("simple_deploy.core.ssh.ssh_key_args", return_value=["DB_KEY"]) as key_mock:
                with patch(
                    "simple_deploy.core.ssh.run_command",
                    return_value=CommandResult(0, "", ""),
                ) as run_mock:
                    scp_file({}, local_path, "db-user", "db.example.local", "/tmp/db_schema.tar.gz", scope="DB")

            key_mock.assert_called_once_with({}, "DB")
            command = run_mock.call_args.args[0]
            self.assertIn("DB_KEY", command)
            self.assertIn("db-user@db.example.local:/tmp/db_schema.tar.gz", command)

    def test_ansible_schema_migration_uses_single_transaction(self):
        """Сохраняет legacy Ansible schema migration в single-transaction режиме."""
        content = LEGACY_DB_MIGRATIONS_TASKS.read_text(encoding="utf-8")

        self.assertIn("--set=ON_ERROR_STOP=1 --single-transaction", content)
