"""Типы runtime-фаз deploy pipeline."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class MaintenanceSqlPhaseEnum(DomainStringEnum):
    """Справочник фаз выполнения maintenance SQL."""

    BEFORE_UNPACK = "before_unpack"
    BEFORE_MIGRATE = "before_migrate"
    AFTER_MIGRATE = "after_migrate"


class ServiceStepPhaseEnum(DomainStringEnum):
    """Справочник фаз выполнения service step команд."""

    BEFORE_UNPACK = "before_unpack"
    AFTER_UNPACK = "after_unpack"
    AFTER_MIGRATE = "after_migrate"
    AFTER_FRONTEND_UNPACK = "after_frontend_unpack"


class SystemctlActionEnum(DomainStringEnum):
    """Справочник поддерживаемых systemctl actions для service step policy."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RELOAD = "reload"
    TRY_RESTART = "try-restart"
    RELOAD_OR_RESTART = "reload-or-restart"
    RELOAD_OR_TRY_RESTART = "reload-or-try-restart"
    STATUS = "status"


MAINTENANCE_SQL_PHASES = MaintenanceSqlPhaseEnum.get_values()
SERVICE_STEP_PHASES = ServiceStepPhaseEnum.get_values()
SYSTEMCTL_ACTIONS = SystemctlActionEnum.get_values()
NGINX_STOP_START_ACTIONS = frozenset(
    {
        SystemctlActionEnum.STOP.value,
        SystemctlActionEnum.START.value,
    }
)
NGINX_UNSUPPORTED_ACTIONS = frozenset(
    {
        SystemctlActionEnum.RESTART.value,
        SystemctlActionEnum.RELOAD.value,
        SystemctlActionEnum.TRY_RESTART.value,
        SystemctlActionEnum.RELOAD_OR_RESTART.value,
        SystemctlActionEnum.RELOAD_OR_TRY_RESTART.value,
    }
)


def _validate_maintenance_sql_phase(value: str) -> str:
    """Проверяет фазу выполнения maintenance SQL."""

    if value not in MAINTENANCE_SQL_PHASES:
        raise ValueError(
            f"Unknown maintenance SQL phase: {value}. Expected one of: {', '.join(MAINTENANCE_SQL_PHASES)}"
        )
    return value


def _validate_service_step_phase(value: str) -> str:
    """Проверяет фазу выполнения service step команды."""

    if value not in SERVICE_STEP_PHASES:
        raise ValueError(
            f"Unknown service step phase: {value}. Expected one of: {', '.join(SERVICE_STEP_PHASES)}"
        )
    return value


def _validate_systemctl_action(value: str) -> str:
    """Проверяет action команды systemctl."""

    if value not in SYSTEMCTL_ACTIONS:
        raise ValueError(
            f"Unknown systemctl action: {value}. Expected one of: {', '.join(SYSTEMCTL_ACTIONS)}"
        )
    return value


MaintenanceSqlPhase = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_maintenance_sql_phase),
]
"""Фаза выполнения maintenance SQL."""


ServiceStepPhase = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_service_step_phase),
]
"""Фаза выполнения service step команды."""


SystemctlAction = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_systemctl_action),
]
"""Action команды systemctl."""


__all__ = [
    "MAINTENANCE_SQL_PHASES",
    "NGINX_STOP_START_ACTIONS",
    "NGINX_UNSUPPORTED_ACTIONS",
    "SERVICE_STEP_PHASES",
    "SYSTEMCTL_ACTIONS",
    "MaintenanceSqlPhase",
    "MaintenanceSqlPhaseEnum",
    "ServiceStepPhase",
    "ServiceStepPhaseEnum",
    "SystemctlAction",
    "SystemctlActionEnum",
]
