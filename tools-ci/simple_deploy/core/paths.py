"""Общие пути и константы runtime-инструментов simple-deploy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS_CI_ROOT = ROOT / "tools-ci"
BUILDER_ROOT = TOOLS_CI_ROOT / "builder"

DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_SECRETS_FILE = ROOT / "local.secrets.env"
DEFAULT_CONFIG_FILE = ROOT / "windows_pipeline.local.json"
DEFAULT_LOG_DIR = ROOT / "logs"

DEFAULT_TIMEOUT = 20
DEFAULT_BACKEND_APP_ROOT_DIR = "example_backend_app"
PIP_TRUSTED_HOSTS = "pypi.org files.pythonhosted.org pypi.python.org"
INCLUDE_DATA_SQL_ENV = "SIMPLE_DEPLOY_INCLUDE_DATA_SQL"


__all__ = [
    "BUILDER_ROOT",
    "DEFAULT_BACKEND_APP_ROOT_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_ENV_FILE",
    "DEFAULT_LOG_DIR",
    "DEFAULT_SECRETS_FILE",
    "DEFAULT_TIMEOUT",
    "INCLUDE_DATA_SQL_ENV",
    "PIP_TRUSTED_HOSTS",
    "ROOT",
    "TOOLS_CI_ROOT",
]
