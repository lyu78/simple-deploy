import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder"))

from src.infra import get_new_build_version  # noqa: E402


class InfraTests(unittest.TestCase):
    def test_new_build_version_includes_minutes(self):
        with patch("src.infra.get_required_env", return_value="1.2.3"):
            with patch("src.infra.datetime") as datetime_mock:
                datetime_mock.now.return_value = datetime(2026, 5, 30, 14, 37, 12)

                self.assertEqual(get_new_build_version(), "1.2.3.30052026_1437")


if __name__ == "__main__":
    unittest.main()
