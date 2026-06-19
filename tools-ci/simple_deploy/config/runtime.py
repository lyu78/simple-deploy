"""
Pydantic-модели текущей runtime-конфигурации Windows runner.

Runtime config - это operational-параметры запуска уже существующего runner-а.
Он описывает не "топологию продукта", а конкретные переключатели и команды:
включен ли maintenance stub, сколько раз повторять healthcheck, какие SQL
скрипты выполнить, какие service steps разрешены и куда отправлять email.

Минимальный пример смысла полей::

{ "maintenance_stub_enabled": true, "data_sql_enabled": true,
"db_update_parallel_max_workers": 4, "service_steps": [ {"phase":
"after_migrate", "command": "systemctl restart app"} ], "healthcheck_retries":
20 }

В отличие от ``config.topology``, этот модуль не знает, какие source
repositories образуют компонент и на каких deployment targets он размещается.
Он сохраняет текущий контракт ``tools-ci/windows_pipeline.local.json`` и только
добавляет typed-валидацию/нормализацию вокруг него.
"""

from __future__ import annotations

from typing import Annotated, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
)

from simple_deploy.types.runtime import (
    MaintenanceSqlPhaseEnum,
    ServiceStepPhaseEnum,
)

NonEmptyString = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1)
]
PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]


class _RuntimeConfigBaseModel(BaseModel):
    """Базовая immutable-модель runtime config без process-policy проверок."""

    model_config = ConfigDict(extra="allow", frozen=True)


class SqlScriptConfigModel(_RuntimeConfigBaseModel):
    """Структурное описание SQL script entry из runtime config."""

    path: NonEmptyString
    phase: MaintenanceSqlPhaseEnum


class ServiceStepConfigModel(_RuntimeConfigBaseModel):
    """Структурное описание service step entry из runtime config."""

    command: NonEmptyString
    phase: ServiceStepPhaseEnum = ServiceStepPhaseEnum.AFTER_MIGRATE
    name: StrictStr | None = None
    permission_check_command: StrictStr | None = None


class RuntimeConfigModel(_RuntimeConfigBaseModel):
    """Структурная модель текущей формы ``tools-ci/windows_pipeline.local.json``.

    Модель держит legacy-совместимый набор полей runner-а. Она не валидирует
    бизнес-правила вроде "stop nginx требует последующий start" - такие правила
    остаются в ``config.validation`` и process/preflight слоях.
    """

    backup_enabled: StrictBool
    maintenance_stub_enabled: StrictBool
    maintenance_stub_archive_path: NonEmptyString
    maintenance_stub_verify_enabled: StrictBool
    maintenance_stub_verify_marker: NonEmptyString
    maintenance_stub_verify_retries: PositiveStrictInt
    maintenance_stub_verify_delay: PositiveStrictInt
    data_sql_enabled: StrictBool
    db_maintenance_enabled: StrictBool
    db_psql_bin: NonEmptyString
    db_psql_host: NonEmptyString
    db_maintenance_sql_phase: MaintenanceSqlPhaseEnum
    db_maintenance_sql: list[NonEmptyString]
    db_maintenance_sql_timeout_seconds: PositiveStrictInt
    db_data_sql_timeout_seconds: PositiveStrictInt
    db_update_parallel_max_workers: PositiveStrictInt
    db_update_parallel_status_interval_seconds: PositiveStrictInt
    sql_scripts: list[SqlScriptConfigModel]
    management_commands: list[NonEmptyString]
    service_permission_checks_enabled: StrictBool
    service_steps: list[ServiceStepConfigModel]
    healthcheck_enabled: StrictBool
    healthcheck_validate_certs: StrictBool
    healthcheck_retries: PositiveStrictInt
    healthcheck_delay: PositiveStrictInt
    portal_version_check_enabled: StrictBool
    portal_version_asset_limit: PositiveStrictInt
    healthcheck_commands: list[NonEmptyString]
    outlook_email_enabled: StrictBool
    outlook_email_recipients: StrictStr | list[NonEmptyString]
    outlook_email_cc: StrictStr | list[NonEmptyString]
    outlook_email_subject: StrictStr
    outlook_email_body: StrictStr
    outlook_email_required: StrictBool


def runtime_config_model(runtime: Mapping[str, object]) -> RuntimeConfigModel:
    """Преобразует mapping из runtime JSON в структурную Pydantic-модель."""
    return RuntimeConfigModel.model_validate(runtime)


__all__ = [
    "MaintenanceSqlPhaseEnum",
    "RuntimeConfigModel",
    "ServiceStepConfigModel",
    "ServiceStepPhaseEnum",
    "SqlScriptConfigModel",
    "runtime_config_model",
]
