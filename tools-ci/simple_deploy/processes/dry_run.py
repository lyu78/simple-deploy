"""Dry-run процесс Windows runner-а.

Модуль фиксирует orchestration preflight-проверок перед build/deploy: чтение
локальных конфигов, проверку обязательных env-ключей, runtime config,
доступности SSH/DB, репозиториев, idempotency data SQL и HTTP/Outlook
настроек. На этом срезе helper-ы остаются в compatibility runner-е, чтобы
перенос ``dry_run`` не смешивался с переносом config/core/SSH слоев.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def _runner_module():
    """Возвращает compatibility runner с preflight helper-ами.

    Ленивый импорт нужен для сохранения старого public API
    ``tools.windows_pipeline.dry_run`` и старых patch paths тестов.
    """
    from simple_deploy import windows_pipeline

    return windows_pipeline


def dry_run(args: argparse.Namespace) -> bool:
    """Выполняет preflight-проверки без build/deploy side effects.

    Функция возвращает итог ``Reporter.result()``. Она не меняет baseline,
    SQLite state, release artifacts и remote VM state, кроме read-only SSH/HTTP
    проверок, которые уже были частью старого runner contract.
    """
    runner = _runner_module()
    reporter = runner.Reporter()
    app_only = bool(getattr(args, "app_only", False))
    try:
        env = runner.load_env(args.env_file, args.secrets_file, require_secrets=not app_only)
        runtime, defaulted_runtime_keys = runner.load_runtime_config(args.config_file)
        reporter.pass_("config files", f"{args.env_file}, {args.secrets_file}")
    except Exception as exc:
        reporter.fail("config files", str(exc))
        return reporter.result()

    for key in defaulted_runtime_keys:
        reporter.warn(
            f"runtime {key}",
            f"missing in {args.config_file}; using default "
            f"{runner.runtime_default_preview(runner.DEFAULT_RUNTIME_CONFIG[key])}",
        )

    for key in required_env_keys(app_only=app_only):
        if env.get(key, "").strip():
            reporter.pass_(f"env {key}")
        else:
            reporter.fail(f"env {key}", "значение не задано")

    runtime_config_ok = runner.check_runtime_config(reporter, runtime)
    if app_only:
        reporter.skip("maintenance stub archive", "app-only mode")
    elif runtime_config_ok:
        runner.check_maintenance_stub_archive(reporter, runtime)
    else:
        reporter.skip("maintenance stub archive", "runtime config invalid")

    runner.check_command(reporter, "Python", [sys.executable, "--version"])
    runner.check_windows_command(reporter, "git", "git --version")
    runner.check_windows_command(reporter, "node", "node --version")
    runner.check_windows_command(reporter, "npm", "npm --version")
    runner.check_windows_command(reporter, "ssh", "ssh -V")
    runner.check_windows_command(reporter, "scp", "where scp")

    git_bash = Path(env.get("GIT_BASH_PATH", ""))
    if git_bash.exists():
        reporter.pass_("Git Bash", str(git_bash))
    else:
        reporter.fail("Git Bash", f"не найден: {git_bash}")

    runner.check_ssh_key_files(reporter, env, app_only=app_only)

    origins = [
        ("backend source repo", env.get("BACKEND_SOURCE_REPO_PATH", "")),
        ("backend target repo", env.get("BACKEND_TARGET_REPO_PATH", "")),
        ("frontend source repo", env.get("FRONTEND_SOURCE_REPO_PATH", "")),
        ("frontend target repo", env.get("FRONTEND_TARGET_REPO_PATH", "")),
    ]
    for name, path in origins:
        origin_url = runner.check_repo(reporter, name, path)
        runner.check_origin_network(reporter, f"{name} origin network", origin_url)

    runner.check_backend_build_inputs(reporter, env)
    if runner.data_sql_artifacts_enabled(args):
        runner.check_backend_data_insert_idempotency(reporter, env)
    else:
        reporter.skip("backend data INSERT idempotency", "data SQL artifacts disabled by --skip-data-sql-artifacts")
    if runtime_config_ok:
        runner.check_outlook_email_config(reporter, runtime)
    else:
        reporter.skip("Outlook email", "runtime config invalid")

    try:
        ssh_state = runner.check_ssh_runtime(reporter, env, app_only=app_only)
    except Exception as exc:
        reporter.fail("SSH runtime checks", str(exc))
        ssh_state = {"app": False, "db": False}
        reporter.skip("app VM deploy checks", "SSH runtime checks завершились ошибкой")
        reporter.skip("DB SQL checks", "SSH runtime checks завершились ошибкой")

    if not ssh_state["app"]:
        reporter.skip("app VM directory checks", "app VM unavailable")
        reporter.skip("service permission checks", "app VM unavailable")
        reporter.skip("DEV HTTP endpoint", "app VM недоступна, healthcheck неинформативен")
    elif not runtime_config_ok:
        reporter.skip("app VM directory checks", "runtime config invalid")
        reporter.skip("service permission checks", "runtime config invalid")
        reporter.skip("DEV HTTP endpoint", "runtime config invalid")
    else:
        runner.check_app_deploy_directories(reporter, env, runtime)
        runner.check_app_manage_py(reporter, env)
        runner.check_service_permissions(reporter, env, runtime)
        if runtime.get("healthcheck_enabled", True):
            runner.check_http(reporter, env, bool(runtime.get("healthcheck_validate_certs", False)))
        else:
            reporter.skip("DEV HTTP endpoint", "healthcheck disabled")

    if app_only:
        reporter.skip("DB psql login", "app-only mode")
    elif not runtime_config_ok:
        reporter.skip("DB psql login", "runtime config invalid")
    elif ssh_state["db"]:
        runner.check_db_psql_login(reporter, env, runtime)
    else:
        reporter.skip("DB psql login", "DB VM SSH/psql unavailable")

    return reporter.result()


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
        return [key for key in keys if key not in {"DB_VM_HOST", "DB_VM_USER", "DB_PORT", "DB_NAME"}]
    return keys


__all__ = ["dry_run", "required_env_keys"]
