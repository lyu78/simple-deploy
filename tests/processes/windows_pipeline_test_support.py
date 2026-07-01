"""Shared fixtures and imports for Windows pipeline process tests."""

import unittest
import json
import os
import tempfile
from contextlib import ExitStack, closing, nullcontext
from pathlib import Path
import sys
from argparse import Namespace
from unittest.mock import patch, sentinel

ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"
RUNTIME_EXAMPLE_PATH = TOOLS_CI_ROOT / "windows_pipeline.example.json"
LEGACY_DB_MIGRATIONS_TASKS = ROOT / "legacy" / "ansible-ci" / "roles" / "db_migrations" / "tasks" / "main.yml"
MISSING_MAINTENANCE_STUB_ARCHIVE = TOOLS_CI_ROOT / "maintenance_stub" / "missing.tar.gz"

DEFAULT_ENV_FILE = TOOLS_CI_ROOT / ".env"
DEFAULT_SECRETS_FILE = TOOLS_CI_ROOT / "local.secrets.env"
DEFAULT_CONFIG_FILE = TOOLS_CI_ROOT / "windows_pipeline.local.json"

TEST_BUILD_VERSION = "1.2.3"
PREVIOUS_BUILD_VERSION = "1.2.2"
TEST_BACKEND_COMMIT = "abc123"
PREVIOUS_BACKEND_COMMIT = "prev123"
TEST_FRONTEND_COMMIT = "def456"

REMOTE_TMP_ROOT = "/tmp/simple-deploy"
REMOTE_RELEASE_ROOT = f"{REMOTE_TMP_ROOT}/{TEST_BUILD_VERSION}"
REMOTE_BACKEND_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/backend.tar.gz"
REMOTE_FRONTEND_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/frontend.tar.gz"
REMOTE_MAINTENANCE_STUB_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/maintenance_stub.tar.gz"
REMOTE_DB_SCHEMA_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_schema_dev.tar.gz"
REMOTE_DB_SCHEMA_DIR = f"{REMOTE_RELEASE_ROOT}/db_schema_dev"
REMOTE_DB_INSERT_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_insert.tar.gz"
REMOTE_DB_INSERT_DIR = f"{REMOTE_RELEASE_ROOT}/db_insert"
REMOTE_DB_UPDATE_PARALLEL_ARCHIVE = f"{REMOTE_RELEASE_ROOT}/db_update_parallel.tar.gz"
REMOTE_DB_UPDATE_PARALLEL_DIR = f"{REMOTE_RELEASE_ROOT}/db_update_parallel"
REMOTE_DB_SET_DEFAULT_PARALLEL_ARCHIVE = (
    f"{REMOTE_RELEASE_ROOT}/db_set_default_parallel.tar.gz"
)
REMOTE_DB_SET_DEFAULT_PARALLEL_DIR = (
    f"{REMOTE_RELEASE_ROOT}/db_set_default_parallel"
)

APP_VM_USER = "deploy-simple"
APP_VM_HOST = "app.example.local"
DB_VM_USER = "db-user"
DB_VM_HOST = "db.example.local"
DEV_DOMAIN = "dev.example.local"
APP_WORKDIR = "/opt/example/backend"
APP_VENV_ACTIVATE_PATH = "/opt/example/backend/venv/bin/activate"
BACKEND_RELEASE_PATH = "/opt/example/backend/app"
FRONTEND_RELEASE_PATH = "/opt/example/frontend/dist"

BACKEND_SOURCE_REPO_WINDOWS = r"C:\example\repos\backend-source"
BACKEND_APP_ROOT = "backend_app"

DATA_SQL_ROOT = "docs/database/scripts"
DATA_SQL_STANDARD_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany/insert_04_26"
DATA_SQL_CATALOG_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany_catalogs/insert_04_26"
DATA_SQL_FULL_STATE_INSERT_DIR = f"{DATA_SQL_ROOT}/app_ip_subcompany_cc/insert_04_26"
DATA_SQL_INSERT_NEW_OBJECTS_DIR = (
    f"{DATA_SQL_ROOT}/insert_new_objects/insert_04_26/insert_cc_and_prw_objects/1_iteration"
)
CATALOG_BUSINESS_KEY_TABLE = "app_ip_subcompany_catalog_contractsubject"
INSERT_NEW_OBJECTS_TABLE = "app_ip_subcompany_objectplanning"
INSERT_NEW_OBJECTS_SQL_FILE = f"insert_{INSERT_NEW_OBJECTS_TABLE}.sql"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.cli.windows_pipeline import (  # noqa: E402
    deploy,
    main,
    mark_applied,
    mark_failed,
    parse_args,
    pipeline,
    set_baseline,
)
from simple_deploy.application.requests import PipelineRequest  # noqa: E402
from simple_deploy.application.results import ProcessResult  # noqa: E402
from simple_deploy.config.runtime_loader import (  # noqa: E402
    check_runtime_config,
    load_runtime_config,
)
from simple_deploy.core.build_env import prepare_build_env  # noqa: E402
from simple_deploy.core.commands import CommandResult  # noqa: E402
from simple_deploy.core.ssh import scp_file  # noqa: E402
from simple_deploy.processes.app_deploy import (  # noqa: E402
    management_commands,
)
from simple_deploy.processes.data_sql import (  # noqa: E402
    cleanup_db_data_update_leftovers,
    run_db_data_insert,
    run_db_data_set_default_parallel,
    run_db_data_update_parallel,
    run_db_maintenance,
    run_db_schema_summary,
)
from simple_deploy.processes.dry_run_checks import (  # noqa: E402
    Reporter,
    check_backend_build_inputs,
    check_backend_data_insert_idempotency,
    check_maintenance_stub_archive,
    check_service_permissions,
    check_ssh_runtime,
    derive_service_permission_check,
    is_sudo_command,
    sudo_list_command,
)
from simple_deploy.processes.healthcheck import (  # noqa: E402
    verify_maintenance_stub_http,
)
from simple_deploy.processes.notifications import (  # noqa: E402
    send_outlook_success_email,
)
from simple_deploy.release.artifacts import (  # noqa: E402
    Artifact,
    DbSqlArtifact,
    resolve_db_data_artifact,
    resolve_db_schema_artifact,
    resolve_maintenance_stub_artifact,
)
from simple_deploy.release.manifest import RELEASE_MANIFEST_NAME  # noqa: E402
from simple_deploy.release.state import (  # noqa: E402
    connect_state_db,
    get_contour_state,
    list_deployment_attempts,
    record_release,
    upsert_contour_state,
)
from simple_deploy.types import ContourCodeEnum  # noqa: E402

class WindowsPipelineTestCase(unittest.TestCase):
    """Shared helper methods for Windows pipeline characterization tests."""

    def _write_release_manifest(self, release_dir: Path, backend_commit: str = TEST_BACKEND_COMMIT) -> None:
        """Shared helper methods for Windows pipeline characterization tests."""
        release_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "repositories": {
                "backend": {"commit_sha": backend_commit},
                "frontend": {"commit_sha": TEST_FRONTEND_COMMIT},
            }
        }
        (release_dir / RELEASE_MANIFEST_NAME).write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def _deploy_args(self, app_only: bool = False) -> Namespace:
        """Shared helper methods for Windows pipeline characterization tests."""
        return Namespace(
            env_file=DEFAULT_ENV_FILE,
            secrets_file=DEFAULT_SECRETS_FILE,
            config_file=DEFAULT_CONFIG_FILE,
            build_version=TEST_BUILD_VERSION,
            latest=False,
            contour="dev",
            include_set_default_sql=False,
            include_data_migration_sql=False,
            app_only=app_only,
        )

    def _deploy_env(self) -> dict[str, str]:
        """Shared helper methods for Windows pipeline characterization tests."""
        return {
            "APP_VM_USER": APP_VM_USER,
            "APP_VM_HOST": APP_VM_HOST,
            "APP_WORKDIR": APP_WORKDIR,
            "APP_VENV_ACTIVATE_PATH": APP_VENV_ACTIVATE_PATH,
            "REMOTE_TMP_ROOT": REMOTE_TMP_ROOT,
            "DEV_DOMAIN": DEV_DOMAIN,
        }

    def _app_artifacts(self) -> tuple[Artifact, Artifact]:
        """Shared helper methods for Windows pipeline characterization tests."""
        backend = Artifact("backend", Path("backend.tar.gz"), REMOTE_BACKEND_ARCHIVE, BACKEND_RELEASE_PATH)
        frontend = Artifact("frontend", Path("frontend.tar.gz"), REMOTE_FRONTEND_ARCHIVE, FRONTEND_RELEASE_PATH)
        return backend, frontend
