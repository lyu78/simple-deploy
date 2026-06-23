import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BUILDER_ROOT = ROOT / "tools-ci" / "builder"

sys.path.insert(0, str(BUILDER_ROOT))

from src.files import (  # noqa: E402
    check_repo,
    clear_directory_contents,
    copy_directory_contents,
    copy_file_to_repo2,
    sync_source_top_level_items,
)


class BuilderFileTests(unittest.TestCase):
    def test_clear_directory_contents_preserves_git_and_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".venv").mkdir()
            (root / "remove.txt").write_text("x", encoding="utf-8")
            (root / "remove_dir").mkdir()
            (root / "remove_dir" / "nested.txt").write_text(
                "x", encoding="utf-8"
            )

            self.assertTrue(clear_directory_contents(str(root)))

            self.assertTrue((root / ".git").is_dir())
            self.assertTrue((root / ".venv").is_dir())
            self.assertFalse((root / "remove.txt").exists())
            self.assertFalse((root / "remove_dir").exists())

    def test_clear_directory_contents_returns_false_for_missing_path(self):
        self.assertFalse(clear_directory_contents("missing-directory"))

    def test_clear_directory_contents_returns_false_on_filesystem_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("x", encoding="utf-8")

            with patch("src.files.os.listdir", side_effect=OSError("boom")):
                self.assertFalse(clear_directory_contents(str(root)))

            with patch("src.files.os.remove", side_effect=OSError("boom")):
                self.assertFalse(clear_directory_contents(str(root)))

            (root / "dir").mkdir(exist_ok=True)
            with patch("src.files.shutil.rmtree", side_effect=OSError("boom")):
                self.assertFalse(clear_directory_contents(str(root)))

    def test_copy_directory_contents_skips_excluded_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "keep.txt").write_text("keep", encoding="utf-8")
            (source / "node_modules").mkdir()
            (source / "node_modules" / "skip.txt").write_text(
                "skip", encoding="utf-8"
            )
            (source / "dir").mkdir()
            (source / "dir" / "nested.txt").write_text(
                "nested", encoding="utf-8"
            )

            self.assertTrue(copy_directory_contents(str(source), str(target)))

            self.assertEqual(
                (target / "keep.txt").read_text(encoding="utf-8"), "keep"
            )
            self.assertTrue((target / "dir" / "nested.txt").is_file())
            self.assertFalse((target / "node_modules").exists())

    def test_copy_directory_contents_returns_false_when_target_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()

            self.assertFalse(
                copy_directory_contents(str(source), str(Path(tmp) / "missing"))
            )

    def test_copy_directory_contents_returns_false_on_source_and_copy_errors(self):
        self.assertFalse(copy_directory_contents("missing-source", "target"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "file.txt").write_text("x", encoding="utf-8")
            (source / "dir").mkdir()

            with patch("src.files.os.listdir", side_effect=OSError("boom")):
                self.assertFalse(copy_directory_contents(str(source), str(target)))

            with patch("src.files.shutil.copy2", side_effect=OSError("boom")):
                self.assertFalse(copy_directory_contents(str(source), str(target)))

            (source / "file.txt").unlink()
            with patch("src.files.shutil.copytree", side_effect=OSError("boom")):
                self.assertFalse(copy_directory_contents(str(source), str(target)))

    def test_sync_source_top_level_items_replaces_only_source_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "file.txt").write_text("new", encoding="utf-8")
            (source / "dir").mkdir()
            (source / "dir" / "nested.txt").write_text("new", encoding="utf-8")
            (source / "build").mkdir()
            (source / "build" / "skip.txt").write_text("skip", encoding="utf-8")
            (target / "file.txt").write_text("old", encoding="utf-8")
            (target / "target_only.txt").write_text("keep", encoding="utf-8")

            self.assertTrue(sync_source_top_level_items(str(source), str(target)))

            self.assertEqual(
                (target / "file.txt").read_text(encoding="utf-8"), "new"
            )
            self.assertEqual(
                (target / "target_only.txt").read_text(encoding="utf-8"),
                "keep",
            )
            self.assertTrue((target / "dir" / "nested.txt").is_file())
            self.assertFalse((target / "build").exists())

    def test_sync_source_top_level_items_returns_false_for_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()

            self.assertFalse(
                sync_source_top_level_items(str(Path(tmp) / "missing"), str(target))
            )

    def test_sync_source_top_level_items_returns_false_on_target_and_io_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            (source / "file.txt").write_text("x", encoding="utf-8")

            self.assertFalse(sync_source_top_level_items(str(source), str(target)))

            target.mkdir()
            with patch("src.files.os.listdir", side_effect=OSError("boom")):
                self.assertFalse(sync_source_top_level_items(str(source), str(target)))

            (target / "file.txt").write_text("old", encoding="utf-8")
            with patch("src.files._remove_path", side_effect=OSError("boom")):
                self.assertFalse(sync_source_top_level_items(str(source), str(target)))

            (target / "file.txt").unlink()
            with patch("src.files.shutil.copy2", side_effect=OSError("boom")):
                self.assertFalse(sync_source_top_level_items(str(source), str(target)))

    def test_copy_file_to_repo2_uses_basename_and_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            source_dir = root / "source"
            source_dir.mkdir()
            source_file = source_dir / "local.env"
            source_file.write_text("VALUE=1", encoding="utf-8")

            with patch("os.getcwd", return_value=str(root)):
                self.assertFalse(copy_file_to_repo2(str(target), "missing.env"))

            with patch("os.getcwd", return_value=str(root)):
                self.assertTrue(
                    copy_file_to_repo2(str(target), "source\\local.env")
                )

            self.assertEqual(
                (target / "local.env").read_text(encoding="utf-8"),
                "VALUE=1",
            )

    def test_copy_file_to_repo2_rejects_directory_source_and_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "folder").mkdir()
            (root / "local.env").write_text("VALUE=1", encoding="utf-8")
            with patch("os.getcwd", return_value=str(root)):
                self.assertFalse(copy_file_to_repo2(str(root), "folder"))
                self.assertFalse(
                    copy_file_to_repo2(str(root / "missing-target"), "local.env")
                )

    def test_copy_file_to_repo2_returns_false_when_copy_fails_or_target_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            (root / "local.env").write_text("VALUE=1", encoding="utf-8")

            with patch("os.getcwd", return_value=str(root)):
                with patch("src.files.shutil.copy2", return_value=None):
                    self.assertFalse(copy_file_to_repo2(str(target), "local.env"))

            with patch("os.getcwd", return_value=str(root)):
                with patch("src.files.shutil.copy2", side_effect=OSError("boom")):
                    self.assertFalse(copy_file_to_repo2(str(target), "local.env"))

    def test_check_repo_requires_git_directory(self):
        self.assertFalse(check_repo("missing-repo"))

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertFalse(check_repo(str(repo)))

            (repo / ".git").mkdir()
            self.assertTrue(check_repo(str(repo)))
