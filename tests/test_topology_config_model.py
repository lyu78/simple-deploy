"""Тесты read/config моделей source и deployment topology."""

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.config.topology import runtime_topology_config_model


class TopologyConfigModelTests(unittest.TestCase):
    """Проверяет структурные модели будущей topology config без runtime effects."""

    def test_topology_config_model_accepts_domain_vocabulary(self):
        """Topology config model нормализует известные domain values."""
        model = runtime_topology_config_model(
            {
                "source_origins": [
                    {
                        "origin_id": "backend-primary",
                        "kind": "PRIMARY_REMOTE",
                        "remote_url": "git@example.local/backend.git",
                    }
                ],
                "source_repositories": [
                    {
                        "repo_id": "backend",
                        "role": "backend",
                        "default_origin_id": "backend-primary",
                        "fallback_origin_ids": ["backend-mirror"],
                    }
                ],
                "components": [
                    {
                        "component_id": "BACKEND",
                        "source_repository_ids": ["backend"],
                        "target_roles": ["backend"],
                    }
                ],
                "machines": [
                    {
                        "machine_id": "dev-app-01",
                        "role": "app",
                        "hostname": "dev-app.example.local",
                        "ssh_user": "deploy",
                    }
                ],
                "landscapes": [
                    {
                        "contour": "DEV",
                        "targets": [
                            {
                                "target_id": "dev-backend",
                                "role": "BACKEND",
                                "machine_id": "dev-app-01",
                                "remote_path": "/opt/app/backend",
                            }
                        ],
                    }
                ],
                "execution_environments": [
                    {
                        "environment_id": "dev-contour",
                        "kind": "contour_bound",
                        "machine_ids": ["dev-app-01"],
                        "contour": "dev",
                        "target_ids": ["dev-backend"],
                    }
                ],
            }
        )

        self.assertEqual(model.source_origins[0].kind, "primary_remote")
        self.assertEqual(model.components[0].component_id, "backend")
        self.assertEqual(model.landscapes[0].contour, "dev")
        self.assertEqual(model.landscapes[0].targets[0].role, "backend")

        with self.assertRaises(ValidationError):
            model.components = []

    def test_topology_config_model_rejects_unknown_domain_values(self):
        """Topology config model отклоняет неизвестные справочники и path-like ids."""
        with self.assertRaises(ValidationError) as context:
            runtime_topology_config_model(
                {
                    "source_origins": [
                        {
                            "origin_id": "backend-primary",
                            "kind": "ftp_remote",
                            "remote_url": "git@example.local/backend.git",
                        }
                    ],
                    "components": [{"component_id": "worker"}],
                    "machines": [
                        {
                            "machine_id": "../dev-app",
                            "role": "app",
                            "hostname": "dev-app.example.local",
                            "ssh_user": "deploy",
                        }
                    ],
                    "landscapes": [
                        {
                            "contour": "stage",
                            "targets": [
                                {
                                    "target_id": "stage-backend",
                                    "role": "worker",
                                    "machine_id": "stage-app-01",
                                }
                            ],
                        }
                    ],
                }
            )

        error_text = str(context.exception)
        self.assertIn("source_origins", error_text)
        self.assertIn("components", error_text)
        self.assertIn("machines", error_text)
        self.assertIn("landscapes", error_text)


if __name__ == "__main__":
    unittest.main()
