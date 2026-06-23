"""Тесты Pydantic-модели runtime config."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
RUNTIME_EXAMPLE_PATH = TOOLS_CI_ROOT / "windows_pipeline.example.json"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.config.runtime import runtime_config_model  # noqa: E402
from simple_deploy.config.runtime_loader import (  # noqa: E402
    load_runtime_config_model,
)


class RuntimeConfigModelTests(unittest.TestCase):
    """Проверяет структурную модель ``tools-ci/windows_pipeline.local.json``."""

    def test_example_runtime_config_matches_pydantic_model(self):
        """Example runtime config проходит структурную Pydantic-валидацию."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))

        model = runtime_config_model(runtime)

        self.assertTrue(model.maintenance_stub_enabled)
        self.assertEqual(model.sql_scripts[0].phase, "after_migrate")
        self.assertEqual(model.service_steps[-1].phase, "after_frontend_unpack")

    def test_load_runtime_config_model_keeps_defaulted_keys_contract(self):
        """Typed loader сохраняет старый defaulted_keys contract."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "windows_pipeline.local.json"
            config_path.write_text('{"backup_enabled": true}\n', encoding="utf-8")

            model, defaulted_keys = load_runtime_config_model(config_path)

        self.assertTrue(model.backup_enabled)
        self.assertIn("db_maintenance_sql_timeout_seconds", defaulted_keys)
        self.assertNotIn("backup_enabled", defaulted_keys)

    def test_runtime_config_model_rejects_structural_type_errors(self):
        """RuntimeConfigModel отклоняет нестрогие bool/int и пустые required strings."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["healthcheck_enabled"] = "true"
        runtime["healthcheck_retries"] = "30"
        runtime["db_psql_bin"] = " "

        with self.assertRaises(ValidationError) as context:
            runtime_config_model(runtime)

        error_text = str(context.exception)
        self.assertIn("healthcheck_enabled", error_text)
        self.assertIn("healthcheck_retries", error_text)
        self.assertIn("db_psql_bin", error_text)

    def test_runtime_config_model_allows_unknown_keys_for_loader_compatibility(self):
        """Первый config-срез сохраняет старый контракт unknown runtime keys."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["future_key"] = "future value"

        model = runtime_config_model(runtime)

        self.assertEqual(model.model_extra["future_key"], "future value")

    def test_runtime_config_model_rejects_unknown_phases_structurally(self):
        """Фазы SQL и service steps проверяются на уровне schema."""
        runtime = json.loads(RUNTIME_EXAMPLE_PATH.read_text(encoding="utf-8"))
        runtime["sql_scripts"] = [
            {
                "path": "tools-ci/sql/reports/public_table_size_report.sql",
                "phase": "during_deploy",
            }
        ]
        runtime["service_steps"] = [{"command": "echo ok", "phase": "during_deploy"}]

        with self.assertRaises(ValidationError) as context:
            runtime_config_model(runtime)

        error_text = str(context.exception)
        self.assertIn("sql_scripts", error_text)
        self.assertIn("service_steps", error_text)


if __name__ == "__main__":
    unittest.main()
