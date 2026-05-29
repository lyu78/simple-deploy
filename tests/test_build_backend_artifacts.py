import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))

from src.build_backend import (  # noqa: E402
    _add_run_all_includes_to_tar,
    _cleanup_build_scripts,
    _create_db_sql_artifact,
    _ensure_backend_build_venv,
    _prepare_build_scripts,
    _run_all_include_paths,
)
from src.utils import add_file_to_tar  # noqa: E402


def load_create_run_all_sql_module():
    module_path = ROOT / "builder" / "scripts" / "additional_artifacts" / "create_run_all_sql.py"
    spec = importlib.util.spec_from_file_location("create_run_all_sql", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildBackendArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.release_dir = self.root / "release"
        (self.repo / "docs/database/scripts/app/insert").mkdir(parents=True)
        (self.repo / "docs/database/scripts/app/update").mkdir(parents=True)
        (self.repo / "docs/database/summary").mkdir(parents=True)
        self.release_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative_path, content="select 1;\n"):
        path = self.repo / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _tar_names(self, archive_name):
        with tarfile.open(self.release_dir / archive_name, "r:gz") as archive:
            return sorted(archive.getnames())

    def test_run_all_include_paths_are_limited_to_referenced_scripts(self):
        first = self._write("docs/database/scripts/app/insert/a.sql")
        second = self._write("docs/database/scripts/app/insert/b.sql")
        self._write("docs/database/scripts/app/update/not_used.sql")
        run_all = self._write(
            "run_all_insert_abc123.sql",
            "\\set ON_ERROR_STOP 1\n"
            "\\i 'docs/database/scripts/app/insert/a.sql'\n"
            "\\i \"docs/database/scripts/app/insert/b.sql\"\n",
        )

        self.assertEqual(
            _run_all_include_paths(self.repo, run_all),
            [
                first.relative_to(self.repo),
                second.relative_to(self.repo),
            ],
        )

    def test_insert_archive_contains_entrypoint_and_only_its_includes(self):
        self._write("docs/database/scripts/app/insert/a.sql")
        self._write("docs/database/scripts/app/update/not_used.sql")
        run_all = self._write(
            "run_all_insert_abc123.sql",
            "\\i 'docs/database/scripts/app/insert/a.sql'\n",
        )

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "insert",
            "1.2.3",
            "abc123",
            lambda archive: (
                add_file_to_tar(archive, run_all, run_all.name),
                _add_run_all_includes_to_tar(archive, self.repo, run_all),
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            [
                "docs/database/scripts/app/insert/a.sql",
                "run_all_insert_abc123.sql",
            ],
        )

    def test_schema_archive_contains_only_summary_sql(self):
        summary = self._write("docs/database/summary/summary_sql_2026_abc123.sql")

        archive_name = _create_db_sql_artifact(
            self.release_dir,
            "schema",
            "1.2.3",
            "abc123",
            lambda archive: add_file_to_tar(
                archive,
                summary,
                f"docs/database/summary/{summary.name}",
            ),
        )

        self.assertEqual(
            self._tar_names(archive_name),
            ["docs/database/summary/summary_sql_2026_abc123.sql"],
        )

    def test_missing_include_fails(self):
        run_all = self._write(
            "run_all_update_abc123.sql",
            "\\i 'docs/database/scripts/app/update/missing.sql'\n",
        )

        with self.assertRaises(RuntimeError):
            _run_all_include_paths(self.repo, run_all)

    def test_build_scripts_directory_is_transient(self):
        stale_file = self._write("build_scripts/stale.sql")

        build_scripts_dir = _prepare_build_scripts(self.repo)

        self.assertTrue(build_scripts_dir.is_dir())
        self.assertFalse(stale_file.exists())
        self.assertTrue((build_scripts_dir / "create_sql_migrations.py").is_file())
        self.assertTrue((build_scripts_dir / "create_run_all_sql.py").is_file())

        _cleanup_build_scripts(build_scripts_dir)

        self.assertFalse(build_scripts_dir.exists())

    def test_run_all_preamble_contains_postgres_session_settings(self):
        module = load_create_run_all_sql_module()
        out = io.StringIO()

        module.write_run_all_preamble(out, 1)
        out.write("\\i 'docs/database/scripts/app/insert/a.sql'\n")
        module.write_run_all_epilogue(out)
        content = out.getvalue()

        self.assertIn("\\set ON_ERROR_STOP 1\n", content)
        self.assertIn("\\timing on\n", content)
        for setting in module.PSQL_SESSION_SETTINGS:
            self.assertIn(f"{setting}\n", content)
        self.assertTrue(content.rstrip().endswith("SET synchronous_commit = ON;"))
        self.assertIn("\\i 'docs/database/scripts/app/insert/a.sql'\n", content)

    def test_missing_backend_build_venv_is_created_in_source_repo(self):
        source_repo = self.root / "source"
        source_repo.mkdir()
        activate_path = source_repo / ".venv/Scripts/activate.bat"

        def fake_run(*args, **kwargs):
            activate_path.parent.mkdir(parents=True)
            activate_path.write_text("", encoding="utf-8")

        with patch.dict("os.environ", {"BACKEND_BUILD_VENV_RELATIVE_PATH": ".venv/Scripts/activate.bat"}):
            with patch("src.build_backend.subprocess.run", side_effect=fake_run) as run_mock:
                self.assertEqual(_ensure_backend_build_venv(source_repo), activate_path)

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][1:3], ["-m", "venv"])
        self.assertEqual(Path(args[0][3]), source_repo / ".venv")
        self.assertEqual(kwargs["cwd"], source_repo)


if __name__ == "__main__":
    unittest.main()
