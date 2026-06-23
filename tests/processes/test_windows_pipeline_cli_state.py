"""Tests for WindowsPipelineCliStateTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineCliStateTests(WindowsPipelineTestCase):

    def test_parse_args_preserves_public_cli_contract_for_all_commands(self):
        """Фиксирует публичные CLI flags для всех process entrypoints."""
        cases = [
            (
                ["dry-run", "--app-only", "--skip-data-sql-artifacts"],
                {
                    "command": "dry-run",
                    "app_only": True,
                    "skip_data_sql_artifacts": True,
                    "include_data_sql": False,
                },
            ),
            (
                ["build", "--skip-data-sql-artifacts"],
                {
                    "command": "build",
                    "skip_data_sql_artifacts": True,
                    "include_data_sql": False,
                },
            ),
            (
                ["deploy", "--latest", "--contour", "test", "--include-set-default-sql", "--app-only"],
                {
                    "command": "deploy",
                    "latest": True,
                    "build_version": "",
                    "contour": "test",
                    "include_set_default_sql": True,
                    "app_only": True,
                },
            ),
            (
                ["pipeline", "--contour", "prod", "--include-set-default-sql", "--skip-data-sql-artifacts"],
                {
                    "command": "pipeline",
                    "contour": "prod",
                    "include_set_default_sql": True,
                    "skip_data_sql_artifacts": True,
                    "app_only": False,
                },
            ),
            (
                ["set-baseline", "--contour", "test", "--backend-commit", TEST_BACKEND_COMMIT],
                {
                    "command": "set-baseline",
                    "contour": "test",
                    "build_version": "",
                    "backend_commit": TEST_BACKEND_COMMIT,
                },
            ),
            (
                ["mark-applied", "--contour", "prod", "--build-version", TEST_BUILD_VERSION],
                {
                    "command": "mark-applied",
                    "contour": "prod",
                    "build_version": TEST_BUILD_VERSION,
                },
            ),
            (
                ["mark-failed", "--contour", "test", "--build-version", TEST_BUILD_VERSION, "--error", "sql failed"],
                {
                    "command": "mark-failed",
                    "contour": "test",
                    "build_version": TEST_BUILD_VERSION,
                    "error": "sql failed",
                },
            ),
        ]

        for command_args, expected_values in cases:
            argv = ["windows_pipeline.py", "--timeout", "77", *command_args]
            with self.subTest(command=command_args[0]):
                with patch.object(sys, "argv", argv):
                    args = parse_args()

                self.assertEqual(args.timeout, 77)
                for name, expected in expected_values.items():
                    self.assertEqual(getattr(args, name), expected)

    def test_main_dispatches_all_public_commands_inside_tee_output(self):
        """Фиксирует соответствие CLI command -> process function в main()."""
        cases = [
            ("dry-run", "dry_run", True, 0),
            ("build", "build", 3, 3),
            ("deploy", "deploy", 4, 4),
            ("pipeline", "pipeline", 5, 5),
            ("set-baseline", "set_baseline", 0, 0),
            ("mark-applied", "mark_applied", 0, 0),
            ("mark-failed", "mark_failed", 0, 0),
        ]

        for command, function_name, function_result, expected_rc in cases:
            args = Namespace(command=command)
            request = sentinel.request
            with self.subTest(command=command):
                with ExitStack() as stack:
                    stack.enter_context(
                        patch(
                            "simple_deploy.cli.windows_pipeline.parse_args",
                            return_value=args,
                        )
                    )
                    request_mock = stack.enter_context(
                        patch(
                            "simple_deploy.cli.windows_pipeline.request_from_args",
                            return_value=request,
                        )
                    )
                    tee_mock = stack.enter_context(
                        patch(
                            "simple_deploy.cli.windows_pipeline.tee_output",
                            return_value=nullcontext(),
                        )
                    )
                    process_mock = stack.enter_context(
                        patch(
                            "simple_deploy.cli.windows_pipeline."
                            f"{function_name}",
                            return_value=function_result,
                        )
                    )

                    self.assertEqual(main(), expected_rc)

                request_mock.assert_called_once_with(args)
                tee_mock.assert_called_once_with(command)
                process_mock.assert_called_once_with(request)

    def test_main_returns_one_when_process_raises(self):
        """Фиксирует, что main преобразует исключение process function в rc=1."""
        args = Namespace(command="build")
        request = sentinel.request

        with patch(
            "simple_deploy.cli.windows_pipeline.parse_args",
            return_value=args,
        ):
            with patch(
                "simple_deploy.cli.windows_pipeline.tee_output",
                return_value=nullcontext(),
            ):
                with patch(
                    "simple_deploy.cli.windows_pipeline.request_from_args",
                    return_value=request,
                ):
                    with patch(
                        "simple_deploy.cli.windows_pipeline.build",
                        side_effect=RuntimeError("build failed"),
                    ):
                        self.assertEqual(main(), 1)

    def test_pipeline_preserves_app_only_for_deploy(self):
        """Фиксирует, что pipeline передает app-only в deploy после dry-run/build."""
        request = PipelineRequest(
            timeout=3600,
            contour=ContourCodeEnum.DEV,
            skip_data_sql_artifacts=False,
            app_only=True,
        )

        with patch(
            "simple_deploy.application.services._dry_run_process",
            return_value=ProcessResult.success("dry-run ok"),
        ):
            with patch(
                "simple_deploy.application.services._build_process",
                return_value=ProcessResult.success("build ok"),
            ):
                with patch(
                    "simple_deploy.application.services._deploy_process",
                    return_value=ProcessResult.success("deploy ok"),
                ) as deploy_mock:
                    self.assertEqual(pipeline(request), 0)

        deploy_args = deploy_mock.call_args.args[0]
        self.assertTrue(deploy_args.app_only)
        self.assertTrue(deploy_args.latest)
        self.assertEqual(deploy_args.build_version, "")

    def test_pipeline_uses_data_sql_artifacts_by_default_without_runtime_mutation(self):
        """Проверяет, что pipeline сохраняет data SQL defaults в DTO."""
        request = PipelineRequest(
            timeout=3600,
            contour=ContourCodeEnum.DEV,
            skip_data_sql_artifacts=False,
            app_only=False,
        )

        with patch(
            "simple_deploy.config.runtime_loader.load_runtime_config"
        ) as load_runtime_mock:
            with patch(
                "simple_deploy.application.services._dry_run_process",
                return_value=ProcessResult.success("dry-run ok"),
            ) as dry_run_mock:
                with patch(
                    "simple_deploy.application.services._build_process",
                    return_value=ProcessResult.success("build ok"),
                ) as build_mock:
                    with patch(
                        "simple_deploy.application.services._deploy_process",
                        return_value=ProcessResult.success("deploy ok"),
                    ):
                        self.assertEqual(pipeline(request), 0)

        load_runtime_mock.assert_not_called()
        self.assertFalse(hasattr(dry_run_mock.call_args.args[0], "include_data_sql"))
        self.assertFalse(hasattr(build_mock.call_args.args[0], "include_data_sql"))
        self.assertFalse(dry_run_mock.call_args.args[0].skip_data_sql_artifacts)
        self.assertFalse(build_mock.call_args.args[0].skip_data_sql_artifacts)

    def test_set_baseline_with_backend_commit_moves_baseline_without_attempt(self):
        """set-baseline с commit двигает baseline и не пишет deployment attempt."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            contour="test",
            build_version="",
            backend_commit=TEST_BACKEND_COMMIT,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with patch("simple_deploy.processes.mark.load_env", return_value={}) as load_env_mock:
                    self.assertEqual(set_baseline(args), 0)

                with closing(connect_state_db(db_path)) as connection:
                    state = get_contour_state(connection, "test")
                    attempts = list_deployment_attempts(connection, contour="test")

        load_env_mock.assert_called_once_with(DEFAULT_ENV_FILE, DEFAULT_SECRETS_FILE, require_secrets=False)
        self.assertEqual(state.last_success_release, "manual-baseline")
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts, [])

    def test_set_baseline_with_build_version_uses_registry_commit(self):
        """set-baseline by build version reads backend commit from registry."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            contour="test",
            build_version=TEST_BUILD_VERSION,
            backend_commit="",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "state.sqlite3"
            release_root = root / "releases"
            env = {"RELEASE_ROOT_WINDOWS": str(release_root)}
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with closing(connect_state_db(db_path)) as connection:
                    record_release(
                        connection,
                        TEST_BUILD_VERSION,
                        TEST_BACKEND_COMMIT,
                        TEST_FRONTEND_COMMIT,
                        {"backend": "backend.tar.gz"},
                    )
                with patch("simple_deploy.processes.mark.load_env", return_value=env):
                    self.assertEqual(set_baseline(args), 0)

                with closing(connect_state_db(db_path)) as connection:
                    state = get_contour_state(connection, "test")
                    attempts = list_deployment_attempts(connection, contour="test")

        self.assertEqual(state.last_success_release, TEST_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts, [])

    def test_set_baseline_without_build_version_uses_initial_config(self):
        """set-baseline without build/commit reads runtime bootstrap baseline."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "state.sqlite3"
            config_file = root / "windows_pipeline.local.json"
            config_file.write_text(
                json.dumps(
                    {
                        "initial_schema_baselines": {
                            "prod": {
                                "build_version": "bootstrap-prod",
                                "backend_commit": TEST_BACKEND_COMMIT,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            args = Namespace(
                env_file=DEFAULT_ENV_FILE,
                secrets_file=DEFAULT_SECRETS_FILE,
                config_file=config_file,
                contour="prod",
                build_version="",
                backend_commit="",
            )

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with patch("simple_deploy.processes.mark.load_env", return_value={}):
                    self.assertEqual(set_baseline(args), 0)

                with closing(connect_state_db(db_path)) as connection:
                    state = get_contour_state(connection, "prod")
                    attempts = list_deployment_attempts(connection, contour="prod")

        self.assertEqual(state.last_success_release, "bootstrap-prod")
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts, [])

    def test_mark_applied_moves_baseline_and_records_success_attempt(self):
        """mark-applied читает manifest, двигает baseline и пишет success attempt."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            contour="test",
            build_version=TEST_BUILD_VERSION,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "state.sqlite3"
            release_root = root / "releases"
            release_dir = release_root / TEST_BUILD_VERSION
            self._write_release_manifest(release_dir)
            env = {"RELEASE_ROOT_WINDOWS": str(release_root)}

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with patch("simple_deploy.processes.mark.load_env", return_value=env):
                    self.assertEqual(mark_applied(args), 0)

                with closing(connect_state_db(db_path)) as connection:
                    state = get_contour_state(connection, "test")
                    attempts = list_deployment_attempts(connection, contour="test")

        self.assertEqual(state.last_success_release, TEST_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(attempts[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["status"], "success")
        self.assertEqual(attempts[0]["error"], "")

    def test_mark_failed_records_failed_attempt_without_moving_baseline(self):
        """mark-failed пишет failed attempt, но не меняет существующий baseline."""
        args = Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            contour="prod",
            build_version=TEST_BUILD_VERSION,
            error="operator rejected",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "state.sqlite3"
            release_root = root / "releases"
            release_dir = release_root / TEST_BUILD_VERSION
            self._write_release_manifest(release_dir)
            env = {"RELEASE_ROOT_WINDOWS": str(release_root)}
            with closing(connect_state_db(db_path)) as connection:
                upsert_contour_state(connection, "prod", PREVIOUS_BUILD_VERSION, PREVIOUS_BACKEND_COMMIT)

            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}, clear=True):
                with patch("simple_deploy.processes.mark.load_env", return_value=env):
                    self.assertEqual(mark_failed(args), 0)

                with closing(connect_state_db(db_path)) as connection:
                    state = get_contour_state(connection, "prod")
                    attempts = list_deployment_attempts(connection, contour="prod")

        self.assertEqual(state.last_success_release, PREVIOUS_BUILD_VERSION)
        self.assertEqual(state.last_success_backend_commit, PREVIOUS_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(attempts[0]["backend_commit"], TEST_BACKEND_COMMIT)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertEqual(attempts[0]["error"], "operator rejected")
