"""Tests for WindowsPipelineDbSqlTests."""

# ruff: noqa: F401,F403,F405

from windows_pipeline_test_support import *  # noqa: F401,F403


class WindowsPipelineDbSqlTests(WindowsPipelineTestCase):

    def test_run_db_schema_summary_uses_single_transaction(self):
        """Фиксирует запуск schema summary через psql в одной транзакции."""
        artifact = DbSqlArtifact(
            name="db_schema_dev",
            local_path=Path("db_schema_dev.tar.gz"),
            remote_archive=REMOTE_DB_SCHEMA_ARCHIVE,
            remote_extract_path=REMOTE_DB_SCHEMA_DIR,
            entrypoint_dir=".",
            entrypoint_pattern="summary_sql_dev_*.sql",
        )
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }

        with patch("simple_deploy.processes.data_sql.scp_file", return_value=CommandResult(0, "", "")):
            with patch("simple_deploy.processes.data_sql.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
                run_db_schema_summary(env, {}, artifact)

        final_command = ssh_mock.call_args_list[-1].args[3]
        self.assertIn("--set=ON_ERROR_STOP=1", final_command)
        self.assertIn("--single-transaction", final_command)
        self.assertIn('-f "$sql_file"', final_command)

    def test_run_db_data_insert_uses_psql_file_and_data_timeout(self):
        """Проверяет запуск data INSERT через psql file и отдельный долгий timeout."""
        artifact = DbSqlArtifact(
            name="db_insert",
            local_path=Path("db_insert.tar.gz"),
            remote_archive=REMOTE_DB_INSERT_ARCHIVE,
            remote_extract_path=REMOTE_DB_INSERT_DIR,
            entrypoint_dir=".",
            entrypoint_pattern="run_all_insert_*.sql",
        )
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }
        runtime = {"db_data_sql_timeout_seconds": 21600}

        with patch("simple_deploy.processes.data_sql.upload_unpack_db_sql_artifact"):
            with patch(
                "simple_deploy.processes.data_sql.ssh_command",
                return_value=CommandResult(0, "DB data insert SQL completed in 26s\n", ""),
            ) as ssh_mock:
                with patch("builtins.print") as print_mock:
                    run_db_data_insert(env, runtime, artifact)

        final_command = ssh_mock.call_args.args[3]
        self.assertIn("run_all_insert_*.sql", final_command)
        self.assertIn('-f "$sql_file"', final_command)
        self.assertIn('log_dir="logs/insert"', final_command)
        self.assertIn('> "$log_file" 2>&1', final_command)
        self.assertIn("tail -n 80", final_command)
        self.assertIn("DB data insert SQL completed in %ss", final_command)
        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 21600)
        printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("PASS DB data insert SQL completed in 26s", printed)
        self.assertNotIn("STDOUT DB data insert SQL", printed)

    def test_cleanup_db_data_update_leftovers_stops_processes_and_tagged_backends(self):
        """Фиксирует preflight cleanup зависших update runners и tagged DB sessions."""
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }
        runtime = {"db_psql_bin": "psql", "db_psql_host": "localhost"}

        with patch("simple_deploy.processes.data_sql.ssh_command", return_value=CommandResult(0, "ok\n", "")) as ssh_mock:
            cleanup_db_data_update_leftovers(env, runtime)

        process_call = ssh_mock.call_args_list[0]
        self.assertEqual(process_call.args[3], "bash -s")
        self.assertIn("command -v pgrep", process_call.kwargs["input_text"])
        self.assertIn(
            "run_all_(update|set_default)_parallel_",
            process_call.kwargs["input_text"],
        )
        self.assertIn("kill -TERM", process_call.kwargs["input_text"])
        self.assertIn("kill -KILL", process_call.kwargs["input_text"])
        self.assertEqual(process_call.kwargs["timeout"], 90)
        self.assertEqual(process_call.kwargs["mask"], ["secret"])

        backend_call = ssh_mock.call_args_list[1]
        backend_command = backend_call.args[3]
        self.assertIn("pg_terminate_backend", backend_command)
        self.assertIn("application_name =", backend_command)
        self.assertIn("simple-deploy-data-update", backend_command)
        self.assertIn("--tuples-only --no-align", backend_command)
        self.assertEqual(backend_call.kwargs["timeout"], 60)
        self.assertEqual(backend_call.kwargs["mask"], ["secret"])

    def test_run_db_data_update_parallel_streams_bash_runner_with_pg_env(self):
        """Проверяет streaming-запуск parallel update runner с PG env и маской пароля."""
        artifact = DbSqlArtifact(
            name="db_update_parallel",
            local_path=Path("db_update_parallel.tar.gz"),
            remote_archive=REMOTE_DB_UPDATE_PARALLEL_ARCHIVE,
            remote_extract_path=REMOTE_DB_UPDATE_PARALLEL_DIR,
            entrypoint_dir=".",
            entrypoint_pattern="run_all_update_parallel_*.sh",
        )
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }
        runtime = {
            "db_psql_bin": "psql",
            "db_psql_host": "localhost",
            "db_data_sql_timeout_seconds": 12345,
            "db_update_parallel_max_workers": 4,
            "db_update_parallel_status_interval_seconds": 15,
        }

        with patch("simple_deploy.processes.data_sql.upload_unpack_db_sql_artifact"):
            with patch("simple_deploy.processes.data_sql.stream_ssh_command", return_value=CommandResult(0, "", "")) as stream_mock:
                run_db_data_update_parallel(env, runtime, artifact)

        command = stream_mock.call_args.args[3]
        self.assertIn("run_all_update_parallel_*.sh", command)
        self.assertIn("PGHOST='localhost'", command)
        self.assertIn("PGPORT='5432'", command)
        self.assertIn("PGUSER='postgres'", command)
        self.assertIn("PGDATABASE='appdb'", command)
        self.assertIn("PGAPPNAME='simple-deploy-data-update'", command)
        self.assertIn("PSQL_BIN='psql'", command)
        self.assertIn("SIMPLE_DEPLOY_UPDATE_MAX_WORKERS='4'", command)
        self.assertIn("SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS='15'", command)
        self.assertNotIn("SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT", command)
        self.assertIn('bash "$runner"', command)
        self.assertEqual(stream_mock.call_args.kwargs["timeout"], 12345)
        self.assertEqual(stream_mock.call_args.kwargs["mask"], ["secret"])

    def test_run_db_data_set_default_parallel_streams_separate_runner(self):
        """Фиксирует отдельный streaming-запуск set_default runner-а."""
        artifact = DbSqlArtifact(
            name="db_set_default_parallel",
            local_path=Path("db_set_default_parallel.tar.gz"),
            remote_archive=REMOTE_DB_SET_DEFAULT_PARALLEL_ARCHIVE,
            remote_extract_path=REMOTE_DB_SET_DEFAULT_PARALLEL_DIR,
            entrypoint_dir=".",
            entrypoint_pattern="run_all_set_default_parallel_*.sh",
        )
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }

        with patch("simple_deploy.processes.data_sql.upload_unpack_db_sql_artifact"):
            with patch("simple_deploy.processes.data_sql.stream_ssh_command", return_value=CommandResult(0, "", "")) as stream_mock:
                run_db_data_set_default_parallel(env, {}, artifact)

        command = stream_mock.call_args.args[3]
        self.assertIn("run_all_set_default_parallel_*.sh", command)
        self.assertIn("PGAPPNAME='simple-deploy-data-update'", command)
        self.assertIn("SIMPLE_DEPLOY_UPDATE_MAX_WORKERS='8'", command)
        self.assertIn("SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS='30'", command)
        self.assertNotIn("SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT", command)
        self.assertIn('bash "$runner"', command)

    def test_run_db_maintenance_uses_configured_timeout(self):
        """Проверяет timeout для inline maintenance SQL на выбранной фазе."""
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }
        runtime = {
            "db_maintenance_sql_phase": "before_unpack",
            "db_maintenance_sql": ["VACUUM ANALYZE;"],
            "db_maintenance_sql_timeout_seconds": 900,
            "sql_scripts": [],
        }

        with patch("simple_deploy.processes.data_sql.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
            run_db_maintenance(env, runtime, "before_unpack")

        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 900)

    def test_run_db_maintenance_uses_timeout_for_sql_scripts(self):
        """Проверяет timeout для maintenance SQL scripts из runtime config."""
        env = {
            "DB_VM_USER": DB_VM_USER,
            "DB_VM_HOST": DB_VM_HOST,
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }
        runtime = {
            "db_maintenance_sql": [],
            "db_maintenance_sql_timeout_seconds": 900,
            "sql_scripts": [
                {
                    "path": "README.MD",
                    "phase": "before_unpack",
                }
            ],
        }

        with patch("simple_deploy.processes.data_sql.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
            run_db_maintenance(env, runtime, "before_unpack")

        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 900)
