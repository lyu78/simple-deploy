"""Dry-run процесс Windows runner-а.

Модуль фиксирует orchestration preflight-проверок перед build/deploy: чтение
локальных конфигов, проверку обязательных env-ключей, runtime config,
доступности SSH/DB, репозиториев, idempotency data SQL и HTTP/Outlook
настроек. На этом срезе helper-ы остаются в compatibility runner-е, чтобы
перенос ``dry_run`` не смешивался с переносом config/core/SSH слоев.
"""

from __future__ import annotations

from pathlib import Path
import sys

from simple_deploy.application.requests import DryRunRequest
from simple_deploy.application.results import ProcessResult
from simple_deploy.config.runtime_loader import (
    check_runtime_config,
    DEFAULT_RUNTIME_CONFIG,
    load_runtime_config,
    runtime_default_preview,
)
from simple_deploy.config.topology import runtime_topology_from_legacy_env
from simple_deploy.core.build_env import data_sql_artifacts_enabled
from simple_deploy.core.env import load_env
from simple_deploy.processes.dry_run_checks import (
    check_app_deploy_directories,
    check_app_manage_py,
    check_backend_build_inputs,
    check_backend_data_insert_idempotency,
    check_command,
    check_db_psql_login,
    check_http,
    check_maintenance_stub_archive,
    check_origin_network,
    check_outlook_email_config,
    check_repo,
    check_service_permissions,
    check_ssh_key_files,
    check_ssh_runtime,
    check_windows_command,
    Reporter,
)


def dry_run(request: DryRunRequest) -> ProcessResult:
    """Выполняет preflight-проверки без build/deploy side effects.

    Функция возвращает итог ``Reporter.result()``. Она не меняет baseline,
    SQLite state, release artifacts и remote VM state, кроме read-only SSH/HTTP
    проверок, которые уже были частью старого runner contract.
    """
    reporter = Reporter()
    app_only = request.app_only
    try:
        require_dry_run_local_files(request)
        env = load_env(
            request.env_file,
            request.secrets_file,
            require_secrets=not app_only,
        )
        runtime, defaulted_runtime_keys = load_runtime_config(
            request.config_file
        )
        reporter.pass_(
            "config files", f"{request.env_file}, {request.secrets_file}"
        )
    except Exception as exc:
        reporter.fail("config files", str(exc))
        return ProcessResult.failure(
            "dry-run config validation failed",
            details={"stage": "config"},
        )

    for key in defaulted_runtime_keys:
        reporter.warn(
            f"runtime {key}",
            f"missing in {request.config_file}; using default "
            f"{runtime_default_preview(DEFAULT_RUNTIME_CONFIG[key])}",
        )

    for key in required_env_keys(app_only=app_only):
        if env.get(key, "").strip():
            reporter.pass_(f"env {key}")
        else:
            reporter.fail(f"env {key}", "значение не задано")

    runtime_config_ok = check_runtime_config(reporter, runtime)
    if app_only:
        reporter.skip("maintenance stub archive", "app-only mode")
    elif runtime_config_ok:
        check_maintenance_stub_archive(reporter, runtime)
    else:
        reporter.skip("maintenance stub archive", "runtime config invalid")

    check_command(reporter, "Python", [sys.executable, "--version"])
    check_windows_command(reporter, "git", "git --version")
    check_windows_command(reporter, "node", "node --version")
    check_windows_command(reporter, "npm", "npm --version")
    check_windows_command(reporter, "ssh", "ssh -V")
    check_windows_command(reporter, "scp", "where scp")

    git_bash = Path(env.get("GIT_BASH_PATH", ""))
    if git_bash.exists():
        reporter.pass_("Git Bash", str(git_bash))
    else:
        reporter.fail("Git Bash", f"не найден: {git_bash}")

    check_ssh_key_files(reporter, env, app_only=app_only)

    topology = runtime_topology_from_legacy_env(env)
    origins_by_id = {
        origin.origin_id: origin for origin in topology.source_origins
    }
    source_origins = []
    for repository in topology.source_repositories:
        origin = origins_by_id.get(repository.default_origin_id)
        if origin is not None:
            source_origins.append(
                (f"{repository.repo_id} source repo", origin.remote_url)
            )
    target_origins = [
        ("backend target repo", env.get("BACKEND_TARGET_REPO_PATH", "")),
        ("frontend target repo", env.get("FRONTEND_TARGET_REPO_PATH", "")),
    ]
    for name, path in [*source_origins, *target_origins]:
        origin_url = check_repo(reporter, name, path)
        check_origin_network(reporter, f"{name} origin network", origin_url)

    check_backend_build_inputs(reporter, env)
    if data_sql_artifacts_enabled(request.skip_data_sql_artifacts):
        check_backend_data_insert_idempotency(reporter, env)
    else:
        reporter.skip(
            "backend data INSERT idempotency",
            "data SQL artifacts disabled by --skip-data-sql-artifacts",
        )
    if runtime_config_ok:
        check_outlook_email_config(reporter, runtime)
    else:
        reporter.skip("Outlook email", "runtime config invalid")

    try:
        ssh_state = check_ssh_runtime(reporter, env, app_only=app_only)
    except Exception as exc:
        reporter.fail("SSH runtime checks", str(exc))
        ssh_state = {"app": False, "db": False}
        reporter.skip(
            "app VM deploy checks", "SSH runtime checks завершились ошибкой"
        )
        reporter.skip(
            "DB SQL checks", "SSH runtime checks завершились ошибкой"
        )

    if not ssh_state["app"]:
        reporter.skip("app VM directory checks", "app VM unavailable")
        reporter.skip("service permission checks", "app VM unavailable")
        reporter.skip(
            "DEV HTTP endpoint",
            "app VM недоступна, healthcheck неинформативен",
        )
    elif not runtime_config_ok:
        reporter.skip("app VM directory checks", "runtime config invalid")
        reporter.skip("service permission checks", "runtime config invalid")
        reporter.skip("DEV HTTP endpoint", "runtime config invalid")
    else:
        check_app_deploy_directories(reporter, env, runtime)
        check_app_manage_py(reporter, env)
        check_service_permissions(reporter, env, runtime)
        if runtime.get("healthcheck_enabled", True):
            check_http(
                reporter,
                env,
                bool(runtime.get("healthcheck_validate_certs", False)),
            )
        else:
            reporter.skip("DEV HTTP endpoint", "healthcheck disabled")

    if app_only:
        reporter.skip("DB psql login", "app-only mode")
    elif not runtime_config_ok:
        reporter.skip("DB psql login", "runtime config invalid")
    elif ssh_state["db"]:
        check_db_psql_login(reporter, env, runtime)
    else:
        reporter.skip("DB psql login", "DB VM SSH/psql unavailable")

    if reporter.result():
        return ProcessResult.success("dry-run checks passed")
    return ProcessResult.failure("dry-run checks failed")


def required_env_keys(app_only: bool = False) -> list[str]:
    """Возвращает обязательные env-ключи для dry-run режима.

    В ``app-only`` режиме DB login/host/port/name не обязательны, потому что
    deploy не должен выполнять DB steps. Функция только описывает контракт
    валидации и не читает реальные env-файлы.
    """
    keys = [
        "BUILD_VERSION_BASE",
        "GIT_BASH_PATH",
        "BACKEND_SOURCE_REPO_PATH",
        "BACKEND_TARGET_REPO_PATH",
        "FRONTEND_SOURCE_REPO_PATH",
        "FRONTEND_TARGET_REPO_PATH",
        "APP_VM_HOST",
        "APP_VM_USER",
        "DB_VM_HOST",
        "DB_VM_USER",
        "DB_PORT",
        "DB_NAME",
        "REMOTE_TMP_ROOT",
        "BACKEND_RELEASE_PATH",
        "FRONTEND_RELEASE_PATH",
        "APP_WORKDIR",
        "APP_VENV_ACTIVATE_PATH",
        "APP_MANAGE_PY_PATH",
        "DEV_DOMAIN",
        "TEST_DOMAIN",
        "PROD_DOMAIN",
        "FRONTEND_TEST_SERVER_NAME",
        "FRONTEND_PROD_SERVER_NAME",
    ]
    if app_only:
        return [
            key
            for key in keys
            if key not in {"DB_VM_HOST", "DB_VM_USER", "DB_PORT", "DB_NAME"}
        ]
    return keys


def require_dry_run_local_files(request: DryRunRequest) -> None:
    """Проверяет наличие локальных файлов, без которых dry-run неинформативен.

    ``--app-only`` ослабляет проверку DB credentials внутри secrets-файла, но
    сам локальный secrets-файл и runtime JSON должны существовать, иначе
    preflight не подтверждает готовность рабочей машины к реальному запуску.
    """
    for label, path in (
        ("local secrets env", request.secrets_file),
        ("runtime config", request.config_file),
    ):
        if not path.exists():
            raise RuntimeError(f"Файл {label} не найден: {path}")
        if not path.is_file():
            raise RuntimeError(f"Путь {label} не является файлом: {path}")


__all__ = ["dry_run", "required_env_keys", "require_dry_run_local_files"]
