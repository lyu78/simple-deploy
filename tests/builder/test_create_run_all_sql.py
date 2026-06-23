import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BUILDER_ROOT = ROOT / "tools-ci" / "builder"
DB_SCRIPTS_ROOT = "docs/database/scripts"


def load_create_run_all_sql_module():
    module_path = (
        BUILDER_ROOT
        / "scripts"
        / "additional_artifacts"
        / "create_run_all_sql.py"
    )
    spec = importlib.util.spec_from_file_location("create_run_all_sql", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop("create_run_all_sql", None)
    spec.loader.exec_module(module)
    return module


class CreateRunAllSqlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.scripts = self.repo / DB_SCRIPTS_ROOT
        self.scripts.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative_path: str, content: str) -> Path:
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _load_for_repo(self):
        module = load_create_run_all_sql_module()
        module.BASE_DIR = str(self.repo)
        module.SCRIPTS_DIR = str(self.scripts)
        module.SCRIPT_DIR = str(self.repo / "build_scripts")
        Path(module.SCRIPT_DIR).mkdir()
        module.COMMIT_HASH = "abc123"
        module.OUTPUT_INSERT = str(
            Path(module.SCRIPT_DIR) / "run_all_insert_abc123.sql"
        )
        module.OUTPUT_UPDATE_SEQUENTIAL = str(
            Path(module.SCRIPT_DIR) / "run_all_update_sequential_abc123.sql"
        )
        module.OUTPUT_UPDATE_PARALLEL = str(
            Path(module.SCRIPT_DIR) / "run_all_update_parallel_abc123.sh"
        )
        module.OUTPUT_SET_DEFAULT_SEQUENTIAL = str(
            Path(module.SCRIPT_DIR) / "run_all_set_default_sequential_abc123.sql"
        )
        module.OUTPUT_SET_DEFAULT_PARALLEL = str(
            Path(module.SCRIPT_DIR) / "run_all_set_default_parallel_abc123.sh"
        )
        return module

    def test_get_commit_hash_falls_back_to_unknown_on_git_error(self):
        module = load_create_run_all_sql_module()

        with patch.object(module.subprocess, "run", side_effect=OSError("boom")):
            self.assertEqual(module.get_commit_hash(), "unknown")

    def test_metadata_helpers_report_missing_and_invalid_values(self):
        module = load_create_run_all_sql_module()

        with self.assertRaisesRegex(RuntimeError, "Missing simple-deploy order"):
            module._metadata_order({}, "docs/database/scripts/a.sql")
        with self.assertRaisesRegex(RuntimeError, "Invalid simple-deploy order"):
            module._metadata_order({"order": "first"}, "docs/database/scripts/a.sql")
        with self.assertRaisesRegex(RuntimeError, "Missing or invalid"):
            module._metadata_parallel({}, "docs/database/scripts/a.sql")
        with self.assertRaisesRegex(RuntimeError, "Missing or invalid"):
            module._metadata_parallel(
                {"parallel": "sometimes"},
                "docs/database/scripts/a.sql",
            )
        self.assertEqual(module._metadata_parallel({"parallel": "TRUE"}, "x"), "true")

    def test_find_metadata_sql_entries_validates_required_group(self):
        module = self._load_for_repo()
        self._write(
            f"{DB_SCRIPTS_ROOT}/domain/update.sql",
            "-- simple-deploy: kind=update\n"
            "-- simple-deploy: order=10\n"
            "-- simple-deploy: parallel=true\n"
            "select 1;\n",
        )

        with self.assertRaisesRegex(RuntimeError, "Missing simple-deploy group"):
            module.find_metadata_sql_entries(module.UPDATE_KINDS)

    def test_find_sql_files_reports_non_idempotent_inserts_and_skips_set_default(self):
        module = self._load_for_repo()
        insert_dir = self.scripts / "app_ip_subcompany"
        non_idempotent = (
            f"{DB_SCRIPTS_ROOT}/app_ip_subcompany/insert_01/plain_insert.sql"
        )
        set_default = (
            f"{DB_SCRIPTS_ROOT}/app_ip_subcompany/set_default/default.sql"
        )
        self._write(
            non_idempotent,
            "INSERT INTO public.catalog (id) VALUES (1);\n",
        )
        self._write(
            set_default,
            "INSERT INTO public.defaults (id) VALUES (1);\n",
        )
        errors = []

        with patch("builtins.print") as print_mock:
            files = module.find_sql_files(
                str(insert_dir),
                include_insert_only=True,
                check_inserts=True,
                errors_list=errors,
            )

        self.assertEqual(files, [non_idempotent])
        self.assertEqual(errors, [non_idempotent])
        self.assertTrue(
            any("NOT IDEMPOTENT" in call.args[0] for call in print_mock.call_args_list)
        )

    def test_shell_helpers_quote_arrays_and_psql_session_arguments(self):
        module = load_create_run_all_sql_module()

        array = module._shell_array("VALUES", ["plain", "two words", "it's"])
        psql_args = module._psql_session_args(["SET work_mem = '64MB';"])

        self.assertIn("VALUES=(", array)
        self.assertIn("plain", array)
        self.assertIn("'two words'", array)
        self.assertIn("'it'\"'\"'s'", array)
        self.assertIn("PSQL_SESSION_ARGS=(", psql_args)
        self.assertIn("ON_ERROR_STOP=1", psql_args)
        self.assertIn("\\timing on", psql_args)
        self.assertIn("'SET work_mem = '\"'\"'64MB'\"'\"';'", psql_args)

    def test_check_idempotent_accepts_sql_without_insert(self):
        module = self._load_for_repo()
        sql = self._write(
            f"{DB_SCRIPTS_ROOT}/domain/read_only.sql",
            "UPDATE public.table SET name = 'x';\n",
        )

        self.assertTrue(module.check_idempotent(sql))

    def test_write_parallel_runner_renders_empty_task_arrays(self):
        module = load_create_run_all_sql_module()
        out = io.StringIO()

        module.write_parallel_runner(out, [], "update", "UPDATE", "update_parallel")

        content = out.getvalue()
        self.assertIn("TASK_ORDERS=(\n)", content)
        self.assertIn("TASK_PATHS=(\n)", content)
        self.assertIn("die \"No $RUNNER_KIND scripts are enabled", content)

    def test_main_generates_all_run_all_entrypoints(self):
        module = self._load_for_repo()
        module.INSERT_DIRS = ["app_ip_subcompany_catalogs"]
        module.MIXED_DIRS = ["app_ip_subcompany"]
        self._write(
            f"{DB_SCRIPTS_ROOT}/app_ip_subcompany_catalogs/catalog.sql",
            "INSERT INTO public.catalog (id) VALUES (1) ON CONFLICT DO NOTHING;\n",
        )
        self._write(
            f"{DB_SCRIPTS_ROOT}/app_ip_subcompany/insert_01/insert.sql",
            "TRUNCATE TABLE public.data;\n"
            "INSERT INTO public.data (id) VALUES (1);\n",
        )
        self._write(
            f"{DB_SCRIPTS_ROOT}/domain/update.sql",
            "-- simple-deploy: kind=update\n"
            "-- simple-deploy: order=20\n"
            "-- simple-deploy: group=domain\n"
            "-- simple-deploy: parallel=true\n"
            "select 1;\n",
        )
        self._write(
            f"{DB_SCRIPTS_ROOT}/domain/default.sql",
            "-- simple-deploy: kind=set_default\n"
            "-- simple-deploy: order=10\n"
            "-- simple-deploy: group=domain\n"
            "-- simple-deploy: parallel=false\n"
            "select 1;\n",
        )

        with patch("builtins.print"):
            module.main()

        output_insert = Path(module.OUTPUT_INSERT).read_text(encoding="utf-8")
        output_update_sequential = Path(
            module.OUTPUT_UPDATE_SEQUENTIAL
        ).read_text(encoding="utf-8")
        output_update_parallel = Path(module.OUTPUT_UPDATE_PARALLEL).read_text(
            encoding="utf-8"
        )
        output_set_default_sequential = Path(
            module.OUTPUT_SET_DEFAULT_SEQUENTIAL
        ).read_text(encoding="utf-8")
        output_set_default_parallel = Path(
            module.OUTPUT_SET_DEFAULT_PARALLEL
        ).read_text(encoding="utf-8")

        self.assertIn("app_ip_subcompany_catalogs/catalog.sql", output_insert)
        self.assertIn("app_ip_subcompany/insert_01/insert.sql", output_insert)
        self.assertIn("SET synchronous_commit = ON;", output_insert)
        self.assertIn("docs/database/scripts/domain/update.sql", output_update_sequential)
        self.assertIn(
            "# simple-deploy-include: docs/database/scripts/domain/update.sql",
            output_update_parallel,
        )
        self.assertIn(
            "docs/database/scripts/domain/default.sql",
            output_set_default_sequential,
        )
        self.assertIn(
            "# simple-deploy-include: docs/database/scripts/domain/default.sql",
            output_set_default_parallel,
        )

    def test_main_exits_after_reporting_non_idempotent_insert_scripts(self):
        module = self._load_for_repo()
        module.INSERT_DIRS = ["app_ip_subcompany_catalogs"]
        module.MIXED_DIRS = []
        self._write(
            f"{DB_SCRIPTS_ROOT}/app_ip_subcompany_catalogs/plain_insert.sql",
            "INSERT INTO public.catalog (id) VALUES (1);\n",
        )

        with patch("builtins.print") as print_mock:
            with self.assertRaises(SystemExit) as cm:
                module.main()

        self.assertEqual(cm.exception.code, 1)
        output = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("non-idempotent INSERT", output)
        self.assertIn("plain_insert.sql", output)


if __name__ == "__main__":
    unittest.main()
