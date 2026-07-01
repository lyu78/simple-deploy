"""Preflight и policy validation runtime-конфигурации."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
from typing import Mapping, Protocol

from simple_deploy.types.contour import CONTOUR_CODES
from simple_deploy.types.release import RELEASE_VERSION_PATTERN
from simple_deploy.types.runtime import (
    MAINTENANCE_SQL_PHASES,
    NGINX_STOP_START_ACTIONS,
    NGINX_UNSUPPORTED_ACTIONS,
    SERVICE_STEP_PHASES,
    SYSTEMCTL_ACTIONS,
)
from simple_deploy.types.source import COMMIT_SHA_PATTERN

DB_MAINTENANCE_PHASES = frozenset(MAINTENANCE_SQL_PHASES)
SERVICE_PHASES = frozenset(SERVICE_STEP_PHASES)
NGINX_SERVICE_TARGETS = {"nginx", "nginx.service"}
RUNTIME_BOOL_FIELDS = (
    "backup_enabled",
    "maintenance_stub_enabled",
    "maintenance_stub_verify_enabled",
    "data_sql_enabled",
    "db_maintenance_enabled",
    "service_permission_checks_enabled",
    "healthcheck_enabled",
    "healthcheck_validate_certs",
    "portal_version_check_enabled",
    "outlook_email_enabled",
    "outlook_email_required",
)
RUNTIME_POSITIVE_INT_FIELDS = (
    "db_maintenance_sql_timeout_seconds",
    "db_data_sql_timeout_seconds",
    "db_update_parallel_max_workers",
    "db_update_parallel_status_interval_seconds",
    "maintenance_stub_verify_retries",
    "maintenance_stub_verify_delay",
    "healthcheck_retries",
    "healthcheck_delay",
    "portal_version_asset_limit",
)
PACKAGED_SQL_REPORT_PATHS = (
    "tools-ci/sql/reports/public_table_size_report.sql",
    "tools-ci/sql/reports/public_table_maintenance_diagnostics.sql",
)
LEGACY_SQL_REPORT_PATHS = {
    "sql/public_table_size_report.sql": (
        "tools-ci/sql/reports/public_table_size_report.sql"
    ),
    "sql/public_table_maintenance_diagnostics.sql": (
        "tools-ci/sql/reports/public_table_maintenance_diagnostics.sql"
    ),
}


class RuntimeConfigReporter(Protocol):
    """Протокол reporter-а для runtime config validation."""

    def pass_(self, name: str, detail: str = "") -> None:
        """Фиксирует успешную проверку."""

    def fail(self, name: str, detail: str) -> None:
        """Фиксирует проваленную проверку."""


def is_bare_systemctl_command(command: object) -> bool:
    """Проверяет, вызывает ли команда bare systemctl без sudo."""
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and tokens[0] == "systemctl")


def is_bare_systemctl_status_command(command: object) -> bool:
    """Проверяет, является ли команда разрешенным bare systemctl status."""
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return (
        len(tokens) >= 3 and tokens[0] == "systemctl" and tokens[1] == "status"
    )


def is_disallowed_bare_systemctl_command(command: object) -> bool:
    """Проверяет, требует ли bare systemctl команда sudo."""
    return is_bare_systemctl_command(
        command
    ) and not is_bare_systemctl_status_command(command)


def systemctl_action(command: object) -> tuple[str, list[str]] | None:
    """Разбирает systemctl verb и targets из shell-команды."""
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    if tokens[0] == "sudo":
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            option = tokens.pop(0)
            if option in {"-u", "-g", "-h", "-p"} and tokens:
                tokens.pop(0)
    if not tokens or Path(tokens[0]).name != "systemctl":
        return None
    for index, token in enumerate(tokens[1:], start=1):
        if token in SYSTEMCTL_ACTIONS:
            return token, tokens[index + 1 :]
    return None


def is_nginx_stop_start_command(command: object) -> bool:
    """
    Проверяет, останавливает или запускает ли команда nginx через systemctl.
    """
    return nginx_systemctl_action(command) in NGINX_STOP_START_ACTIONS


def is_unsupported_nginx_command(command: object) -> bool:
    """
    Проверяет, использует ли команда неподдерживаемый nginx restart/reload.
    """
    return nginx_systemctl_action(command) in NGINX_UNSUPPORTED_ACTIONS


def nginx_systemctl_action(command: object) -> str | None:
    """Возвращает systemctl action, если команда нацелена на nginx."""
    action = systemctl_action(command)
    if not action:
        return None
    verb, targets = action
    if any(target in NGINX_SERVICE_TARGETS for target in targets):
        return verb
    return None


def check_runtime_config(
    reporter: RuntimeConfigReporter,
    runtime: Mapping[str, object],
    *,
    root: Path,
    default_runtime_config: Mapping[str, object],
) -> bool:
    """Проверяет форму runtime config и policy безопасного deploy."""
    ok = True
    unknown_keys = sorted(set(runtime) - set(default_runtime_config))
    if unknown_keys:
        reporter.fail(
            "runtime config keys", "unknown key(s): " + ", ".join(unknown_keys)
        )
        ok = False
    else:
        reporter.pass_(
            "runtime config keys",
            f"{len(default_runtime_config)} known key(s)",
        )

    for field in RUNTIME_BOOL_FIELDS:
        if isinstance(runtime.get(field), bool):
            continue
        reporter.fail(f"runtime {field}", "expected boolean true/false")
        ok = False

    for field in RUNTIME_POSITIVE_INT_FIELDS:
        value = runtime.get(field)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        ):
            continue
        reporter.fail(f"runtime {field}", "expected positive integer")
        ok = False

    for field in (
        "db_psql_bin",
        "db_psql_host",
        "maintenance_stub_archive_path",
        "maintenance_stub_verify_marker",
    ):
        value = runtime.get(field)
        if isinstance(value, str) and value.strip():
            continue
        reporter.fail(f"runtime {field}", "expected non-empty string")
        ok = False

    phase = runtime.get("db_maintenance_sql_phase")
    if phase not in DB_MAINTENANCE_PHASES:
        reporter.fail(
            "runtime db_maintenance_sql_phase",
            "expected one of: " + ", ".join(sorted(DB_MAINTENANCE_PHASES)),
        )
        ok = False

    for field in (
        "db_maintenance_sql",
        "management_commands",
        "healthcheck_commands",
    ):
        value = runtime.get(field)
        if not isinstance(value, list):
            reporter.fail(f"runtime {field}", "expected list")
            ok = False
            continue
        bad_indexes = [
            str(index)
            for index, item in enumerate(value, start=1)
            if not isinstance(item, str) or not item.strip()
        ]
        if bad_indexes:
            reporter.fail(
                f"runtime {field}",
                "expected non-empty string item(s), bad index(es): "
                + ", ".join(bad_indexes),
            )
            ok = False

    initial_schema_baselines = runtime.get("initial_schema_baselines")
    if not isinstance(initial_schema_baselines, dict):
        reporter.fail("runtime initial_schema_baselines", "expected object")
        ok = False
    else:
        for contour, baseline in initial_schema_baselines.items():
            label = f"runtime initial_schema_baselines {contour}"
            if contour not in CONTOUR_CODES:
                reporter.fail(
                    label,
                    "contour must be one of: "
                    + ", ".join(sorted(CONTOUR_CODES)),
                )
                ok = False
                continue
            if not isinstance(baseline, dict):
                reporter.fail(
                    label, "expected object with build_version and backend_commit"
                )
                ok = False
                continue
            build_version = baseline.get("build_version")
            backend_commit = baseline.get("backend_commit")
            if not isinstance(build_version, str) or not re.fullmatch(
                RELEASE_VERSION_PATTERN, build_version.strip()
            ):
                reporter.fail(label, "build_version has invalid format")
                ok = False
            if not isinstance(backend_commit, str) or not re.fullmatch(
                COMMIT_SHA_PATTERN, backend_commit.strip()
            ):
                reporter.fail(label, "backend_commit has invalid format")
                ok = False

    for field in ("outlook_email_recipients", "outlook_email_cc"):
        value = runtime.get(field)
        if isinstance(value, str):
            continue
        if isinstance(value, list) and all(
            isinstance(item, str) and item.strip() for item in value
        ):
            continue
        if isinstance(value, list) and not value:
            continue
        reporter.fail(
            f"runtime {field}", "expected string or list of non-empty strings"
        )
        ok = False

    for field in ("outlook_email_subject", "outlook_email_body"):
        if isinstance(runtime.get(field), str):
            continue
        reporter.fail(f"runtime {field}", "expected string")
        ok = False

    sql_scripts = runtime.get("sql_scripts")
    if not isinstance(sql_scripts, list):
        reporter.fail("runtime sql_scripts", "expected list")
        ok = False
    else:
        for index, script in enumerate(sql_scripts, start=1):
            label = f"runtime sql_scripts #{index}"
            if not isinstance(script, dict):
                reporter.fail(label, "expected object with path and phase")
                ok = False
                continue
            path_value = script.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                reporter.fail(label, "path must be a non-empty string")
                ok = False
            else:
                path_key = path_value.strip().replace("\\", "/")
                replacement = LEGACY_SQL_REPORT_PATHS.get(path_key)
                if replacement is not None:
                    reporter.fail(
                        label,
                        f"legacy SQL report path {path_key}; use {replacement}",
                    )
                    ok = False
                elif (path := root / path_value).is_file():
                    reporter.pass_(f"{label} path", str(path))
                else:
                    reporter.fail(label, f"path not found: {path}")
                    ok = False
            script_phase = script.get("phase")
            if script_phase not in DB_MAINTENANCE_PHASES:
                reporter.fail(
                    label,
                    "phase must be one of: "
                    + ", ".join(sorted(DB_MAINTENANCE_PHASES)),
                )
                ok = False

    service_steps = runtime.get("service_steps")
    if not isinstance(service_steps, list):
        reporter.fail("runtime service_steps", "expected list")
        ok = False
    else:
        nginx_service_actions: list[tuple[int, str, str, str]] = []
        for index, step in enumerate(service_steps, start=1):
            label = f"runtime service_steps #{index}"
            if not isinstance(step, dict):
                reporter.fail(
                    label, "expected object with command and optional phase"
                )
                ok = False
                continue
            step_phase = step.get("phase", "after_migrate")
            if step_phase not in SERVICE_PHASES:
                reporter.fail(
                    label,
                    "phase must be one of: "
                    + ", ".join(sorted(SERVICE_PHASES)),
                )
                ok = False
            command = step.get("command")
            nginx_command_action = nginx_systemctl_action(command)
            if nginx_command_action in NGINX_STOP_START_ACTIONS:
                nginx_service_actions.append(
                    (index, label, str(step_phase), nginx_command_action)
                )
            if not isinstance(command, str) or not command.strip():
                reporter.fail(label, "command must be a non-empty string")
                ok = False
            elif is_unsupported_nginx_command(command):
                reporter.fail(
                    label,
                    "nginx restart/reload commands are not supported; "
                    "use stop nginx then start nginx",
                )
                ok = False
            elif (
                is_nginx_stop_start_command(command)
                and step_phase != "after_frontend_unpack"
            ):
                reporter.fail(
                    label,
                    "nginx stop/start commands must run in "
                    "after_frontend_unpack after final frontend unpack",
                )
                ok = False
            elif is_disallowed_bare_systemctl_command(command):
                reporter.fail(
                    label,
                    "systemctl service commands except status must use sudo",
                )
                ok = False
            for optional_field in ("name", "permission_check_command"):
                if optional_field in step and not isinstance(
                    step[optional_field], str
                ):
                    reporter.fail(
                        label, f"{optional_field} must be a string when set"
                    )
                    ok = False
                elif is_unsupported_nginx_command(step.get(optional_field)):
                    reporter.fail(
                        label,
                        f"{optional_field} must not use nginx restart/reload; "
                        "use stop nginx then start nginx",
                    )
                    ok = False
                elif (
                    is_nginx_stop_start_command(step.get(optional_field))
                    and step_phase != "after_frontend_unpack"
                ):
                    reporter.fail(
                        label,
                        f"{optional_field} must run nginx stop/start in "
                        "after_frontend_unpack",
                    )
                    ok = False
                elif is_disallowed_bare_systemctl_command(
                    step.get(optional_field)
                ):
                    reporter.fail(
                        label,
                        f"{optional_field} must use sudo for systemctl "
                        "commands except status",
                    )
                    ok = False
        for position, (_index, label, step_phase, verb) in enumerate(
            nginx_service_actions
        ):
            if verb != "stop" or step_phase != "after_frontend_unpack":
                continue
            has_later_start = any(
                later_phase == "after_frontend_unpack"
                and later_verb == "start"
                for (
                    _later_index,
                    _later_label,
                    later_phase,
                    later_verb,
                ) in nginx_service_actions[position + 1 :]
            )
            if not has_later_start:
                reporter.fail(
                    label,
                    "nginx stop in after_frontend_unpack must be followed "
                    "by nginx start before healthcheck",
                )
                ok = False

    if ok:
        reporter.pass_("runtime config values", "types and ranges are valid")
    return ok


__all__ = [
    "DB_MAINTENANCE_PHASES",
    "NGINX_SERVICE_TARGETS",
    "NGINX_STOP_START_ACTIONS",
    "NGINX_UNSUPPORTED_ACTIONS",
    "LEGACY_SQL_REPORT_PATHS",
    "PACKAGED_SQL_REPORT_PATHS",
    "RUNTIME_BOOL_FIELDS",
    "RUNTIME_POSITIVE_INT_FIELDS",
    "RuntimeConfigReporter",
    "SERVICE_PHASES",
    "SYSTEMCTL_ACTIONS",
    "check_runtime_config",
    "is_bare_systemctl_command",
    "is_bare_systemctl_status_command",
    "is_disallowed_bare_systemctl_command",
    "is_nginx_stop_start_command",
    "is_unsupported_nginx_command",
    "nginx_systemctl_action",
    "systemctl_action",
]
