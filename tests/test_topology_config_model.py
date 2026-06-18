"""Тесты read/config моделей source и deployment topology."""

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.config.topology import runtime_topology_config_model, runtime_topology_from_legacy_env


class TopologyConfigModelTests(unittest.TestCase):
    """Проверяет структурные модели будущей topology config без runtime effects."""

    def test_topology_config_model_accepts_domain_vocabulary(self):
        """Topology config model принимает точные domain values."""
        model = runtime_topology_config_model(
            {
                "source_origins": [
                    {
                        "origin_id": "backend-primary",
                        "kind": "primary_remote",
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
                        "component_id": "backend",
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
                        "contour": "dev",
                        "targets": [
                            {
                                "target_id": "dev-backend",
                                "role": "backend",
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

    def test_runtime_topology_from_legacy_env_builds_dev_topology(self):
        """Legacy env adapter returns a read-only DEV topology view."""
        model = runtime_topology_from_legacy_env(
            {
                "BACKEND_SOURCE_REPO_PATH": " C:/repos/backend ",
                "FRONTEND_SOURCE_REPO_PATH": "C:/repos/frontend",
                "APP_VM_HOST": "dev-app.example.local",
                "APP_VM_USER": "deploy",
                "APP_WORKDIR": "/opt/simple-deploy",
                "APP_SSH_KEY_PATH": "C:/keys/app.pem",
                "DB_VM_HOST": "dev-db.example.local",
                "DB_VM_USER": "postgres",
                "DB_SSH_KEY_PATH": "C:/keys/db.pem",
                "BACKEND_RELEASE_PATH": "/srv/backend",
                "FRONTEND_RELEASE_PATH": "/srv/frontend",
                "REMOTE_TMP_ROOT": "/tmp/simple-deploy",
            }
        )

        self.assertEqual([origin.origin_id for origin in model.source_origins], ["backend-local", "frontend-local"])
        self.assertEqual(model.source_origins[0].kind, "emergency_clone")
        self.assertEqual(model.source_origins[0].remote_url, "C:/repos/backend")
        self.assertEqual([repo.repo_id for repo in model.source_repositories], ["backend", "frontend"])

        machines = {machine.machine_id: machine for machine in model.machines}
        self.assertEqual(machines["dev-app"].hostname, "dev-app.example.local")
        self.assertEqual(machines["dev-app"].ssh_user, "deploy")
        self.assertEqual(machines["dev-app"].workdir, "/opt/simple-deploy")
        self.assertEqual(machines["dev-app"].auth_profile, "C:/keys/app.pem")
        self.assertEqual(machines["dev-db"].auth_profile, "C:/keys/db.pem")

        targets = {target.target_id: target for target in model.landscapes[0].targets}
        self.assertEqual(targets["dev-backend"].machine_id, "dev-app")
        self.assertEqual(targets["dev-backend"].remote_path, "/srv/backend")
        self.assertEqual(targets["dev-frontend"].machine_id, "dev-app")
        self.assertEqual(targets["dev-database"].machine_id, "dev-db")
        self.assertEqual(targets["dev-database"].remote_path, "/tmp/simple-deploy")

        environment = model.execution_environments[0]
        self.assertEqual(environment.environment_id, "dev-contour")
        self.assertEqual(environment.kind, "contour_bound")
        self.assertEqual(environment.contour, "dev")
        self.assertEqual(environment.machine_ids, ["dev-app", "dev-db"])
        self.assertEqual(environment.target_ids, ["dev-backend", "dev-frontend", "dev-database"])

    def test_runtime_topology_from_legacy_env_tolerates_partial_env(self):
        """Legacy env adapter can expose source topology before VM keys are present."""
        model = runtime_topology_from_legacy_env(
            {
                "BACKEND_SOURCE_REPO_PATH": "C:/repos/backend",
                "APP_VM_HOST": "dev-app.example.local",
            }
        )

        self.assertEqual([origin.origin_id for origin in model.source_origins], ["backend-local"])
        self.assertEqual([repo.repo_id for repo in model.source_repositories], ["backend"])
        self.assertEqual(model.machines, [])
        self.assertEqual(model.landscapes, [])
        self.assertEqual(model.execution_environments, [])

        components = {component.component_id: component for component in model.components}
        self.assertEqual(components["backend"].source_repository_ids, ["backend"])
        self.assertEqual(components["frontend"].source_repository_ids, [])
        self.assertEqual(components["database"].target_roles, ["database"])


if __name__ == "__main__":
    unittest.main()
