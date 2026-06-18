"""
Типы runtime-фаз deploy pipeline и управления systemd units.

Модуль описывает два соседних словаря runtime config:

- фазы, в которые pipeline может выполнить maintenance SQL или service steps;
- допустимые ``systemctl`` actions, которыми service steps управляют systemd
  units на APP/DB VM: запуск, остановка, перезапуск, reload и чтение status.

Эти типы не запускают команды сами. Они только фиксируют vocabulary для
runtime config, validation и dry-run permission checks.
"""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class MaintenanceSqlPhaseEnum(DomainStringEnum):
    """
    Справочник фаз выполнения maintenance SQL.

    Значения определяют, в какой момент deploy pipeline запускает SQL-скрипты
    обслуживания относительно распаковки и миграций.
    """

    BEFORE_UNPACK = "before_unpack"
    BEFORE_MIGRATE = "before_migrate"
    AFTER_MIGRATE = "after_migrate"


class ServiceStepPhaseEnum(DomainStringEnum):
    """
    Справочник фаз выполнения service step команд.

    Service steps - это runtime-команды оператора, которые pipeline выполняет
    в заданной фазе deploy. На практике через них часто управляются systemd
    units приложения: nginx, backend services, workers и другие unit-ы,
    доступные на APP/DB VM.
    """

    BEFORE_UNPACK = "before_unpack"
    AFTER_UNPACK = "after_unpack"
    AFTER_MIGRATE = "after_migrate"
    AFTER_FRONTEND_UNPACK = "after_frontend_unpack"


class SystemctlActionEnum(DomainStringEnum):
    """
    Справочник поддерживаемых ``systemctl`` actions для service step policy.

    Значения соответствуют действиям systemd unit management: ``start`` и
    ``stop`` меняют состояние unit-а, ``restart``/``try-restart`` перезапускают
    его, ``reload``-варианты перечитывают конфигурацию, а ``status`` нужен для
    read-only проверки доступности unit-а.
    """

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


__all__ = [
    "MAINTENANCE_SQL_PHASES",
    "NGINX_STOP_START_ACTIONS",
    "NGINX_UNSUPPORTED_ACTIONS",
    "SERVICE_STEP_PHASES",
    "SYSTEMCTL_ACTIONS",
    "MaintenanceSqlPhaseEnum",
    "ServiceStepPhaseEnum",
    "SystemctlActionEnum",
]
