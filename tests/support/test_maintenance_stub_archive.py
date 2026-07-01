"""Tests for the bundled maintenance stub archive."""

import tarfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE_STUB_ARCHIVE = (
    ROOT / "tools-ci" / "maintenance_stub" / "maintenance_stub.tar.gz"
)


class MaintenanceStubArchiveTests(unittest.TestCase):
    def test_default_archive_uses_absolute_asset_paths(self):
        """Stub assets must load when nginx falls back to index.html on nested URLs."""
        with tarfile.open(MAINTENANCE_STUB_ARCHIVE, "r:gz") as archive:
            names = set(archive.getnames())
            index_file = archive.extractfile("build/index.html")
            self.assertIsNotNone(index_file)
            index_html = index_file.read().decode("utf-8")

        self.assertIn("build/index.html", names)
        self.assertIn('src="/assets/', index_html)
        self.assertIn('href="/assets/', index_html)
        self.assertNotIn('src="./assets/', index_html)
        self.assertNotIn('href="./assets/', index_html)


if __name__ == "__main__":
    unittest.main()
