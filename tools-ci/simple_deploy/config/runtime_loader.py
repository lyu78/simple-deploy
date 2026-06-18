"""Загрузка legacy runtime-конфига для Windows runner-а."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from simple_deploy.config.runtime import (
    runtime_config_model,
    RuntimeConfigModel,
)
from simple_deploy.config.validation import (
    check_runtime_config as _check_runtime_config,
)
from simple_deploy.core.paths import ROOT
from simple_deploy.release.artifacts import DEFAULT_MAINTENANCE_STUB_ARCHIVE

if TYPE_CHECKING:
    from simple_deploy.processes.dry_run_checks import Reporter


DEFAULT_RUNTIME_CONFIG = {
    "backup_enabled": False,
    "maintenance_stub_enabled": True,
    "maintenance_stub_archive_path": DEFAULT_MAINTENANCE_STUB_ARCHIVE,
    "maintenance_stub_verify_enabled": True,
    "maintenance_stub_verify_marker": "Плановые технические работы",
    "maintenance_stub_verify_retries": 10,
    "maintenance_stub_verify_delay": 2,
    "data_sql_enabled": True,
    "db_maintenance_enabled": True,
    "db_psql_bin": "psql",
    "db_psql_host": "localhost",
    "db_maintenance_sql_phase": "after_migrate",
    "db_maintenance_sql": ["VACUUM ANALYZE;"],
    "db_maintenance_sql_timeout_seconds": 900,
    "db_data_sql_timeout_seconds": 21600,
    "db_update_parallel_max_workers": 8,
    "db_update_parallel_status_interval_seconds": 30,
    "sql_scripts": [],
    "management_commands": [],
    "service_permission_checks_enabled": True,
    "service_steps": [],
    "healthcheck_enabled": True,
    "healthcheck_validate_certs": False,
    "healthcheck_retries": 30,
    "healthcheck_delay": 5,
    "portal_version_check_enabled": True,
    "portal_version_asset_limit": 20,
    "healthcheck_commands": [],
    "outlook_email_enabled": False,
    "outlook_email_recipients": [],
    "outlook_email_cc": [],
    "outlook_email_subject": "Деплой успешно завершен: {build_version}",
    "outlook_email_body": (
        "Деплой успешно завершен.\n\n"
        "Версия сборки: {build_version}\n"
        "Стенд: {stand_url}\n"
        "Каталог релиза: {release_dir}\n\n"
        "Артефакты:\n{artifacts_text}\n\n"
        "Изменения с предыдущего релиза:\n{release_changelog_text}"
    ),
    "outlook_email_required": False,
}


def load_runtime_config(config_file: Path) -> tuple[dict, list[str]]:
    """Загружает JSON-конфиг поверх дефолтов.

    Возвращает итоговый config и список ключей, взятых из defaults.
    """
    config = json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))
    configured_keys: set[str] = set()
    if config_file.exists():
        with config_file.open("r", encoding="utf-8") as file:
            override = json.load(file)
        configured_keys = set(override)
        config.update(override)
    defaulted_keys = sorted(set(DEFAULT_RUNTIME_CONFIG) - configured_keys)
    return config, defaulted_keys


def load_runtime_config_model(
    config_file: Path,
) -> tuple[RuntimeConfigModel, list[str]]:
    """Загружает runtime config через legacy loader.

    Возвращает typed read-model и список ключей, взятых из defaults.
    """
    runtime, defaulted_keys = load_runtime_config(config_file)
    return runtime_config_model(runtime), defaulted_keys


def runtime_default_preview(value: object) -> str:
    """Форматирует дефолтное runtime-значение для вывода в dry-run."""
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def check_runtime_config(reporter: Reporter, runtime: dict) -> bool:
    """Проверяет runtime config через вынесенный слой validation."""
    return _check_runtime_config(
        reporter,
        runtime,
        root=ROOT,
        default_runtime_config=DEFAULT_RUNTIME_CONFIG,
    )


__all__ = [
    "DEFAULT_RUNTIME_CONFIG",
    "check_runtime_config",
    "load_runtime_config",
    "load_runtime_config_model",
    "runtime_default_preview",
]
