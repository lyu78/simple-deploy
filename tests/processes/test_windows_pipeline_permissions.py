"""Тесты совместимого Windows pipeline перед разборкой процессного монолита.

Модуль фиксирует контракты runtime-валидации, SSH/SQL команд, build/deploy
оркестрации и dry-run проверок. Тестовые пути намеренно собраны в константах,
чтобы реальные локальные директории и закрытая архитектура репозитория-источника
не расползались по проверкам.
"""

import unittest
import json
import os
import tempfile
from contextlib import ExitStack, closing, nullcontext
from pathlib import Path
import sys
from argparse import Namespace
from unittest.mock import patch, sentinel

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"
RUNTIME_EXAMPLE_PATH = TOOLS_CI_ROOT / "windows_pipeline.example.json"
LEGACY_DB_MIGRATIONS_TASKS = ROOT / "legacy" / "ansible-ci" / "roles" / "db_migrations" / "tasks" / "main.yml"
MISSING_MAINTENANCE_STUB_ARCHIVE = TOOLS_CI_ROOT / "maintenance_stub" / "missing.tar.gz"

DEFAULT_ENV_FILE = TOOLS_CI_ROOT / ".env"
DEFAULT_SECRETS_FILE = TOOLS_CI_ROOT / "local.secrets.env"
DEFAULT_CONFIG_FILE = TOOLS_CI_ROOT / "windows_pipeline.local.json"

TEST_BUILD_VERSION = "1.2.3"
PREVIOUS_BUILD_VERSION = "1.2.2"
TEST_BACKEND_COMMIT = "abc123"
PREVIOUS_BACKEND_COMMIT = "prev123"
TEST_FRONTEND_COMMIT = "def456"

REMOTE_TMP_ROOT = "/tmp/simple-deploy"
REMOTE_RELEASE_ROOT = f"{REMOTE_TMP_ROOT}/{TEST_BUILD_VERSION}"
REMOTE_BACKEND_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/backend.tar.gz"
REMOTE_FRONTEND_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/frontend.tar.gz"
REMOTE_MAINTENANCE_STUB_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/maintenance_stub.tar.gz"
REMOTE_DB_SCHEMA_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_schema_dev.tar.gz"
REMOTE_DB_SCHEMA_DIR = f"{REMOTE_RELEASE_ROOT}/db_schema_dev"
REMOTE_DB_INSERT_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_insert.tar.gz"
REMOTE_DB_INSERT_DIR = f"{REMOTE_RELEASE_ROOT}/db_insert"
REMOTE_DB_UPDATE_PARALLEL_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_update_parallel.tar.gz"
REMOTE_DB_UPDATE_PARALLEL_DIR = f"{REMOTE_RELEASE_ROOT}/db_update_parallel"
REMOTE_DB_SET_DEFAULT_PARALLEL_ARCHIVE = (
    f"{REMOTE_RELEASE_ROOT}/db_set_default_parallel.tar.gz"
)
REMOTE_DB_SET_DEFAULT_PARALLEL_DIR = (
    f"{REMOTE_RELEASE_ROOT}/db_set_default_parallel"
)

APP_VM_USER = "deploy-simple"
APP_VM_HOST = "app.example.local"
DB_VM_USER = "db-user"
DB_VM_HOST = "db.example.local"
DEV_DOMAIN = "dev.example.local"
APP_WORKDIR = "/opt/example/backend"
APP_VENV_ACTIVATE_PATH = "/opt/example/backend/venv/bin/activate"
BACKEND_RELEASE_PATH = "/opt/example/backend/app"
FRONTEND_RELEASE_PATH = "/opt/example/frontend/dist"

BACKEND_SOURCE_REPO_WINDOWS = r"C:\example\repos\backend-source"
BACKEND_APP_ROOT = "backend_app"

DATA_SQL_ROOT = "docs/database/scripts"
DATA_SQL_STANDARD_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany/insert_04_26"
DATA_SQL_CATALOG_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany_catalogs/insert_04_26"
DATA_SQL_FULL_STATE_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany_cc/insert_04_26"
DATA_SQL_INSERT_NEW_OBJECTS_DIR = (
    f"{DATA_SQL_ROOT}/insert_new_objects/insert_04_26/insert_cc_and_prw_objects/1_iteration"
)
CATALOG_BUSINESS_KEY_TABLE = "app_ip_subcompany_catalog_contractsubject"
INSERT_NEW_OBJECTS_TABLE = "app_ip_subcompany_objectplanning"
INSERT_NEW_OBJECTS_SQL_FILE = f"insert_{INSERT_NEW_OBJECTS_TABLE}.sql"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.cli.windows_pipeline import (  # noqa: E402
    deploy,
    main,
    mark_applied,
    mark_failed,
    parse_args,
    pipeline,
    set_baseline,
)
from simple_deploy.application.requests import PipelineRequest  # noqa: E402
from simple_deploy.application.results import ProcessResult  # noqa: E402
from simple_deploy.config.runtime_loader import (  # noqa: E402
    check_runtime_config,
    load_runtime_config,
)
from simple_deploy.core.build_env import prepare_build_env  # noqa: E402
from simple_deploy.core.commands import CommandResult  # noqa: E402
from simple_deploy.core.ssh import scp_file  # noqa: E402
from simple_deploy.processes.app_deploy import (  # noqa: E402
    management_commands,
)
from simple_deploy.processes.data_sql import (  # noqa: E402
    cleanup_db_data_update_leftovers,
    run_db_data_insert,
    run_db_data_set_default_parallel,
    run_db_data_update_parallel,
    run_db_maintenance,
    run_db_schema_summary,
)
from simple_deploy.processes.dry_run_checks import (  # noqa: E402
    Reporter,
    check_backend_build_inputs,
    check_backend_data_insert_idempotency,
    check_maintenance_stub_archive,
    check_service_permissions,
    check_ssh_runtime,
    derive_service_permission_check,
    is_sudo_command,
    sudo_list_command,
)
from simple_deploy.processes.healthcheck import (  # noqa: E402
    verify_maintenance_stub_http,
)
from simple_deploy.processes.notifications import (  # noqa: E402
    send_outlook_success_email,
)
from simple_deploy.release.artifacts import (  # noqa: E402
    Artifact,
    DbSqlArtifact,
    resolve_db_data_artifact,
    resolve_db_schema_artifact,
    resolve_maintenance_stub_artifact,
)
from simple_deploy.release.manifest import RELEASE_MANIFEST_NAME  # noqa: E402
from simple_deploy.release.state import (  # noqa: E402
    connect_state_db,
    get_contour_state,
    list_deployment_attempts,
    upsert_contour_state,
)
from simple_deploy.types import ContourCodeEnum  # noqa: E402


class WindowsPipelinePermissionTests(unittest.TestCase):
    """Проверяет поведение Windows runner, которое должно сохраниться при шаге 5."""

    def _write_release_manifest(self, release_dir: Path, backend_commit: str = TEST_BACKEND_COMMIT) -> None:
        """Создает минимальный release_manifest.json для ручных mark-процессов."""
        release_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "repositories": {
                "backend": {"commit_sha": backend_commit},
                "frontend": {"commit_sha": TEST_FRONTEND_COMMIT},
            }
        }
        (release_dir / RELEASE_MANIFEST_NAME).write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def _deploy_args(self, app_only: bool = False) -> Namespace:
        """Возвращает базовый Namespace deploy-команды для process tests."""
        return Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
            include_set_default_sql=False,
            app_only=app_only,
        )

    def _deploy_env(self) -> dict[str, str]:
        """Возвращает нейтральное окружение app VM для deploy characterization tests."""
        return {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
            "APP_WORKDIR": APP_WORKDIR,
            "APP_VENV_ACTIVATE_PATH": APP_VENV_ACTIVATE_PATH,
            "REMOTE_TMP_ROOT": REMOTE_TMP_ROOT,
            "DEV_DOMAIN": DEV_DOMAIN,
        }

    def _app_artifacts(self) -> tuple[Artifact, Artifact]:
        """Создает backend/frontend artifacts с нейтральными remote paths."""
        backend = Artifact("backend", Path("backend.tar.gz"), REMOTE_BACKEND_ARCHIVE, BACKEND_RELEASE_PATH)
        frontend = Artifact("frontend", Path("frontend.tar.gz"), REMOTE_FRONTEND_ARCHIVE, FRONTEND_RELEASE_PATH)
        return backend, frontend

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

    def test_ansible_schema_migration_uses_single_transaction(self):
        """Сохраняет legacy Ansible schema migration в single-transaction режиме."""
        content = LEGACY_DB_MIGRATIONS_TASKS.read_text(encoding="utf-8")

        self.assertIn("--set=ON_ERROR_STOP=1 --single-transaction", content)

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

    def test_deploy_full_skips_maintenance_stub_when_runtime_disabled(self):
        """При maintenance_stub_enabled=false deploy не resolve/unpack/verify stub."""
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

    def test_prepare_build_env_keeps_configured_backend_app_root(self):
        """Не перетирает явно заданный backend app root дефолтным значением."""
        build_env = prepare_build_env(
            {
                "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
                "BACKEND_APP_ROOT_DIR": BACKEND_APP_ROOT,
                "DEV_DOMAIN": DEV_DOMAIN,
            }
        )

        self.assertEqual(build_env["BACKEND_APP_ROOT_DIR"], BACKEND_APP_ROOT)
        self.assertEqual(build_env["BACKEND_DJANGO_SETTINGS_MODULE"], f"{BACKEND_APP_ROOT}.settings.base")

    def test_dry_run_fails_when_backend_app_root_is_missing(self):
        """Dry-run сообщает ошибку, если backend app root не задан и не найден."""
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
                        "DEV_DOMAIN": DEV_DOMAIN,
                    },
                )

        self.assertTrue(any("BACKEND_APP_ROOT_DIR" in issue for issue in reporter.issues))

    def test_dry_run_checks_backend_settings_import_when_venv_exists(self):
        """Dry-run проверяет импорт Django settings через найденный backend venv."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            app_root = source_repo / BACKEND_APP_ROOT
            venv_scripts = source_repo / ".venv" / "Scripts"
            app_root.mkdir(parents=True)
            venv_scripts.mkdir(parents=True)
            (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
            python_path = venv_scripts / "python.exe"
            python_path.write_text("", encoding="utf-8")
            reporter = Reporter()

            with patch.dict("os.environ", {}, clear=True):
                with patch(
                    "simple_deploy.processes.dry_run_checks.run_command",
                    return_value=CommandResult(0, f"{BACKEND_APP_ROOT}.settings.base\n", ""),
                ) as run_mock:
                    check_backend_build_inputs(
                        reporter,
                        {
                            "BACKEND_SOURCE_REPO_PATH": str(source_repo),
                            "BACKEND_APP_ROOT_DIR": BACKEND_APP_ROOT,
                            "BACKEND_DJANGO_SETTINGS_MODULE": f"{BACKEND_APP_ROOT}.settings.base",
                            "DEV_DOMAIN": DEV_DOMAIN,
                        },
                    )

        self.assertEqual(reporter.issues, [])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], str(python_path))
        self.assertEqual(command[1:3], ["-Xutf8", "-c"])
        self.assertIn(f"{BACKEND_APP_ROOT}.settings.base", command[3])

    def test_dry_run_fails_on_non_idempotent_data_insert_sql(self):
        """Dry-run отклоняет INSERT без ON CONFLICT в обычных data insert каталогах."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_STANDARD_INSERT_DIR
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
        """Dry-run принимает INSERT с конфликтной стратегией обновления."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_STANDARD_INSERT_DIR
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

    def test_dry_run_fails_on_catalog_business_key_duplicate(self):
        """Dry-run ловит дубликаты бизнес-ключей в catalog data SQL."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_CATALOG_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_contractsubject.sql"
            sql.write_text(
                "\n".join(
                    [
                        f"INSERT INTO public.{CATALOG_BUSINESS_KEY_TABLE} (id, title)",
                        "VALUES (1, 'same title')",
                        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                        f"INSERT INTO public.{CATALOG_BUSINESS_KEY_TABLE} (id, title)",
                        "VALUES (2, 'same title')",
                        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;",
                    ]
                ),
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("catalog business key duplicate" in issue for issue in reporter.issues))
        self.assertTrue(any("same title" in issue for issue in reporter.issues))

    def test_dry_run_allows_full_state_truncate_insert_sql(self):
        """Разрешает full-state insert, если SQL сам очищает управляемую таблицу."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_full_state.sql"
            sql.write_text(
                "TRUNCATE TABLE public.some_owned_table RESTART IDENTITY;\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_allows_full_state_drop_create_insert_sql(self):
        """Разрешает full-state insert, если SQL пересоздает управляемую таблицу."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_recreated_table.sql"
            sql.write_text(
                "DROP TABLE IF EXISTS public.some_owned_table;\n"
                "CREATE TABLE public.some_owned_table (id bigint PRIMARY KEY);\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_allows_drop_insert_sql(self):
        """Разрешает insert после DROP зависимого объекта в full-state каталоге."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_FULL_STATE_INSERT_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / "insert_drop_reset.sql"
            sql.write_text(
                "DROP MATERIALIZED VIEW IF EXISTS public.some_owned_view;\n"
                "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_dry_run_fails_on_insert_new_objects_truncate(self):
        """Запрещает TRUNCATE в insert_new_objects, где допустим только insert-if-missing."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"TRUNCATE TABLE public.{INSERT_NEW_OBJECTS_TABLE};\n"
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT DO NOTHING;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert-if-missing idempotency" in issue for issue in reporter.issues))

    def test_dry_run_fails_on_insert_new_objects_without_do_nothing(self):
        """Запрещает insert_new_objects с UPDATE-веткой вместо DO NOTHING."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertTrue(any("insert-if-missing idempotency" in issue for issue in reporter.issues))

    def test_dry_run_passes_on_insert_new_objects_do_nothing(self):
        """Разрешает insert_new_objects, если конфликтная стратегия только DO NOTHING."""
        with tempfile.TemporaryDirectory() as tmp:
            source_repo = Path(tmp) / "backend"
            insert_dir = source_repo / DATA_SQL_INSERT_NEW_OBJECTS_DIR
            insert_dir.mkdir(parents=True)
            sql = insert_dir / INSERT_NEW_OBJECTS_SQL_FILE
            sql.write_text(
                f"INSERT INTO public.{INSERT_NEW_OBJECTS_TABLE} (id) VALUES (1) "
                "ON CONFLICT DO NOTHING;\n",
                encoding="utf-8",
            )
            reporter = Reporter()

            check_backend_data_insert_idempotency(
                reporter,
                {"BACKEND_SOURCE_REPO_PATH": str(source_repo)},
            )

        self.assertEqual(reporter.issues, [])

    def test_outlook_success_email_attaches_release_manifest(self):
        """Проверяет HTML-письмо Outlook и attachment release_manifest.json."""
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
            env = {"DEV_DOMAIN": DEV_DOMAIN}
            artifacts = [
                Artifact(
                    name="backend",
                    local_path=release_dir / "backend.tar.gz",
                    remote_archive="/tmp/backend.tar.gz",
                    extract_path=BACKEND_RELEASE_PATH,
                )
            ]

            with patch("simple_deploy.processes.notifications.release_changelog_text", return_value="none"):
                with patch(
                    "simple_deploy.processes.notifications.run_command",
                    return_value=CommandResult(0, "sent", ""),
                ) as run_mock:
                    send_outlook_success_email(env, runtime, TEST_BUILD_VERSION, release_dir, artifacts)

            payload = json.loads(run_mock.call_args.kwargs["input_text"])
            self.assertEqual(payload["attachments"], [str(manifest)])
            powershell = run_mock.call_args.args[0][-1]
            self.assertIn("font-family: Arial", powershell)
            self.assertIn("font-size: 10pt", powershell)
            self.assertIn("HtmlEncode", powershell)
            self.assertIn("<br>", powershell)


if __name__ == "__main__":
    unittest.main()
