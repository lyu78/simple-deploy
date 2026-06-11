"""Pydantic-модели runtime-конфигурации Windows runner."""

from __future__ import annotations

from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, StringConstraints


MaintenanceSqlPhase = Literal["before_unpack", "before_migrate", "after_migrate"]
ServiceStepPhase = Literal["before_unpack", "after_unpack", "after_migrate", "after_frontend_unpack"]

NonEmptyString = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]


class _RuntimeConfigBaseModel(BaseModel):
    """Базовая модель runtime config без process-policy проверок."""

    model_config = ConfigDict(extra="allow", frozen=True)


class SqlScriptConfigModel(_RuntimeConfigBaseModel):
    """Структурное описание SQL script entry из runtime config."""

    path: NonEmptyString
    phase: MaintenanceSqlPhase


class ServiceStepConfigModel(_RuntimeConfigBaseModel):
    """Структурное описание service step entry из runtime config."""

    command: NonEmptyString
    phase: ServiceStepPhase = "after_migrate"
    name: StrictStr | None = None
    permission_check_command: StrictStr | None = None


class RuntimeConfigModel(_RuntimeConfigBaseModel):
    """Структурная модель текущей формы ``windows_pipeline.local.json``."""

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
    db_maintenance_sql_phase: MaintenanceSqlPhase
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
    """Преобразует runtime config mapping в структурную Pydantic-модель."""

    return RuntimeConfigModel.model_validate(runtime)


__all__ = [
    "MaintenanceSqlPhase",
    "RuntimeConfigModel",
    "ServiceStepConfigModel",
    "ServiceStepPhase",
    "SqlScriptConfigModel",
    "runtime_config_model",
]
