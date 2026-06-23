"""Тесты сборки backend artifacts и offline SQL архивов builder-а.

Модуль описывает контракты упаковки schema/data SQL, запуска дополнительных
генераторов и синхронизации backend source repo. Пути к тестовой структуре
исходного репозитория вынесены в константы, чтобы при следующем разбиении тестов
их можно было заменить fixtures или параметризацией.
"""

import importlib.util
import io
import json
import shutil
import sys
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"
BUILDER_ROOT = TOOLS_CI_ROOT / "builder"
TEST_BUILD_VERSION = "1.2.3"
TEST_COMMIT = "abc123"
TEST_RELEASE_BRANCH = f"release/{TEST_BUILD_VERSION}"

DB_SCRIPTS_ROOT = "docs/database/scripts"
APP_INSERT_SQL = f"{DB_SCRIPTS_ROOT}/app/insert/a.sql"
APP_SECOND_INSERT_SQL = f"{DB_SCRIPTS_ROOT}/app/insert/b.sql"
APP_UNUSED_UPDATE_SQL = f"{DB_SCRIPTS_ROOT}/app/update/not_used.sql"
APP_UPDATE_SQL = f"{DB_SCRIPTS_ROOT}/app/update/a.sql"
CATALOG_INSERT_DIR = f"{DB_SCRIPTS_ROOT}/app_ip_subcompany_catalogs/insert_01_26"
FULL_STATE_INSERT_SQL = f"{DB_SCRIPTS_ROOT}/app_ip_subcompany_cc/insert_04_26/insert_drop_reset.sql"
INSERT_NEW_OBJECTS_UPDATE_SQL = f"{DB_SCRIPTS_ROOT}/insert_new_objects/manual_update.sql"
DOMAIN_A_DEFAULT_SQL = f"{DB_SCRIPTS_ROOT}/domain_a/default.sql"
DOMAIN_A_INSERT_SQL = f"{DB_SCRIPTS_ROOT}/domain_a/insert.sql"
DOMAIN_A_UPDATE_SQL = f"{DB_SCRIPTS_ROOT}/domain_a/update.sql"
DOMAIN_B_DEFAULT_SQL = f"{DB_SCRIPTS_ROOT}/domain_b/default.sql"
DOMAIN_B_UPDATE_SQL = f"{DB_SCRIPTS_ROOT}/domain_b/update.sql"

BACKEND_SOURCE_REPO_WINDOWS = r"C:\example\repos\backend-source"
BACKEND_TARGET_REPO_WINDOWS = r"C:\example\repos\backend-target"
BACKEND_SOURCE_REPO_BASH = "/c/example/repos/backend-source"
BACKEND_TARGET_REPO_BASH = "/c/example/repos/backend-target"
BACKEND_APP_ROOT = "backend_app"

sys.path.insert(0, str(BUILDER_ROOT))

from src.build_backend import (  # noqa: E402
    _add_run_all_includes_to_tar,
    _add_shell_runner_includes_to_tar,
    _cleanup_build_scripts,
    _create_db_migrations_archives,
    _create_db_sql_artifact,
    _ensure_backend_build_venv,
    _install_backend_build_requirements,
    _prepare_build_scripts,
    _run_additional_artifact_generators,
    _run_all_include_paths,
    _shell_runner_include_paths,
    build_backend,
)
from src.files import sync_source_top_level_items  # noqa: E402
from src.utils import add_file_to_tar  # noqa: E402


def load_create_run_all_sql_module():
    """Загружает генератор run_all SQL как отдельный модуль из builder scripts."""
    module_path = BUILDER_ROOT / "scripts" / "additional_artifacts" / "create_run_all_sql.py"
    spec = importlib.util.spec_from_file_location("create_run_all_sql", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildBackendArtifactTests(unittest.TestCase):
    """Проверяет builder-контракты, важные для самодостаточного release package."""

    def setUp(self):
        """Создает временный source repo и release dir для файловых builder-тестов."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.release_dir = self.root / "release"
        (self.repo / Path(APP_INSERT_SQL).parent).mkdir(parents=True)
        (self.repo / Path(APP_UPDATE_SQL).parent).mkdir(parents=True)
        self.release_dir.mkdir()

    def tearDown(self):
        """Удаляет временную файловую структуру builder-теста."""
        self.tmp.cleanup()

    def _write(self, relative_path, content="select 1;\n"):
        """Пишет файл в тестовый source repo и возвращает абсолютный путь."""
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _tar_names(self, archive_name):
        """Возвращает отсортированный список путей внутри тестового tar.gz архива."""
        with tarfile.open(self.release_dir / archive_name, "r:gz") as archive:
            return sorted(archive.getnames())

    def test_run_all_include_paths_are_limited_to_referenced_scripts(self):
        """В архив попадают только SQL-файлы, явно referenced из run_all."""
        first = self._write(APP_INSERT_SQL)
        second = self._write(APP_SECOND_INSERT_SQL)
        self._write(APP_UNUSED_UPDATE_SQL)
        run_all = self._write(
            f"run_all_insert_{TEST_COMMIT}.sql",
            "\\set ON_ERROR_STOP 1\n"
            f"\\i '{APP_INSERT_SQL}'\n"
            f"\\i \"{APP_SECOND_INSERT_SQL}\"\n",
        )

        self.assertEqual(
            _run_all_include_paths(self.repo, run_all),
            [
                first.relative_to(self.repo),
                second.relative_to(self.repo),
            ],
        )

    def test_insert_archive_contains_entrypoint_and_only_its_includes(self):
        """INSERT archive содержит entrypoint и только его include-зависимости."""
        self._write(APP_INSERT_SQL)
        self._write(APP_UNUSED_UPDATE_SQL)
        run_all = self._write(
            f"run_all_insert_{TEST_COMMIT}.sql",
            f"\\i '{APP_INSERT_SQL}'\n",
        )

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "insert",
            TEST_BUILD_VERSION,
            TEST_COMMIT,
            lambda archive: (
                add_file_to_tar(archive, run_all, run_all.name),
                _add_run_all_includes_to_tar(archive, self.repo, run_all),
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            [
                APP_INSERT_SQL,
                f"run_all_insert_{TEST_COMMIT}.sql",
            ],
        )

    def test_update_sequential_archive_contains_entrypoint_and_its_includes(self):
        """Sequential update archive содержит entrypoint и referenced SQL."""
        self._write(APP_UPDATE_SQL)
        run_all = self._write(
            f"run_all_update_sequential_{TEST_COMMIT}.sql",
            f"\\i '{APP_UPDATE_SQL}'\n",
        )

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "update_sequential",
            TEST_BUILD_VERSION,
            TEST_COMMIT,
            lambda archive: (
                add_file_to_tar(archive, run_all, run_all.name),
                _add_run_all_includes_to_tar(archive, self.repo, run_all),
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            [
                APP_UPDATE_SQL,
                f"run_all_update_sequential_{TEST_COMMIT}.sql",
            ],
        )

    def test_update_parallel_archive_contains_entrypoint_and_its_includes(self):
        """Parallel update archive добавляет SQL include из bash runner metadata."""
        first = self._write(APP_UPDATE_SQL)
        runner = self._write(
            f"run_all_update_parallel_{TEST_COMMIT}.sh",
            "#!/usr/bin/env bash\n"
            f"# simple-deploy-include: {APP_UPDATE_SQL}\n",
        )

        self.assertEqual(_shell_runner_include_paths(self.repo, runner), [first.relative_to(self.repo)])

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "update_parallel",
            TEST_BUILD_VERSION,
            TEST_COMMIT,
            lambda archive: (
                add_file_to_tar(archive, runner, runner.name),
                _add_shell_runner_includes_to_tar(archive, self.repo, runner),
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            [
                APP_UPDATE_SQL,
                f"run_all_update_parallel_{TEST_COMMIT}.sh",
            ],
        )

    def test_schema_archive_contains_only_summary_sql(self):
        """Schema archive содержит только summary SQL entrypoint без source tree."""
        summary_name = f"summary_sql_dev_2026_{TEST_COMMIT}.sql"
        summary = self._write(f"build_scripts/{summary_name}")

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "schema",
            TEST_BUILD_VERSION,
            TEST_COMMIT,
            lambda archive: add_file_to_tar(
                archive,
                summary,
                summary.name,
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            [summary_name],
        )

    def test_missing_include_fails(self):
        """Отсутствующий include в run_all приводит к ошибке сборки архива."""
        run_all = self._write(
            f"run_all_update_sequential_{TEST_COMMIT}.sql",
            f"\\i '{DB_SCRIPTS_ROOT}/app/update/missing.sql'\n",
        )

        with self.assertRaises(RuntimeError):
            _run_all_include_paths(self.repo, run_all)

    def test_build_scripts_directory_is_cleaned_after_generation(self):
        """Проверяет очистку временной build_scripts директории после подготовки."""
        stale_file = self._write("build_scripts/stale.sql")

        build_scripts_dir = _prepare_build_scripts(self.repo)

        self.assertTrue(build_scripts_dir.is_dir())
        self.assertFalse(stale_file.exists())
        self.assertTrue((build_scripts_dir / "create_sql_migrations.py").is_file())
        self.assertTrue((build_scripts_dir / "create_run_all_sql.py").is_file())

        _cleanup_build_scripts(build_scripts_dir)

        self.assertFalse(build_scripts_dir.exists())

    def test_run_all_preamble_contains_postgres_session_settings(self):
        """Фиксирует Postgres session settings в run_all INSERT entrypoint."""
        module = load_create_run_all_sql_module()
        out = io.StringIO()

        module.write_run_all_preamble(out, 1)
        out.write(f"\\i '{APP_INSERT_SQL}'\n")
        module.write_run_all_epilogue(out)
        content = out.getvalue()

        self.assertIn("\\set ON_ERROR_STOP 1\n", content)
        self.assertIn("\\timing on\n", content)
        for setting in module.PSQL_SESSION_SETTINGS:
            self.assertIn(f"{setting}\n", content)
        self.assertTrue(content.rstrip().endswith("SET synchronous_commit = ON;"))
        self.assertIn(f"\\i '{APP_INSERT_SQL}'\n", content)

    def test_update_sequential_preamble_uses_conservative_session_settings(self):
        """Фиксирует консервативные session settings для sequential update SQL."""
        module = load_create_run_all_sql_module()
        out = io.StringIO()

        module.write_run_all_preamble(out, 1, module.PSQL_SEQUENTIAL_SESSION_SETTINGS)
        content = out.getvalue()

        self.assertIn("\\set ON_ERROR_STOP 1\n", content)
        for setting in module.PSQL_SEQUENTIAL_SESSION_SETTINGS:
            self.assertIn(f"{setting}\n", content)
        self.assertNotIn("max_parallel_workers", content)
        self.assertNotIn("enable_parallel_hash", content)

    def test_run_all_generator_treats_drop_insert_as_idempotent(self):
        """Разрешает DROP plus INSERT сценарий как full-state idempotent data SQL."""
        module = load_create_run_all_sql_module()
        sql = self._write(
            FULL_STATE_INSERT_SQL,
            "DROP MATERIALIZED VIEW IF EXISTS public.some_owned_view;\n"
            "INSERT INTO public.some_owned_table (id) VALUES (1);\n",
        )

        self.assertTrue(module.check_idempotent(sql))

    def test_run_all_insert_files_use_forward_slash_paths(self):
        """Проверяет, что генератор возвращает archive paths через forward slash."""
        module = load_create_run_all_sql_module()
        old_base_dir = module.BASE_DIR
        old_scripts_dir = module.SCRIPTS_DIR
        module.BASE_DIR = str(self.repo)
        module.SCRIPTS_DIR = str(self.repo / DB_SCRIPTS_ROOT)
        try:
            insert_dir = self.repo / CATALOG_INSERT_DIR
            catalog_sql = f"{CATALOG_INSERT_DIR}/insert_catalog.sql"
            self._write(
                catalog_sql,
                "INSERT INTO public.catalog (id) VALUES (1) ON CONFLICT (id) DO NOTHING;\n",
            )

            self.assertEqual(
                module.find_sql_files(str(insert_dir), check_inserts=True, errors_list=[]),
                [catalog_sql],
            )
        finally:
            module.BASE_DIR = old_base_dir
            module.SCRIPTS_DIR = old_scripts_dir

    def test_metadata_files_are_split_by_update_and_set_default_kind(self):
        """Metadata выборки разделяют update и set_default, исключая INSERT."""
        module = load_create_run_all_sql_module()
        old_base_dir = module.BASE_DIR
        old_scripts_dir = module.SCRIPTS_DIR
        module.BASE_DIR = str(self.repo)
        module.SCRIPTS_DIR = str(self.repo / DB_SCRIPTS_ROOT)
        try:
            self._write(
                DOMAIN_B_UPDATE_SQL,
                "-- simple-deploy: kind=update\n"
                "-- simple-deploy: order=20\n"
                "-- simple-deploy: group=domain.b\n"
                "-- simple-deploy: parallel=true\n"
                "select 1;\n",
            )
            self._write(
                DOMAIN_A_DEFAULT_SQL,
                "-- simple-deploy: kind=set_default\n"
                "-- simple-deploy: order=10\n"
                "-- simple-deploy: group=domain.a\n"
                "-- simple-deploy: parallel=false\n"
                "select 1;\n",
            )
            self._write(
                DOMAIN_A_INSERT_SQL,
                "-- simple-deploy: kind=insert\n"
                "-- simple-deploy: order=1\n"
                "-- simple-deploy: group=domain.a\n"
                "-- simple-deploy: parallel=true\n"
                "select 1;\n",
            )
            self._write(
                INSERT_NEW_OBJECTS_UPDATE_SQL,
                "-- simple-deploy: kind=update\n"
                "-- simple-deploy: order=1\n"
                "-- simple-deploy: group=manual\n"
                "-- simple-deploy: parallel=true\n"
                "select 1;\n",
            )

            self.assertEqual(
                module.find_metadata_sql_files(module.UPDATE_KINDS),
                [DOMAIN_B_UPDATE_SQL],
            )
            self.assertEqual(
                module.find_metadata_sql_files(module.SET_DEFAULT_KINDS),
                [DOMAIN_A_DEFAULT_SQL],
            )
        finally:
            module.BASE_DIR = old_base_dir
            module.SCRIPTS_DIR = old_scripts_dir

    def test_update_parallel_runner_has_live_status_and_no_csv_output(self):
        """Проверяет live status update runner без set_default env-фильтра."""
        module = load_create_run_all_sql_module()
        entries = [
            {
                "kind": "update",
                "order": 10,
                "group": "domain.a",
                "parallel": "true",
                "path": str(Path(DOMAIN_A_UPDATE_SQL)),
                "archive_path": DOMAIN_A_UPDATE_SQL,
            },
        ]
        out = io.StringIO()

        module.write_update_parallel_runner(out, entries)
        content = out.getvalue()

        self.assertIn("#!/usr/bin/env bash\n", content)
        self.assertIn(f"# simple-deploy-include: {DOMAIN_A_UPDATE_SQL}\n", content)
        self.assertIn("DEFAULT_MAX_WORKERS=8", content)
        self.assertIn("DEFAULT_STATUS_INTERVAL_SECONDS=30", content)
        self.assertNotIn("SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT", content)
        self.assertIn("TASK_KINDS=(", content)
        self.assertNotIn("SKIP set_default scripts=", content)
        self.assertIn("RUNNER_KIND=update", content)
        self.assertIn("logs/$LOG_DIR_NAME/$run_id", content)
        self.assertIn("[START]", content)
        self.assertIn("[RUNNING]", content)
        self.assertIn("[$status]", content)
        self.assertIn("=== WAVE $CURRENT_WAVE start:", content)
        self.assertIn("Top slow scripts:", content)
        self.assertIn("total_duration=", content)
        self.assertIn("\\timing on", content)
        self.assertIn('if [[ "${TASK_PARALLEL[$idx]}" == "false" ]]', content)
        self.assertNotIn(".csv", content.lower())

        bash_path = shutil.which("bash")
        if bash_path:
            runner_path = self.root / "run_all_update_parallel_test.sh"
            runner_path.write_text(content, encoding="utf-8", newline="\n")
            subprocess.run([bash_path, "-n", str(runner_path)], check=True)

    def test_set_default_parallel_runner_uses_separate_kind_and_log_dir(self):
        """Фиксирует отдельный parallel runner для kind=set_default."""
        module = load_create_run_all_sql_module()
        entries = [
            {
                "kind": "set_default",
                "order": 10,
                "group": "domain.b",
                "parallel": "false",
                "path": str(Path(DOMAIN_B_DEFAULT_SQL)),
                "archive_path": DOMAIN_B_DEFAULT_SQL,
            },
        ]
        out = io.StringIO()

        module.write_set_default_parallel_runner(out, entries)
        content = out.getvalue()

        self.assertIn(f"# simple-deploy-include: {DOMAIN_B_DEFAULT_SQL}\n", content)
        self.assertIn("RUNNER_KIND=set_default", content)
        self.assertIn("LOG_DIR_NAME=set_default_parallel", content)
        self.assertIn("=== $RUNNER_TITLE PARALLEL DONE:", content)
        self.assertNotIn("SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT", content)
        self.assertNotIn("SKIP set_default", content)

        bash_path = shutil.which("bash")
        if bash_path:
            runner_path = self.root / "run_all_set_default_parallel_test.sh"
            runner_path.write_text(content, encoding="utf-8", newline="\n")
            subprocess.run([bash_path, "-n", str(runner_path)], check=True)

    def test_missing_backend_build_venv_is_created_in_source_repo(self):
        """Создает backend build venv внутри source repo, если activate.bat отсутствует."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        activate_path = source_repo / ".venv/Scripts/activate.bat"

        def fake_run_git_bash(*args, **kwargs):
            activate_path.parent.mkdir(parents=True)
            activate_path.write_text("", encoding="utf-8")

        env = {
            "BACKEND_BUILD_VENV_RELATIVE_PATH": ".venv/Scripts/activate.bat",
            "GIT_BASH_PATH": "bash",
        }
        with patch.dict("os.environ", env):
            with patch("src.build_backend._run_git_bash", side_effect=fake_run_git_bash) as run_mock:
                self.assertEqual(_ensure_backend_build_venv(source_repo), activate_path)

        args, kwargs = run_mock.call_args
        self.assertIn("python -m venv", args[0])
        self.assertIn("/.venv", args[0])
        self.assertEqual(kwargs["cwd"], source_repo)

    def test_artifact_generators_run_through_source_venv_python(self):
        """Запускает pip/schema/run_all generators через python из source repo venv."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        activate_path = source_repo / ".venv/Scripts/activate.bat"
        python_path = source_repo / ".venv/Scripts/python.exe"
        activate_path.parent.mkdir(parents=True)
        activate_path.write_text("", encoding="utf-8")
        python_path.write_text("", encoding="utf-8")
        (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
        build_scripts_dir = source_repo / "build_scripts"
        build_scripts_dir.mkdir()

        env = {
            "BACKEND_BUILD_VENV_RELATIVE_PATH": ".venv/Scripts/activate.bat",
            "GIT_BASH_PATH": "bash",
            "SIMPLE_DEPLOY_INCLUDE_DATA_SQL": "1",
        }
        with patch.dict("os.environ", env):
            with patch("src.build_backend._run_logged_command") as run_mock:
                _run_additional_artifact_generators(source_repo, build_scripts_dir)

        self.assertEqual(run_mock.call_count, 3)
        pip_install_args, pip_install_kwargs = run_mock.call_args_list[0]
        schema_args, schema_kwargs = run_mock.call_args_list[1]
        run_all_args, run_all_kwargs = run_mock.call_args_list[2]
        self.assertEqual(pip_install_args[0][0], str(python_path))
        self.assertEqual(pip_install_args[0][1:4], ["-m", "pip", "install"])
        self.assertIn("--disable-pip-version-check", pip_install_args[0])
        self.assertIn("-r", pip_install_args[0])
        self.assertIn(str(source_repo / "requirements.txt"), pip_install_args[0])
        self.assertIn("pypi.org", pip_install_args[0])
        self.assertIn("files.pythonhosted.org", pip_install_args[0])
        self.assertIn("pypi.python.org", pip_install_args[0])
        self.assertEqual(schema_args[0][0], str(python_path))
        self.assertIn("-Xutf8", schema_args[0])
        self.assertIn(str(build_scripts_dir / "create_sql_migrations.py"), schema_args[0])
        self.assertEqual(run_all_args[0][0], str(python_path))
        self.assertIn("-Xutf8", run_all_args[0])
        self.assertIn(str(build_scripts_dir / "create_run_all_sql.py"), run_all_args[0])
        self.assertEqual(pip_install_kwargs["cwd"], source_repo)
        self.assertEqual(schema_kwargs["cwd"], source_repo)
        self.assertEqual(run_all_kwargs["cwd"], source_repo)

    def test_artifact_generators_skip_data_sql_when_explicitly_disabled(self):
        """При SIMPLE_DEPLOY_INCLUDE_DATA_SQL=0 пропускает run_all data SQL generator."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        activate_path = source_repo / ".venv/Scripts/activate.bat"
        python_path = source_repo / ".venv/Scripts/python.exe"
        activate_path.parent.mkdir(parents=True)
        activate_path.write_text("", encoding="utf-8")
        python_path.write_text("", encoding="utf-8")
        (source_repo / "requirements.txt").write_text("Django==4.2\n", encoding="utf-8")
        build_scripts_dir = source_repo / "build_scripts"
        build_scripts_dir.mkdir()

        env = {
            "BACKEND_BUILD_VENV_RELATIVE_PATH": ".venv/Scripts/activate.bat",
            "GIT_BASH_PATH": "bash",
            "SIMPLE_DEPLOY_INCLUDE_DATA_SQL": "0",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("src.build_backend._run_logged_command") as run_mock:
                _run_additional_artifact_generators(source_repo, build_scripts_dir)

        self.assertEqual(run_mock.call_count, 2)
        self.assertIn(str(source_repo / "requirements.txt"), run_mock.call_args_list[0].args[0])
        self.assertIn(str(build_scripts_dir / "create_sql_migrations.py"), run_mock.call_args_list[1].args[0])
        called_commands = [" ".join(call.args[0]) for call in run_mock.call_args_list]
        self.assertFalse(any("create_run_all_sql.py" in command for command in called_commands))

    def test_missing_schema_metadata_reports_schema_generator_failure(self):
        """Отсутствие schema metadata после успешного generator запуска считается ошибкой."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        build_scripts_dir = source_repo / "build_scripts"
        build_scripts_dir.mkdir()
        python_path = source_repo / ".venv/Scripts/python.exe"

        with patch.dict("os.environ", {"RELEASE_ROOT_WINDOWS": str(self.release_dir)}, clear=True):
            with patch("src.build_backend.git_output", return_value=TEST_COMMIT):
                with patch("src.build_backend._prepare_build_scripts", return_value=build_scripts_dir):
                    with patch("src.build_backend._schema_baselines_json", return_value="{}"):
                        with patch("src.build_backend._prepare_backend_build_python", return_value=python_path):
                            with patch("src.build_backend._run_artifact_generator") as run_mock:
                                with self.assertRaisesRegex(
                                    RuntimeError,
                                    "Schema migration generator exited successfully but did not create metadata",
                                ):
                                    _create_db_migrations_archives(str(source_repo), TEST_BUILD_VERSION)

        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[2], "create_sql_migrations.py")

    def test_db_migrations_archives_skip_data_sql_when_explicitly_disabled(self):
        """Schema archives остаются, а data SQL archives не пишутся при явном skip."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        build_scripts_dir = source_repo / "build_scripts"
        build_scripts_dir.mkdir()
        python_path = source_repo / ".venv/Scripts/python.exe"

        def fake_run_artifact_generator(*args):
            script_name = args[2]
            self.assertEqual(script_name, "create_sql_migrations.py")
            metadata = {
                "contours": {
                    "dev": {"entrypoint": "summary_sql_dev_abc.sql"},
                    "test": {"entrypoint": "summary_sql_test_abc.sql"},
                    "prod": {"entrypoint": "summary_sql_prod_abc.sql"},
                }
            }
            (build_scripts_dir / "schema_migrations_metadata.json").write_text(
                json.dumps(metadata),
                encoding="utf-8",
            )
            for contour in ("dev", "test", "prod"):
                (build_scripts_dir / f"summary_sql_{contour}_abc.sql").write_text(
                    "select 1;\n",
                    encoding="utf-8",
                )

        env = {
            "RELEASE_ROOT_WINDOWS": str(self.release_dir),
            "SIMPLE_DEPLOY_INCLUDE_DATA_SQL": "0",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch("src.build_backend.git_output", return_value=TEST_COMMIT):
                with patch("src.build_backend._prepare_build_scripts", return_value=build_scripts_dir):
                    with patch("src.build_backend._schema_baselines_json", return_value="{}"):
                        with patch("src.build_backend._prepare_backend_build_python", return_value=python_path):
                            with patch(
                                "src.build_backend._run_artifact_generator",
                                side_effect=fake_run_artifact_generator,
                            ) as run_mock:
                                manifest = _create_db_migrations_archives(str(source_repo), TEST_BUILD_VERSION)

        run_mock.assert_called_once()
        self.assertFalse(manifest["db_data_sql_enabled"])
        self.assertNotIn("db_insert_archive", manifest)
        self.assertNotIn("db_update_sequential_archive", manifest)
        self.assertNotIn("db_update_parallel_archive", manifest)
        self.assertNotIn("db_set_default_sequential_archive", manifest)
        self.assertNotIn("db_set_default_parallel_archive", manifest)
        self.assertEqual(set(manifest["db_schema_archives"]), {"dev", "test", "prod"})

    def test_db_migrations_archives_include_data_sql_by_default(self):
        """По умолчанию builder добавляет schema, insert/update/set_default data SQL archives."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        build_scripts_dir = source_repo / "build_scripts"
        build_scripts_dir.mkdir()
        python_path = source_repo / ".venv/Scripts/python.exe"

        def fake_run_artifact_generator(*args):
            script_name = args[2]
            if script_name == "create_sql_migrations.py":
                metadata = {
                    "contours": {
                        "dev": {"entrypoint": "summary_sql_dev_abc.sql"},
                        "test": {"entrypoint": "summary_sql_test_abc.sql"},
                        "prod": {"entrypoint": "summary_sql_prod_abc.sql"},
                    }
                }
                (build_scripts_dir / "schema_migrations_metadata.json").write_text(
                    json.dumps(metadata),
                    encoding="utf-8",
                )
                for contour in ("dev", "test", "prod"):
                    (build_scripts_dir / f"summary_sql_{contour}_abc.sql").write_text(
                        "select 1;\n",
                        encoding="utf-8",
                    )
            elif script_name == "create_run_all_sql.py":
                (build_scripts_dir / f"run_all_insert_{TEST_COMMIT}.sql").write_text(
                    "\\set ON_ERROR_STOP 1\n",
                    encoding="utf-8",
                )
                (build_scripts_dir / f"run_all_update_sequential_{TEST_COMMIT}.sql").write_text(
                    "\\set ON_ERROR_STOP 1\n",
                    encoding="utf-8",
                )
                (build_scripts_dir / f"run_all_set_default_sequential_{TEST_COMMIT}.sql").write_text(
                    "\\set ON_ERROR_STOP 1\n",
                    encoding="utf-8",
                )
                update_sql = source_repo / APP_UPDATE_SQL
                update_sql.parent.mkdir(parents=True, exist_ok=True)
                update_sql.write_text("select 1;\n", encoding="utf-8")
                set_default_sql = source_repo / DOMAIN_A_DEFAULT_SQL
                set_default_sql.parent.mkdir(parents=True, exist_ok=True)
                set_default_sql.write_text("select 1;\n", encoding="utf-8")
                (build_scripts_dir / f"run_all_update_parallel_{TEST_COMMIT}.sh").write_text(
                    "#!/usr/bin/env bash\n"
                    f"# simple-deploy-include: {APP_UPDATE_SQL}\n",
                    encoding="utf-8",
                )
                (build_scripts_dir / f"run_all_set_default_parallel_{TEST_COMMIT}.sh").write_text(
                    "#!/usr/bin/env bash\n"
                    f"# simple-deploy-include: {DOMAIN_A_DEFAULT_SQL}\n",
                    encoding="utf-8",
                )

        with patch.dict("os.environ", {"RELEASE_ROOT_WINDOWS": str(self.release_dir)}, clear=True):
            with patch("src.build_backend.git_output", return_value=TEST_COMMIT):
                with patch("src.build_backend._prepare_build_scripts", return_value=build_scripts_dir):
                    with patch("src.build_backend._schema_baselines_json", return_value="{}"):
                        with patch("src.build_backend._prepare_backend_build_python", return_value=python_path):
                            with patch(
                                "src.build_backend._run_artifact_generator",
                                side_effect=fake_run_artifact_generator,
                            ) as run_mock:
                                manifest = _create_db_migrations_archives(str(source_repo), TEST_BUILD_VERSION)

        self.assertEqual(
            [call.args[2] for call in run_mock.call_args_list],
            ["create_sql_migrations.py", "create_run_all_sql.py"],
        )
        self.assertTrue(manifest["db_data_sql_enabled"])
        self.assertIn("db_insert_archive", manifest)
        self.assertNotIn("db_update_archive", manifest)
        self.assertIn("db_update_sequential_archive", manifest)
        self.assertIn("db_update_parallel_archive", manifest)
        self.assertIn("db_set_default_sequential_archive", manifest)
        self.assertIn("db_set_default_parallel_archive", manifest)

    def test_backend_build_requirements_path_can_be_configured(self):
        """Учитывает BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH при pip install."""
        source_repo = self.root / "source"
        source_repo.mkdir()
        requirements_path = source_repo / "requirements/prod.txt"
        requirements_path.parent.mkdir()
        requirements_path.write_text("Django==4.2\n", encoding="utf-8")
        python_path = source_repo / ".venv/Scripts/python.exe"
        python_path.parent.mkdir(parents=True)
        python_path.write_text("", encoding="utf-8")

        env = {
            "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH": "requirements/prod.txt",
            "GIT_BASH_PATH": "bash",
        }
        with patch.dict("os.environ", env):
            with patch("src.build_backend._run_logged_command") as run_mock:
                _install_backend_build_requirements(source_repo, python_path)

        self.assertEqual(run_mock.call_count, 1)
        self.assertIn(str(requirements_path), run_mock.call_args_list[0].args[0])

    def test_source_top_level_sync_preserves_target_only_items(self):
        """Синхронизация top-level source repo сохраняет target-only директории."""
        source_repo = self.root / "source"
        target_repo = self.root / "target"
        app_root = BACKEND_APP_ROOT
        source_repo.mkdir()
        target_repo.mkdir()

        (source_repo / app_root).mkdir()
        (source_repo / app_root / "app.py").write_text("new\n", encoding="utf-8")
        (target_repo / app_root).mkdir()
        (target_repo / app_root / "old.py").write_text("old\n", encoding="utf-8")

        (source_repo / "common.txt").write_text("new\n", encoding="utf-8")
        (target_repo / "common.txt").write_text("old\n", encoding="utf-8")

        (target_repo / "legacy_only").mkdir()
        (target_repo / "legacy_only" / "keep.sql").write_text("keep\n", encoding="utf-8")

        (source_repo / "archives").mkdir()
        (source_repo / "archives" / "source.tmp").write_text("skip\n", encoding="utf-8")
        (target_repo / "archives").mkdir()
        (target_repo / "archives" / "target.tmp").write_text("keep\n", encoding="utf-8")

        self.assertTrue(sync_source_top_level_items(source_repo, target_repo))

        self.assertTrue((target_repo / "legacy_only" / "keep.sql").is_file())
        self.assertTrue((target_repo / app_root / "app.py").is_file())
        self.assertFalse((target_repo / app_root / "old.py").exists())
        self.assertEqual((target_repo / "common.txt").read_text(encoding="utf-8"), "new\n")
        self.assertTrue((target_repo / "archives" / "target.tmp").is_file())
        self.assertFalse((target_repo / "archives" / "source.tmp").exists())

    def test_backend_build_overrides_archive_root_to_source_repo(self):
        """Перед упаковкой backend архивов archive root переопределяется на source repo."""
        env = {
            "BACKEND_SOURCE_REPO_PATH": BACKEND_SOURCE_REPO_WINDOWS,
            "BACKEND_TARGET_REPO_PATH": BACKEND_TARGET_REPO_WINDOWS,
            "BACKEND_REPO_ROOT_BASH": BACKEND_TARGET_REPO_BASH,
            "BACKEND_APP_ROOT_DIR": BACKEND_APP_ROOT,
            "GIT_BASH_PATH": "bash",
        }
        with patch.dict("os.environ", env):
            with patch("src.build_backend.check_repo", return_value=True):
                with patch("src.build_backend.git_checkout_dev", return_value=True):
                    with patch("src.build_backend.git_pull", return_value=True):
                        with patch("src.build_backend.git_checkout_new_branch", return_value=True):
                            with patch("src.build_backend.sync_source_top_level_items", return_value=True):
                                with patch("src.build_backend.git_add_commit_push", return_value=True):
                                    with patch("src.build_backend._create_db_migrations_archives", return_value={}):
                                        with patch("src.build_backend.subprocess.run") as run_mock:
                                            build_backend(TEST_BUILD_VERSION, TEST_RELEASE_BRANCH)

        archive_env = run_mock.call_args.kwargs["env"]
        self.assertEqual(archive_env["BACKEND_REPO_ROOT_BASH"], BACKEND_SOURCE_REPO_BASH)
        self.assertEqual(archive_env["BACKEND_APP_ROOT_DIR"], BACKEND_APP_ROOT)

    def test_backend_archive_script_excludes_python_cache(self):
        """Backend archive shell script исключает Python cache файлы."""
        script_path = BUILDER_ROOT / "scripts" / "archive_script_backend.sh"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn('--exclude="*/__pycache__/*"', content)
        self.assertIn('--exclude="*.pyc"', content)
        self.assertIn('--exclude="*.pyo"', content)


if __name__ == "__main__":
    unittest.main()
