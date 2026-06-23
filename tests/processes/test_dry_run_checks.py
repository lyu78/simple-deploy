import sys
import tempfile
import unittest
from pathlib import Path
from urllib import error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.core.commands import CommandResult  # noqa: E402
from simple_deploy.processes.dry_run_checks import (  # noqa: E402
    Reporter,
    check_app_deploy_directories,
    check_app_manage_py,
    check_backend_data_insert_idempotency,
    check_db_psql_login,
    check_http,
    check_maintenance_stub_archive,
    check_origin_network,
    check_outlook_email_config,
    check_remote_directory,
    check_repo,
    check_service_permissions,
    check_ssh_key_files,
    check_ssh_runtime,
    find_catalog_business_key_conflicts,
    iter_sql_files,
    parse_insert_rows,
    parse_sql_literal,
    runtime_local_path,
    split_sql_csv,
    split_sql_statements,
)


class DryRunCheckSqlParsingTests(unittest.TestCase):
    def test_split_sql_statements_keeps_semicolon_inside_string(self):
        statements = split_sql_statements(
            "\nSELECT 'a;b';\n\nINSERT INTO t (id) VALUES (1);"
        )

        self.assertEqual(
            statements,
            [
                ("SELECT 'a;b'", 2),
                ("INSERT INTO t (id) VALUES (1)", 4),
            ],
        )

    def test_split_sql_csv_keeps_nested_calls_and_escaped_quotes(self):
        values = split_sql_csv("'a,b', now(), func(1, 'x,y'), 'it''s ok'")

        self.assertEqual(
            values,
            ["'a,b'", "now()", "func(1, 'x,y')", "'it''s ok'"],
        )

    def test_parse_insert_rows_handles_quoted_table_null_and_escaped_literals(self):
        rows = parse_insert_rows(
            """
            INSERT INTO public."app_ip_subcompany_catalog_region" ("id", "code", "title")
            VALUES (1, 'RU', 'Russia'), (2, NULL, 'It''s empty')
            ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;
            """
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].table, "app_ip_subcompany_catalog_region")
        self.assertEqual(rows[0].columns, ("id", "code", "title"))
        self.assertEqual(rows[0].values, ("1", "RU", "Russia"))
        self.assertEqual(rows[1].values, ("2", None, "It's empty"))

    def test_parse_sql_literal_returns_unquoted_values_and_null(self):
        self.assertIsNone(parse_sql_literal("NULL"))
        self.assertEqual(parse_sql_literal("'a''b'"), "a'b")
        self.assertEqual(parse_sql_literal("42"), "42")

    def test_find_catalog_business_key_conflicts_ignores_blank_optional_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.sql"
            path.write_text(
                """
                INSERT INTO app_ip_subcompany_catalog_contractor (id, tin, title)
                VALUES (1, '', 'a'), (2, '', 'b');
                INSERT INTO app_ip_subcompany_catalog_region (id, code, title)
                VALUES (1, '77', 'a'), (2, '77', 'b');
                """,
                encoding="utf-8",
            )

            problems = find_catalog_business_key_conflicts(
                path, Path("docs/database/scripts/catalog.sql")
            )

        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].rule, "catalog business key duplicate")
        self.assertIn("app_ip_subcompany_catalog_region", problems[0].detail)

    def test_iter_sql_files_filters_insert_and_set_default_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "insert").mkdir()
            (root / "update").mkdir()
            (root / "set_default").mkdir()
            insert_sql = root / "insert" / "a.sql"
            update_sql = root / "update" / "b.sql"
            default_sql = root / "set_default" / "c.sql"
            insert_sql.write_text("", encoding="utf-8")
            update_sql.write_text("", encoding="utf-8")
            default_sql.write_text("", encoding="utf-8")

            insert_only = list(iter_sql_files(root, include_insert_only=True))
            all_sql = list(iter_sql_files(root, include_insert_only=False))

        self.assertEqual(insert_only, [insert_sql])
        self.assertEqual(all_sql, [insert_sql, update_sql])


class DryRunCheckEnvironmentTests(unittest.TestCase):
    def test_check_ssh_key_files_skips_unconfigured_keys(self):
        reporter = Reporter()

        check_ssh_key_files(reporter, {}, app_only=False)

        self.assertEqual(reporter.issues, [])
        self.assertIn("SSH key: not configured", reporter.skipped[0])

    def test_check_ssh_key_files_reports_missing_specific_key_and_skips_db_app_only(self):
        reporter = Reporter()

        check_ssh_key_files(
            reporter,
            {"APP_SSH_KEY_PATH": "missing-app-key.pem"},
            app_only=True,
        )

        self.assertTrue(any("app SSH key" in issue for issue in reporter.issues))
        self.assertTrue(any("DB SSH key" in item for item in reporter.skipped))

    def test_check_repo_reports_missing_git_and_origin_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            reporter = Reporter()

            self.assertEqual(check_repo(reporter, "repo", str(path)), "")
            self.assertIn("не Git-репозиторий", reporter.issues[0])

            (path / ".git").mkdir()
            reporter = Reporter()
            with patch(
                "simple_deploy.processes.dry_run_checks.run_command",
                return_value=CommandResult(1, "", "origin missing"),
            ):
                self.assertEqual(check_repo(reporter, "repo", str(path)), "")

        self.assertIn("origin missing", reporter.issues[0])

    def test_check_repo_returns_origin_url_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".git").mkdir()
            reporter = Reporter()

            with patch(
                "simple_deploy.processes.dry_run_checks.run_command",
                return_value=CommandResult(0, "https://example/repo.git\n", ""),
            ):
                origin = check_repo(reporter, "repo", str(path))

        self.assertEqual(origin, "https://example/repo.git")
        self.assertEqual(reporter.issues, [])

    def test_check_origin_network_skips_unsupported_urls_and_accepts_auth_http_codes(self):
        reporter = Reporter()

        check_origin_network(reporter, "empty", "")
        check_origin_network(reporter, "ssh", "git@example:repo.git")
        check_origin_network(reporter, "file", "file:///repo")

        http_error = error.HTTPError(
            url="https://example/repo",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        with patch(
            "simple_deploy.processes.dry_run_checks.request.urlopen",
            side_effect=http_error,
        ):
            check_origin_network(reporter, "http", "https://example/repo")

        self.assertEqual(reporter.issues, [])
        self.assertEqual(len(reporter.skipped), 3)

    def test_check_origin_network_fails_on_server_error(self):
        reporter = Reporter()
        http_error = error.HTTPError(
            url="https://example/repo",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )

        with patch(
            "simple_deploy.processes.dry_run_checks.request.urlopen",
            side_effect=http_error,
        ):
            check_origin_network(reporter, "http", "https://example/repo")

        self.assertIn("HTTP 500", reporter.issues[0])

    def test_runtime_local_path_resolves_relative_paths_under_repo_root(self):
        self.assertEqual(runtime_local_path("tools-ci"), ROOT / "tools-ci")

    def test_check_maintenance_stub_archive_handles_disabled_and_absolute_path(self):
        reporter = Reporter()
        check_maintenance_stub_archive(
            reporter, {"maintenance_stub_enabled": False}
        )
        self.assertIn("maintenance stub archive: disabled", reporter.skipped)

        with tempfile.NamedTemporaryFile() as tmp:
            reporter = Reporter()
            check_maintenance_stub_archive(
                reporter,
                {
                    "maintenance_stub_enabled": True,
                    "maintenance_stub_archive_path": tmp.name,
                },
            )

        self.assertEqual(reporter.issues, [])


class DryRunCheckRemoteTests(unittest.TestCase):
    def _env(self) -> dict[str, str]:
        return {
            "APP_VM_USER": "deploy",
            "APP_VM_HOST": "app.example.local",
            "DB_VM_USER": "db",
            "DB_VM_HOST": "db.example.local",
            "DB_PORT": "5432",
            "DB_NAME": "app",
            "DB_LOGIN_USER": "postgres",
            "DB_LOGIN_PASSWORD": "secret",
            "REMOTE_TMP_ROOT": "/tmp/simple-deploy",
            "BACKEND_RELEASE_PATH": "/opt/backend",
            "FRONTEND_RELEASE_PATH": "/opt/frontend",
            "APP_WORKDIR": "/opt/backend",
            "APP_MANAGE_PY_PATH": "manage.py",
            "DEV_DOMAIN": "dev.example.local",
        }

    def test_check_ssh_runtime_skips_db_in_app_only_mode(self):
        reporter = Reporter()

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            return_value=CommandResult(0, "ok\n", ""),
        ) as ssh_mock:
            state = check_ssh_runtime(reporter, self._env(), app_only=True)

        self.assertEqual(state, {"app": True, "db": False})
        self.assertEqual(ssh_mock.call_count, 1)
        self.assertTrue(any("DB VM SSH/psql" in item for item in reporter.skipped))

    def test_check_ssh_runtime_records_db_failure_without_disabling_app(self):
        reporter = Reporter()

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            side_effect=[
                CommandResult(0, "app ok", ""),
                CommandResult(1, "", "db down"),
            ],
        ):
            state = check_ssh_runtime(reporter, self._env())

        self.assertEqual(state, {"app": True, "db": False})
        self.assertTrue(any("DB VM SSH/psql" in issue for issue in reporter.issues))

    def test_check_db_psql_login_masks_password_on_failure(self):
        reporter = Reporter()

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            return_value=CommandResult(2, "", "password secret rejected"),
        ):
            check_db_psql_login(
                reporter,
                self._env(),
                {"db_psql_bin": "psql", "db_psql_host": "localhost"},
            )

        self.assertIn("*** rejected", reporter.issues[0])
        self.assertNotIn("secret", reporter.issues[0])

    def test_check_outlook_email_config_validates_templates_and_com(self):
        reporter = Reporter()

        with patch(
            "simple_deploy.processes.dry_run_checks.check_command"
        ) as command_mock:
            check_outlook_email_config(
                reporter,
                {
                    "outlook_email_enabled": True,
                    "outlook_email_recipients": "dev@example.local",
                    "outlook_email_cc": "owner@example.local",
                    "outlook_email_subject": "Release {build_version}",
                    "outlook_email_body": "Open {stand_url}",
                    "outlook_email_required": True,
                },
            )

        self.assertEqual(reporter.issues, [])
        command_mock.assert_called_once()

    def test_check_outlook_email_config_reports_missing_fields_and_bad_template(self):
        reporter = Reporter()

        with patch("simple_deploy.processes.dry_run_checks.check_command"):
            check_outlook_email_config(
                reporter,
                {
                    "outlook_email_enabled": True,
                    "outlook_email_recipients": [],
                    "outlook_email_subject": "",
                    "outlook_email_body": "{bad",
                },
            )

        self.assertTrue(any("Outlook email recipients" in item for item in reporter.issues))
        self.assertTrue(any("Outlook email subject" in item for item in reporter.issues))
        self.assertTrue(any("Outlook email templates" in item for item in reporter.issues))

    def test_check_service_permissions_handles_disabled_empty_sudo_and_derived(self):
        env = self._env()

        reporter = Reporter()
        check_service_permissions(
            reporter, env, {"service_permission_checks_enabled": False}
        )
        self.assertIn("service permission checks: disabled", reporter.skipped)

        reporter = Reporter()
        check_service_permissions(
            reporter,
            env,
            {"service_permission_checks_enabled": True, "service_steps": []},
        )
        self.assertIn("service permission checks: service_steps empty", reporter.skipped)

        reporter = Reporter()
        runtime = {
            "service_permission_checks_enabled": True,
            "service_steps": [
                {
                    "name": "nginx",
                    "command": "systemctl restart nginx",
                },
                {
                    "name": "custom sudo",
                    "command": "sudo /bin/systemctl start app",
                },
            ],
        }
        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            side_effect=[
                CommandResult(0, "sudo list", ""),
                CommandResult(0, "dry run ok", ""),
                CommandResult(0, "sudo ok", ""),
            ],
        ) as ssh_mock:
            check_service_permissions(reporter, env, runtime)

        self.assertEqual(reporter.issues, [])
        self.assertEqual(ssh_mock.call_count, 3)
        derived_command = ssh_mock.call_args_list[1].args[3]
        self.assertIn("--dry-run", derived_command)

    def test_check_service_permissions_accepts_readable_status_rc_3(self):
        reporter = Reporter()
        runtime = {
            "service_permission_checks_enabled": True,
            "service_steps": [
                {
                    "name": "status",
                    "command": "echo unused",
                    "permission_check_command": "systemctl status app",
                }
            ],
        }

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            return_value=CommandResult(3, "inactive", ""),
        ):
            check_service_permissions(reporter, self._env(), runtime)

        self.assertEqual(reporter.issues, [])

    def test_check_remote_directory_and_app_helpers_use_ssh_results(self):
        reporter = Reporter()
        env = self._env()

        with patch(
            "simple_deploy.processes.dry_run_checks.ssh_command",
            return_value=CommandResult(0, "", ""),
        ) as ssh_mock:
            check_remote_directory(reporter, env, "tmp", "/tmp/simple-deploy/")
            check_app_deploy_directories(
                reporter,
                env,
                {"backup_enabled": True},
            )
            check_app_manage_py(reporter, env)

        self.assertEqual(reporter.issues, [])
        self.assertEqual(ssh_mock.call_count, 7)

    def test_check_http_accepts_403_and_fails_500(self):
        reporter = Reporter()

        forbidden = error.HTTPError(
            url="https://dev.example.local/",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        server_error = error.HTTPError(
            url="https://dev.example.local/",
            code=500,
            msg="Server Error",
            hdrs=None,
            fp=None,
        )
        with patch(
            "simple_deploy.processes.dry_run_checks.request.urlopen",
            side_effect=[forbidden, server_error],
        ):
            check_http(reporter, self._env(), validate_certs=False)
            check_http(reporter, self._env(), validate_certs=False)

        self.assertTrue(any("HTTP 500" in issue for issue in reporter.issues))
