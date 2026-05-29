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
    _install_backend_build_requirements,
    _prepare_build_scripts,
    _run_additional_artifact_generators,
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

    def test_build_scripts_directory_is_kept_for_debug(self):
        stale_file = self._write("build_scripts/stale.sql")

        build_scripts_dir = _prepare_build_scripts(self.repo)

        self.assertTrue(build_scripts_dir.is_dir())
        self.assertFalse(stale_file.exists())
        self.assertTrue((build_scripts_dir / "create_sql_migrations.py").is_file())
        self.assertTrue((build_scripts_dir / "create_run_all_sql.py").is_file())

        _cleanup_build_scripts(build_scripts_dir)

        self.assertTrue(build_scripts_dir.exists())

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

    def test_artifact_generators_run_through_git_bash_with_source_venv_python(self):
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
        }
        with patch.dict("os.environ", env):
            with patch("src.build_backend._run_git_bash") as run_mock:
                _run_additional_artifact_generators(source_repo, build_scripts_dir)

        self.assertEqual(run_mock.call_count, 4)
        pip_upgrade_args, pip_upgrade_kwargs = run_mock.call_args_list[0]
        pip_install_args, pip_install_kwargs = run_mock.call_args_list[1]
        first_args, first_kwargs = run_mock.call_args_list[2]
        second_args, second_kwargs = run_mock.call_args_list[3]
        self.assertIn("/.venv/Scripts/python.exe", pip_upgrade_args[0])
        self.assertIn("-m pip install", pip_upgrade_args[0])
        self.assertIn("--trusted-host pypi.org", pip_upgrade_args[0])
        self.assertIn("--upgrade pip", pip_upgrade_args[0])
        self.assertIn("/.venv/Scripts/python.exe", pip_install_args[0])
        self.assertIn("-r", pip_install_args[0])
        self.assertIn("requirements.txt", pip_install_args[0])
        self.assertIn("--trusted-host files.pythonhosted.org", pip_install_args[0])
        self.assertIn("/.venv/Scripts/python.exe", first_args[0])
        self.assertIn("-Xutf8", first_args[0])
        self.assertIn("build_scripts/create_sql_migrations.py", first_args[0])
        self.assertIn("/.venv/Scripts/python.exe", second_args[0])
        self.assertIn("-Xutf8", second_args[0])
        self.assertIn("build_scripts/create_run_all_sql.py", second_args[0])
        self.assertEqual(pip_upgrade_kwargs["cwd"], source_repo)
        self.assertEqual(pip_install_kwargs["cwd"], source_repo)
        self.assertEqual(first_kwargs["cwd"], source_repo)
        self.assertEqual(second_kwargs["cwd"], source_repo)

    def test_backend_build_requirements_path_can_be_configured(self):
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
            with patch("src.build_backend._run_git_bash") as run_mock:
                _install_backend_build_requirements(source_repo, python_path)

        self.assertEqual(run_mock.call_count, 2)
        self.assertIn("requirements/prod.txt", run_mock.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
