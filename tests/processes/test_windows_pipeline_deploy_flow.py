"""Tests for WindowsPipelineDeployFlowTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineDeployFlowTests(WindowsPipelineTestCase):

    def test_deploy_failure_records_failed_attempt(self):
        """Фиксирует запись failed deploy attempt при ошибке до state success."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
        )
        env = {"DEV_DOMAIN": DEV_DOMAIN}
        release_dir = Path("releases") / TEST_BUILD_VERSION

        with patch("simple_deploy.processes.deploy.load_env", return_value=env):
            with patch("simple_deploy.processes.deploy.load_runtime_config", return_value=({}, [])):
                with patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)):
                    with patch(
                        "simple_deploy.processes.deploy.resolve_artifacts",
                        side_effect=RuntimeError("artifact missing"),
                    ):
                        with patch("simple_deploy.processes.mark.mark_contour_failed") as mark_failed_mock:
                            with self.assertRaisesRegex(RuntimeError, "artifact missing"):
                                deploy(args)

        mark_failed_mock.assert_called_once_with("dev", TEST_BUILD_VERSION, release_dir, "artifact missing")

    def test_deploy_app_only_skips_db_steps(self):
        """Проверяет, что app-only deploy не выполняет DB cleanup/schema/maintenance."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
            app_only=True,
        )
        env = {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
            "APP_WORKDIR": APP_WORKDIR,
            "APP_VENV_ACTIVATE_PATH": APP_VENV_ACTIVATE_PATH,
            "REMOTE_TMP_ROOT": REMOTE_TMP_ROOT,
            "DEV_DOMAIN": DEV_DOMAIN,
        }
        runtime = {"service_steps": [], "healthcheck_enabled": True}
        release_dir = Path("releases") / TEST_BUILD_VERSION
        artifact = Artifact(
            "backend",
            Path("backend.tar.gz"),
            REMOTE_BACKEND_ARCHIVE,
            BACKEND_RELEASE_PATH,
        )

        with ExitStack() as stack:
            load_env_mock = stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[artifact]))
            cleanup_mock = stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            resolve_db_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact"))
            db_maintenance_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            db_schema_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            service_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(
                patch("simple_deploy.processes.deploy.management_commands", return_value=["python manage.py migrate --fake"])
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.ssh_command", return_value=CommandResult(0, "", "")))
            healthcheck_mock = stack.enter_context(patch("simple_deploy.processes.deploy.healthcheck"))
            mark_applied_mock = stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        load_env_mock.assert_called_once_with(args.env_file, args.secrets_file, require_secrets=False)
        cleanup_mock.assert_not_called()
        resolve_db_mock.assert_not_called()
        db_maintenance_mock.assert_not_called()
        db_schema_mock.assert_not_called()
        self.assertEqual(
            [call.args[2] for call in service_mock.call_args_list],
            ["before_unpack", "after_unpack", "after_migrate"],
        )
        healthcheck_mock.assert_called_once()
        mark_applied_mock.assert_called_once_with("dev", TEST_BUILD_VERSION, release_dir)

    def test_deploy_full_skips_data_sql_when_runtime_disabled(self):
        """При data_sql_enabled=false full deploy выполняет schema SQL и пропускает data SQL."""
        args = self._deploy_args()
        args.include_data_migration_sql = True
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": False,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            resolve_data_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_data_artifact"))
            resolve_stub_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact"))
            upload_mock = stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            db_schema_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            db_insert_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_insert"))
            db_update_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_update_parallel"))
            db_set_default_mock = stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_data_set_default_parallel")
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            mark_mock = stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        resolve_data_mock.assert_not_called()
        resolve_stub_mock.assert_not_called()
        db_schema_mock.assert_called_once_with(env, runtime, db_schema)
        db_insert_mock.assert_not_called()
        db_update_mock.assert_not_called()
        db_set_default_mock.assert_not_called()
        upload_mock.assert_called_once_with(env, [backend, frontend], REMOTE_RELEASE_ROOT)
        mark_mock.assert_called_once_with("dev", TEST_BUILD_VERSION, release_dir)

    def test_deploy_full_skips_data_sql_by_default(self):
        """Full deploy без --include-data-migration-sql выполняет schema SQL и пропускает data SQL."""
        args = self._deploy_args()
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": True,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            resolve_data_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_data_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            db_schema_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            db_insert_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_insert"))
            db_update_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_update_parallel"))
            db_set_default_mock = stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_data_set_default_parallel")
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        resolve_data_mock.assert_not_called()
        db_schema_mock.assert_called_once_with(env, runtime, db_schema)
        db_insert_mock.assert_not_called()
        db_update_mock.assert_not_called()
        db_set_default_mock.assert_not_called()

    def test_deploy_full_skips_maintenance_stub_when_runtime_disabled(self):
        """При maintenance_stub_enabled=false deploy не resolve/unpack/verify stub."""
        args = self._deploy_args()
        args.include_data_migration_sql = True
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": True,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")
        db_insert = DbSqlArtifact("db_insert", Path("insert.tar.gz"), "", "", ".", "run_all_insert_*.sql")
        db_update = DbSqlArtifact("db_update_parallel", Path("update.tar.gz"), "", "", ".", "run_all_update_parallel_*.sh")

        def data_artifact_side_effect(_env, _build_version, _release_dir, kind):
            return {"insert": db_insert, "update_parallel": db_update}[kind]

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_data_artifact", side_effect=data_artifact_side_effect))
            resolve_stub_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact"))
            verify_stub_mock = stack.enter_context(patch("simple_deploy.processes.deploy.verify_maintenance_stub_http"))
            upload_mock = stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            unpack_mock = stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            db_insert_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_insert"))
            db_update_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_update_parallel"))
            db_set_default_mock = stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_data_set_default_parallel")
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        resolve_stub_mock.assert_not_called()
        verify_stub_mock.assert_not_called()
        upload_mock.assert_called_once_with(env, [backend, frontend], REMOTE_RELEASE_ROOT)
        self.assertNotIn("maintenance_stub", [call.args[1].name for call in unpack_mock.call_args_list])
        db_insert_mock.assert_called_once_with(env, runtime, db_insert)
        db_update_mock.assert_called_once_with(env, runtime, db_update)
        db_set_default_mock.assert_not_called()

    def test_deploy_full_runs_set_default_as_separate_step_when_requested(self):
        """--include-set-default-sql добавляет отдельный set_default step после update."""
        args = self._deploy_args()
        args.include_data_migration_sql = True
        args.include_set_default_sql = True
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": True,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")
        db_insert = DbSqlArtifact("db_insert", Path("insert.tar.gz"), "", "", ".", "run_all_insert_*.sql")
        db_update = DbSqlArtifact("db_update_parallel", Path("update.tar.gz"), "", "", ".", "run_all_update_parallel_*.sh")
        db_set_default = DbSqlArtifact(
            "db_set_default_parallel",
            Path("set_default.tar.gz"),
            "",
            "",
            ".",
            "run_all_set_default_parallel_*.sh",
        )
        events = []

        def data_artifact_side_effect(_env, _build_version, _release_dir, kind):
            return {
                "insert": db_insert,
                "update_parallel": db_update,
                "set_default_parallel": db_set_default,
            }[kind]

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            resolve_data_mock = stack.enter_context(
                patch("simple_deploy.processes.deploy.resolve_db_data_artifact", side_effect=data_artifact_side_effect)
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_insert"))
            stack.enter_context(
                patch(
                    "simple_deploy.processes.deploy.run_db_data_update_parallel",
                    side_effect=lambda *_args: events.append("update"),
                )
            )
            set_default_mock = stack.enter_context(
                patch(
                    "simple_deploy.processes.deploy.run_db_data_set_default_parallel",
                    side_effect=lambda *_args: events.append("set_default"),
                )
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        self.assertEqual(
            [call.args[3] for call in resolve_data_mock.call_args_list],
            ["insert", "update_parallel", "set_default_parallel"],
        )
        self.assertEqual(events, ["update", "set_default"])
        set_default_mock.assert_called_once_with(env, runtime, db_set_default)

    def test_deploy_set_default_requires_data_migration_sql(self):
        """--include-set-default-sql без --include-data-migration-sql не запускает data SQL."""
        args = self._deploy_args()
        args.include_set_default_sql = True
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": False,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": True,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            resolve_data_mock = stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_data_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            db_insert_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_insert"))
            db_update_mock = stack.enter_context(patch("simple_deploy.processes.deploy.run_db_data_update_parallel"))
            db_set_default_mock = stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_data_set_default_parallel")
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        resolve_data_mock.assert_not_called()
        db_insert_mock.assert_not_called()
        db_update_mock.assert_not_called()
        db_set_default_mock.assert_not_called()

    def test_successful_deploy_marks_state_after_healthcheck_before_email(self):
        """Фиксирует текущий порядок success side effects: healthcheck, mark, email."""
        args = self._deploy_args()
        env = self._deploy_env()
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": True,
            "maintenance_stub_enabled": False,
            "data_sql_enabled": False,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend, frontend = self._app_artifacts()
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")
        events = []

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.cleanup_db_data_update_leftovers"))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            stack.enter_context(patch("simple_deploy.processes.deploy.upload_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.backup_app_artifacts"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps"))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_schema_summary"))
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance"))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=[]))
            stack.enter_context(patch("simple_deploy.processes.deploy.healthcheck", side_effect=lambda *_args: events.append("healthcheck")))
            stack.enter_context(
                patch("simple_deploy.processes.deploy.mark_contour_applied", side_effect=lambda *_args: events.append("mark"))
            )
            stack.enter_context(
                patch("simple_deploy.processes.deploy.send_outlook_success_email", side_effect=lambda *_args: events.append("email"))
            )

            self.assertEqual(deploy(args), 0)

        self.assertEqual(events, ["healthcheck", "mark", "email"])

    def test_deploy_full_keeps_frontend_stub_until_backend_is_started(self):
        """Фиксирует порядок full deploy: stub держится до запуска backend и frontend unpack."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
            include_data_migration_sql=True,
            include_set_default_sql=False,
            app_only=False,
        )
        env = {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
            "APP_WORKDIR": APP_WORKDIR,
            "APP_VENV_ACTIVATE_PATH": APP_VENV_ACTIVATE_PATH,
            "REMOTE_TMP_ROOT": REMOTE_TMP_ROOT,
            "DEV_DOMAIN": DEV_DOMAIN,
        }
        runtime = {
            "service_steps": [],
            "healthcheck_enabled": True,
            "maintenance_stub_enabled": True,
            "data_sql_enabled": True,
        }
        release_dir = Path("releases") / TEST_BUILD_VERSION
        backend = Artifact("backend", Path("backend.tar.gz"), REMOTE_BACKEND_ARCHIVE, BACKEND_RELEASE_PATH)
        frontend = Artifact(
            "frontend",
            Path("frontend.tar.gz"),
            REMOTE_FRONTEND_ARCHIVE,
            FRONTEND_RELEASE_PATH,
        )
        stub = Artifact(
            "maintenance_stub",
            Path("maintenance_stub.tar.gz"),
            REMOTE_MAINTENANCE_STUB_ARCHIVE,
            FRONTEND_RELEASE_PATH,
        )
        db_schema = DbSqlArtifact("db_schema_dev", Path("schema.tar.gz"), "", "", ".", "summary_sql_dev_*.sql")
        db_insert = DbSqlArtifact("db_insert", Path("insert.tar.gz"), "", "", ".", "run_all_insert_*.sql")
        db_update = DbSqlArtifact(
            "db_update_parallel",
            Path("update.tar.gz"),
            "",
            "",
            ".",
            "run_all_update_parallel_*.sh",
        )
        events = []

        def service_side_effect(_env, _runtime, phase):
            events.append(f"service:{phase}")

        def unpack_side_effect(_env, artifact):
            events.append(f"unpack:{artifact.name}")

        def maintenance_side_effect(_env, _runtime, phase):
            events.append(f"maintenance:{phase}")

        def data_artifact_side_effect(_env, _build_version, _release_dir, kind):
            return {"insert": db_insert, "update_parallel": db_update}[kind]

        with ExitStack() as stack:
            stack.enter_context(patch("simple_deploy.processes.deploy.load_env", return_value=env))
            stack.enter_context(patch("simple_deploy.processes.deploy.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_artifacts", return_value=[backend, frontend]))
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_db_schema_artifact", return_value=db_schema))
            stack.enter_context(
                patch("simple_deploy.processes.deploy.resolve_db_data_artifact", side_effect=data_artifact_side_effect)
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.resolve_maintenance_stub_artifact", return_value=stub))
            stack.enter_context(
                patch(
                    "simple_deploy.processes.deploy.cleanup_db_data_update_leftovers",
                    side_effect=lambda *_args: events.append("cleanup:update"),
                )
            )
            stack.enter_context(
                patch("simple_deploy.processes.deploy.upload_app_artifacts", side_effect=lambda *_args: events.append("upload"))
            )
            stack.enter_context(
                patch("simple_deploy.processes.deploy.backup_app_artifacts", side_effect=lambda *_args: events.append("backup"))
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_service_steps", side_effect=service_side_effect))
            stack.enter_context(patch("simple_deploy.processes.deploy.unpack_app_artifact", side_effect=unpack_side_effect))
            stack.enter_context(
                patch("simple_deploy.processes.deploy.verify_maintenance_stub_http", side_effect=lambda *_args: events.append("stub:http"))
            )
            stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_schema_summary", side_effect=lambda *_args: events.append("db:schema"))
            )
            stack.enter_context(
                patch("simple_deploy.processes.deploy.run_db_data_insert", side_effect=lambda *_args: events.append("db:insert"))
            )
            stack.enter_context(
                patch(
                    "simple_deploy.processes.deploy.run_db_data_update_parallel",
                    side_effect=lambda *_args, **_kwargs: events.append("db:update_parallel"),
                )
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.run_db_maintenance", side_effect=maintenance_side_effect))
            stack.enter_context(patch("simple_deploy.processes.deploy.management_commands", return_value=["python manage.py migrate"]))
            stack.enter_context(
                patch(
                    "simple_deploy.processes.deploy.ssh_command",
                    side_effect=lambda *_args, **_kwargs: events.append("management") or CommandResult(0, "", ""),
                )
            )
            stack.enter_context(patch("simple_deploy.processes.deploy.healthcheck", side_effect=lambda *_args: events.append("healthcheck")))
            stack.enter_context(patch("simple_deploy.processes.deploy.mark_contour_applied"))
            stack.enter_context(patch("simple_deploy.processes.deploy.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        self.assertLess(events.index("cleanup:update"), events.index("upload"))
        self.assertLess(events.index("service:before_unpack"), events.index("unpack:maintenance_stub"))
        self.assertLess(events.index("unpack:maintenance_stub"), events.index("db:schema"))
        self.assertLess(events.index("unpack:maintenance_stub"), events.index("stub:http"))
        self.assertLess(events.index("stub:http"), events.index("db:schema"))
        self.assertLess(events.index("db:schema"), events.index("db:insert"))
        self.assertLess(events.index("db:insert"), events.index("db:update_parallel"))
        self.assertLess(events.index("db:update_parallel"), events.index("unpack:backend"))
        self.assertLess(events.index("unpack:backend"), events.index("service:after_unpack"))
        self.assertLess(events.index("service:after_unpack"), events.index("management"))
        self.assertLess(events.index("management"), events.index("service:after_migrate"))
        self.assertLess(events.index("service:after_migrate"), events.index("unpack:frontend"))
        self.assertLess(events.index("unpack:frontend"), events.index("service:after_frontend_unpack"))
        self.assertLess(events.index("service:after_frontend_unpack"), events.index("healthcheck"))
        self.assertLess(events.index("unpack:frontend"), events.index("healthcheck"))

    def test_deploy_failure_record_error_preserves_original_error(self):
        """Не затирает исходную deploy ошибку ошибкой best-effort записи failed state."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
        )
        release_dir = Path("releases") / TEST_BUILD_VERSION

        with patch("simple_deploy.processes.deploy.load_env", return_value={}):
            with patch("simple_deploy.processes.deploy.load_runtime_config", return_value=({}, [])):
                with patch("simple_deploy.processes.deploy.resolve_release_dir", return_value=(TEST_BUILD_VERSION, release_dir)):
                    with patch(
                        "simple_deploy.processes.deploy.resolve_artifacts",
                        side_effect=RuntimeError("artifact missing"),
                    ):
                        with patch(
                            "simple_deploy.processes.mark.mark_contour_failed",
                            side_effect=RuntimeError("sqlite error"),
                        ):
                            with self.assertRaisesRegex(RuntimeError, "artifact missing"):
                                deploy(args)
