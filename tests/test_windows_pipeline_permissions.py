import unittest
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
import sys
from argparse import Namespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools-ci"))

from tools.windows_pipeline import (
    Artifact,
    CommandResult,
    DbSqlArtifact,
    Reporter,
    build,
    check_backend_data_insert_idempotency,
    check_backend_build_inputs,
    check_runtime_config,
    check_service_permissions,
    check_ssh_runtime,
    deploy,
    derive_service_permission_check,
    is_sudo_command,
    load_runtime_config,
    management_commands,
    pipeline,
    prepare_build_env,
    resolve_db_schema_artifact,
    run_db_schema_summary,
    run_db_maintenance,
    scp_file,
    send_outlook_success_email,
    sudo_list_command,
)


class WindowsPipelinePermissionTests(unittest.TestCase):
    def test_reporter_warn_does_not_fail_result(self):
        reporter = Reporter()

        reporter.warn("runtime db_maintenance_sql_timeout_seconds", "missing; using default 900")

        self.assertEqual(reporter.issues, [])
        self.assertTrue(reporter.result())
        self.assertIn("runtime db_maintenance_sql_timeout_seconds", reporter.warnings[0])

    def test_default_management_commands_fake_migrations(self):
        commands = management_commands({"APP_MANAGE_PY_PATH": "manage.py"}, {"management_commands": []})

        self.assertEqual(
            commands,
            [
                "python 'manage.py' migrate --fake",
                "python 'manage.py' sync_action_role",
            ],
        )

    def test_derive_service_permission_check_keeps_sudo_command(self):
        command = "sudo /bin/systemctl restart nginx"

        self.assertEqual(derive_service_permission_check(command), command)

    def test_sudo_list_command_checks_payload_without_running_it(self):
        self.assertEqual(
            sudo_list_command("sudo /bin/systemctl restart nginx"),
            "sudo -n -l '/bin/systemctl' 'restart' 'nginx'",
        )

    def test_sudo_list_command_strips_sudo_options(self):
        self.assertEqual(
            sudo_list_command("sudo -n -u root /bin/systemctl start example-backend"),
            "sudo -n -l '/bin/systemctl' 'start' 'example-backend'",
        )

    def test_is_sudo_command(self):
        self.assertTrue(is_sudo_command("sudo /bin/systemctl restart nginx"))
        self.assertFalse(is_sudo_command("/bin/systemctl restart nginx"))

    def test_resolve_db_schema_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            artifact_path = release_dir / "db_schema_dev_r_1.2.3-c_abc123.tar.gz"
            artifact_path.write_text("", encoding="utf-8")

            artifact = resolve_db_schema_artifact(
                {"REMOTE_TMP_ROOT": "/tmp/simple-deploy"},
                "1.2.3",
                release_dir,
            )

            self.assertEqual(artifact.local_path, artifact_path)
            self.assertEqual(artifact.remote_archive, "/tmp/simple-deploy/1.2.3/db_schema_dev.tar.gz")
            self.assertEqual(artifact.remote_extract_path, "/tmp/simple-deploy/1.2.3/db_schema_dev")
            self.assertEqual(artifact.entrypoint_dir, ".")
            self.assertEqual(artifact.entrypoint_pattern, "summary_sql_dev_*.sql")

    def test_scp_file_uses_requested_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "db_schema.tar.gz"
            local_path.write_text("", encoding="utf-8")

            with patch("tools.windows_pipeline.ssh_key_args", return_value=["DB_KEY"]) as key_mock:
                with patch(
                    "tools.windows_pipeline.run_command",
                    return_value=CommandResult(0, "", ""),
                ) as run_mock:
                    scp_file({}, local_path, "db-user", "db.example.local", "/tmp/db_schema.tar.gz", scope="DB")

            key_mock.assert_called_once_with({}, "DB")
            command = run_mock.call_args.args[0]
            self.assertIn("DB_KEY", command)
            self.assertIn(f"db-user@db.example.local:/tmp/db_schema.tar.gz", command)

    def test_run_db_schema_summary_uses_single_transaction(self):
        artifact = DbSqlArtifact(
            name="db_schema_dev",
            local_path=Path("db_schema_dev.tar.gz"),
            remote_archive="/tmp/simple-deploy/1.2.3/db_schema_dev.tar.gz",
            remote_extract_path="/tmp/simple-deploy/1.2.3/db_schema_dev",
            entrypoint_dir=".",
            entrypoint_pattern="summary_sql_dev_*.sql",
        )
        env = {
            "DB_VM_USER": "db-user",
            "DB_VM_HOST": "db.example.local",
            "DB_PORT": "5432",
            "DB_NAME": "appdb",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
        }

        with patch("tools.windows_pipeline.scp_file", return_value=CommandResult(0, "", "")):
            with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
                run_db_schema_summary(env, {}, artifact)

        final_command = ssh_mock.call_args_list[-1].args[3]
        self.assertIn("--set=ON_ERROR_STOP=1", final_command)
        self.assertIn("--single-transaction", final_command)
        self.assertIn('-f "$sql_file"', final_command)

    def test_run_db_maintenance_uses_configured_timeout(self):
        env = {
            "DB_VM_USER": "db-user",
            "DB_VM_HOST": "db.example.local",
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

        with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
            run_db_maintenance(env, runtime, "before_unpack")

        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 900)

    def test_run_db_maintenance_uses_timeout_for_sql_scripts(self):
        env = {
            "DB_VM_USER": "db-user",
            "DB_VM_HOST": "db.example.local",
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

        with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "", "")) as ssh_mock:
            run_db_maintenance(env, runtime, "before_unpack")

        self.assertEqual(ssh_mock.call_args.kwargs["timeout"], 900)

    def test_windows_pipeline_example_runtime_config_is_valid(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_runtime_config_rejects_bad_maintenance_timeout(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["db_maintenance_sql_timeout_seconds"] = "900s"
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("db_maintenance_sql_timeout_seconds" in issue for issue in reporter.issues))

    def test_runtime_config_checks_sql_script_shape(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["sql_scripts"] = [{"path": "missing.sql", "phase": "after_unpack"}]
        reporter = Reporter()

        self.assertFalse(check_runtime_config(reporter, runtime))
        self.assertTrue(any("sql_scripts #1" in issue for issue in reporter.issues))

    def test_runtime_config_rejects_bare_systemctl_service_step(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
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

    def test_runtime_config_accepts_bare_systemctl_status_service_step(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["service_steps"] = [
            {
                "name": "status celerybeat",
                "phase": "after_migrate",
                "command": "systemctl status celerybeat_local.service",
                "permission_check_command": "systemctl status celerybeat_local.service",
            }
        ]
        reporter = Reporter()

        self.assertTrue(check_runtime_config(reporter, runtime))
        self.assertEqual(reporter.issues, [])

    def test_runtime_config_accepts_sudo_systemctl_service_step(self):
        runtime_path = ROOT / "tools-ci" / "windows_pipeline.example.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
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
        reporter = Reporter()
        env = {
            "APP_VM_USER": "deploy-simple",
            "APP_VM_HOST": "app.example.local",
        }

        with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "ok\n", "")) as ssh_mock:
            result = check_ssh_runtime(reporter, env, app_only=True)

        self.assertEqual(result, {"app": True, "db": False})
        self.assertEqual(ssh_mock.call_count, 1)
        self.assertTrue(any("DB VM SSH/psql" in item for item in reporter.skipped))

    def test_service_permission_accepts_readable_inactive_systemctl_status(self):
        reporter = Reporter()
        env = {
            "APP_VM_USER": "deploy-simple",
            "APP_VM_HOST": "app.example.local",
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
            with patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(3, status_output, "")):
                check_service_permissions(reporter, env, runtime)

        self.assertEqual(reporter.issues, [])
        self.assertTrue(
            any("status readable; unit may be inactive" in call.args[1] for call in pass_mock.call_args_list)
        )

    def test_load_runtime_config_reports_defaulted_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "windows_pipeline.local.json"
            config_path.write_text('{"backup_enabled": true}\n', encoding="utf-8")

            runtime, defaulted_keys = load_runtime_config(config_path)

        self.assertTrue(runtime["backup_enabled"])
        self.assertIn("db_maintenance_sql_timeout_seconds", defaulted_keys)
        self.assertNotIn("backup_enabled", defaulted_keys)

    def test_ansible_schema_migration_uses_single_transaction(self):
        role_path = ROOT / "ansible-ci" / "roles" / "db_migrations" / "tasks" / "main.yml"
        content = role_path.read_text(encoding="utf-8")

        self.assertIn("--set=ON_ERROR_STOP=1 --single-transaction", content)

    def test_prepare_build_env_uses_backend_source_repo_for_archive_root(self):
        build_env = prepare_build_env(
            {
                "BACKEND_SOURCE_REPO_PATH": r"C:\example\repos\backend-source",
                "BACKEND_TARGET_REPO_PATH_BASH": "/c/example/repos/backend-target",
                "BACKEND_REPO_ROOT_BASH": "/c/wrong",
                "DEV_DOMAIN": "dev.example.local",
            }
        )

        self.assertEqual(build_env["BACKEND_REPO_ROOT_BASH"], "/c/example/repos/backend-source")
        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], "example_backend_app")
        self.assertEqual(build_env["BACKEND_DJANGO_SETTINGS_MODULE"], "example_backend_app.settings.base")

    def test_prepare_build_env_sets_pip_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            build_env = prepare_build_env(
                {
                    "BACKEND_SOURCE_REPO_PATH": r"C:\example\repos\backend-source",
                    "DEV_DOMAIN": "dev.example.local",
                }
            )

        self.assertEqual(build_env["PIP_DISABLE_PIP_VERSION_CHECK"], "1")
        self.assertEqual(
            build_env["PIP_TRUSTED_HOST"],
            "pypi.org files.pythonhosted.org pypi.python.org",
        )

    def test_build_disables_data_sql_by_default(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            timeout=3600,
            include_data_sql=False,
        )
        env = {
            "BACKEND_SOURCE_REPO_PATH": r"C:\example\repos\backend-source",
            "DEV_DOMAIN": "dev.example.local",
        }
        with patch("tools.windows_pipeline.load_env", return_value=env):
            with patch("tools.windows_pipeline.prepare_frontend_env_files"):
                with patch("tools.windows_pipeline.stream_command", return_value=0) as stream_mock:
                    self.assertEqual(build(args), 0)

        build_env = stream_mock.call_args.kwargs["env"]
        self.assertEqual(build_env["SIMPLE_DEPLOY_INCLUDE_DATA_SQL"], "0")

    def test_build_enables_data_sql_with_flag(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            timeout=3600,
            include_data_sql=True,
        )
        env = {
            "BACKEND_SOURCE_REPO_PATH": r"C:\example\repos\backend-source",
            "DEV_DOMAIN": "dev.example.local",
        }
        with patch("tools.windows_pipeline.load_env", return_value=env):
            with patch("tools.windows_pipeline.prepare_frontend_env_files"):
                with patch("tools.windows_pipeline.stream_command", return_value=0) as stream_mock:
                    self.assertEqual(build(args), 0)

        build_env = stream_mock.call_args.kwargs["env"]
        self.assertEqual(build_env["SIMPLE_DEPLOY_INCLUDE_DATA_SQL"], "1")

    def test_pipeline_preserves_app_only_for_deploy(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            config_file=Path("windows_pipeline.local.json"),
            timeout=3600,
            build_version="",
            latest=False,
            contour="dev",
            include_data_sql=False,
            app_only=True,
        )

        with patch("tools.windows_pipeline.dry_run", return_value=True):
            with patch("tools.windows_pipeline.build", return_value=0):
                with patch("tools.windows_pipeline.deploy", return_value=0) as deploy_mock:
                    self.assertEqual(pipeline(args), 0)

        deploy_args = deploy_mock.call_args.args[0]
        self.assertTrue(deploy_args.app_only)
        self.assertTrue(deploy_args.latest)
        self.assertEqual(deploy_args.build_version, "")

    def test_deploy_failure_records_failed_attempt(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            config_file=Path("windows_pipeline.local.json"),
            build_version="1.2.3",
            latest=False,
            contour="dev",
        )
        env = {"DEV_DOMAIN": "dev.example.local"}
        release_dir = Path("releases") / "1.2.3"

        with patch("tools.windows_pipeline.load_env", return_value=env):
            with patch("tools.windows_pipeline.load_runtime_config", return_value=({}, [])):
                with patch("tools.windows_pipeline.resolve_release_dir", return_value=("1.2.3", release_dir)):
                    with patch(
                        "tools.windows_pipeline.resolve_artifacts",
                        side_effect=RuntimeError("artifact missing"),
                    ):
                        with patch("tools.windows_pipeline.mark_contour_failed") as mark_failed_mock:
                            with self.assertRaisesRegex(RuntimeError, "artifact missing"):
                                deploy(args)

        mark_failed_mock.assert_called_once_with("dev", "1.2.3", release_dir, "artifact missing")

    def test_deploy_app_only_skips_db_steps(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            config_file=Path("windows_pipeline.local.json"),
            build_version="1.2.3",
            latest=False,
            contour="dev",
            app_only=True,
        )
        env = {
            "APP_VM_USER": "deploy-simple",
            "APP_VM_HOST": "app.example.local",
            "APP_WORKDIR": "/home/admin/app-backend",
            "APP_VENV_ACTIVATE_PATH": "/home/admin/app-backend/venv/bin/activate",
            "REMOTE_TMP_ROOT": "/tmp/simple-deploy",
            "DEV_DOMAIN": "dev.example.local",
        }
        runtime = {"service_steps": [], "healthcheck_enabled": True}
        release_dir = Path("releases") / "1.2.3"
        artifact = Artifact(
            "backend",
            Path("backend.tar.gz"),
            "/tmp/simple-deploy/1.2.3/backend.tar.gz",
            "/home/admin/app-backend/gazproject_2_0",
        )

        with ExitStack() as stack:
            load_env_mock = stack.enter_context(patch("tools.windows_pipeline.load_env", return_value=env))
            stack.enter_context(patch("tools.windows_pipeline.load_runtime_config", return_value=(runtime, [])))
            stack.enter_context(patch("tools.windows_pipeline.resolve_release_dir", return_value=("1.2.3", release_dir)))
            stack.enter_context(patch("tools.windows_pipeline.resolve_artifacts", return_value=[artifact]))
            resolve_db_mock = stack.enter_context(patch("tools.windows_pipeline.resolve_db_schema_artifact"))
            db_maintenance_mock = stack.enter_context(patch("tools.windows_pipeline.run_db_maintenance"))
            db_schema_mock = stack.enter_context(patch("tools.windows_pipeline.run_db_schema_summary"))
            service_mock = stack.enter_context(patch("tools.windows_pipeline.run_service_steps"))
            stack.enter_context(
                patch("tools.windows_pipeline.management_commands", return_value=["python manage.py migrate --fake"])
            )
            stack.enter_context(patch("tools.windows_pipeline.ssh_command", return_value=CommandResult(0, "", "")))
            stack.enter_context(patch("tools.windows_pipeline.scp_file", return_value=CommandResult(0, "", "")))
            healthcheck_mock = stack.enter_context(patch("tools.windows_pipeline.healthcheck"))
            mark_applied_mock = stack.enter_context(patch("tools.windows_pipeline.mark_contour_applied"))
            stack.enter_context(patch("tools.windows_pipeline.send_outlook_success_email"))

            self.assertEqual(deploy(args), 0)

        load_env_mock.assert_called_once_with(args.env_file, args.secrets_file, require_secrets=False)
        resolve_db_mock.assert_not_called()
        db_maintenance_mock.assert_not_called()
        db_schema_mock.assert_not_called()
        self.assertEqual(
            [call.args[2] for call in service_mock.call_args_list],
            ["before_unpack", "after_unpack", "after_migrate"],
        )
        healthcheck_mock.assert_called_once()
        mark_applied_mock.assert_called_once_with("dev", "1.2.3", release_dir)

    def test_deploy_failure_record_error_preserves_original_error(self):
        args = Namespace(
            env_file=Path(".env"),
            secrets_file=Path("local.secrets.env"),
            config_file=Path("windows_pipeline.local.json"),
            build_version="1.2.3",
            latest=False,
            contour="dev",
        )
        release_dir = Path("releases") / "1.2.3"

        with patch("tools.windows_pipeline.load_env", return_value={}):
            with patch("tools.windows_pipeline.load_runtime_config", return_value=({}, [])):
                with patch("tools.windows_pipeline.resolve_release_dir", return_value=("1.2.3", release_dir)):
                    with patch(
                        "tools.windows_pipeline.resolve_artifacts",
                        side_effect=RuntimeError("artifact missing"),
                    ):
                        with patch(
                            "tools.windows_pipeline.mark_contour_failed",
                            side_effect=RuntimeError("sqlite error"),
                        ):
                            with self.assertRaisesRegex(RuntimeError, "artifact missing"):
                                deploy(args)

    def test_prepare_build_env_keeps_configured_backend_app_root(self):
        build_env = prepare_build_env(
            {
                "BACKEND_SOURCE_REPO_PATH": r"C:\example\repos\backend-source",
                "BACKEND_APP_ROOT_DIR": "backend_app",
                "DEV_DOMAIN": "dev.example.local",
            }
        )

        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], "backend_app")
        self.assertEqual(build_env["BACKEND_DJANGO_SETTINGS_MODULE"], "backend_app.settings.base")

    def test_dry_run_fails_when_backend_app_root_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            source_repo.mkdir()
            (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
            reporter = Reporter()

            with patch.dict("os.environ", {}, clear=True):
                check_backend_build_inputs(
                    reporter,
                    {
                        "BACKEND_SOURCE_REPO_PATH": str(source_repo),
                        "DEV_DOMAIN": "dev.example.local",
                    },
                )

        self.assertTrue(any("BACKEND_APP_ROOT_DIR" in issue for issue in reporter.issues))

    def test_dry_run_checks_backend_settings_import_when_venv_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            app_root = source_repo / "backend_app"
            venv_scripts = source_repo / ".venv" / "Scripts"
            app_root.mkdir(parents=True)
            venv_scripts.mkdir(parents=True)
            (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
            python_path = venv_scripts / "python.exe"
            python_path.write_text("", encoding="utf-8")
            reporter = Reporter()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "tools.windows_pipeline.run_command",
                    return_value=CommandResult(0, "backend_app.settings.base\n", ""),
                ) as run_mock:
                    check_backend_build_inputs(
                        reporter,
                        {
                            "BACKEND_SOURCE_REPO_PATH": str(source_repo),
                            "BACKEND_APP_ROOT_DIR": "backend_app",
                            "BACKEND_DJANGO_SETTINGS_MODULE": "backend_app.settings.base",
                            "DEV_DOMAIN": "dev.example.local",
                        },
                    )

        self.assertEqual(reporter.issues, [])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], str(python_path))
        self.assertEqual(command[1:3], ["-Xutf8", "-c"])
        self.assertIn("backend_app.settings.base", command[3])

    def test_dry_run_fails_on_non_idempotent_data_insert_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / "docs/database/scripts/app_ip_subcompany/insert_04_26"
            insert_dir.mkdir(parents=True)
            bad_sql = insert_dir / "insert_bad.sql"
            bad_sql.write_text("INSERT INTO table_name (id) VALUES (1);\n", encoding="utf-8")
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert_bad.sql" in issue for issue in reporter.issues))

    def test_dry_run_passes_on_idempotent_data_insert_sql(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / "docs/database/scripts/app_ip_subcompany/insert_04_26"
            insert_dir.mkdir(parents=True)
            good_sql = insert_dir / "insert_good.sql"
            good_sql.write_text(
                "INSERT INTO table_name (id) VALUES (1) "
                "ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_outlook_success_email_attaches_release_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            release_dir = Path(tmp)
            manifest = release_dir / "release_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            runtime = {
                "outlook_email_enabled": True,
                "outlook_email_recipients": ["dev-team@example.local"],
                "outlook_email_subject": "Release {build_version}",
                "outlook_email_body": "Artifacts:\n{artifacts_text}",
            }
            env = {"DEV_DOMAIN": "dev.example.local"}
            artifacts = [
                Artifact(
                    name="backend",
                    local_path=release_dir / "backend.tar.gz",
                    remote_archive="/tmp/backend.tar.gz",
                    extract_path="/opt/backend",
                )
            ]

            with patch("tools.windows_pipeline.release_changelog_text", return_value="none"):
                with patch(
                    "tools.windows_pipeline.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(env, runtime, "1.2.3", release_dir, artifacts)

            payload = json.loads(run_mock.call_args.kwargs["input_text"])
            self.assertEqual(payload["attachments"], [str(manifest)])
            powershell = run_mock.call_args.args[0][-1]
            self.assertIn("font-family: Arial", powershell)
            self.assertIn("font-size: 10pt", powershell)
            self.assertIn("HtmlEncode", powershell)
            self.assertIn("<br>", powershell)


if __name__ == "__main__":
    unittest.main()
