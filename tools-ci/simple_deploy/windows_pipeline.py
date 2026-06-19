"""Compatibility runner для Windows-only simple-deploy.

Модуль сохраняет старый CLI/import контракт Windows runner-а и постепенно
сжимается до тонкого слоя CLI/logging/re-export поверх новых владельцев логики.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

from simple_deploy.application.requests import (  # noqa: E402
    BuildRequest,
    DeployRequest,
    DryRunRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    SetBaselineRequest,
)
from simple_deploy.application.services import (  # noqa: E402
    build as _build_service,
    deploy as _deploy_service,
    dry_run as _dry_run_service,
    mark_applied as _mark_applied_service,
    mark_failed as _mark_failed_service,
    pipeline as _pipeline_service,
    set_baseline as _set_baseline_service,
)
from simple_deploy.cli.requests import (  # noqa: E402
    build_request_from_args,
    deploy_request_from_args,
    dry_run_request_from_args,
    mark_applied_request_from_args,
    mark_failed_request_from_args,
    pipeline_request_from_args,
    request_from_args,
    set_baseline_request_from_args,
)
from simple_deploy.config.validation import (  # noqa: E402,F401
    DB_MAINTENANCE_PHASES,
    NGINX_SERVICE_TARGETS,
    NGINX_STOP_START_ACTIONS,
    NGINX_UNSUPPORTED_ACTIONS,
    RUNTIME_BOOL_FIELDS,
    RUNTIME_POSITIVE_INT_FIELDS,
    SERVICE_PHASES,
    SYSTEMCTL_ACTIONS,
    is_bare_systemctl_command,
    is_bare_systemctl_status_command,
    is_disallowed_bare_systemctl_command,
    is_nginx_stop_start_command,
    is_unsupported_nginx_command,
    nginx_systemctl_action,
    systemctl_action,
)
from simple_deploy.core.paths import (  # noqa: E402
    DEFAULT_CONFIG_FILE,
    DEFAULT_ENV_FILE,
    DEFAULT_LOG_DIR,
    DEFAULT_SECRETS_FILE,
)
from simple_deploy.registry.state import (  # noqa: E402
    CONTOURS,
)


class Tee:
    """Пишет один и тот же текст сразу в несколько потоков вывода."""

    def __init__(self, *streams) -> None:
        """Сохраняет целевые потоки вывода."""
        self.streams = streams

    def write(self, text: str) -> int:
        """Записывает текст во все потоки и возвращает его длину."""
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        """Сбрасывает буферы всех потоков."""
        for stream in self.streams:
            stream.flush()


def create_log_file(command: str) -> Path:
    """Создает путь к log-файлу для запуска указанной CLI-команды."""
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_command = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in command or "run"
    )
    return DEFAULT_LOG_DIR / f"{timestamp}-{safe_command}.log"


@contextlib.contextmanager
def tee_output(command: str):
    """Дублирует stdout/stderr текущей команды в log-файл."""
    log_path = create_log_file(command)
    with log_path.open("w", encoding="utf-8") as log_file:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)
        try:
            print(f"RUN LOG {log_path}", flush=True)
            yield log_path
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def dry_run(request: DryRunRequest | argparse.Namespace) -> bool:
    """Запускает dry-run через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = dry_run_request_from_args(request)
    return _dry_run_service(request)


def build(request: BuildRequest | argparse.Namespace) -> int:
    """Запускает build через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = build_request_from_args(request)
    return _build_service(request)


def deploy(request: DeployRequest | argparse.Namespace) -> int:
    """Запускает deploy через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = deploy_request_from_args(request)
    return _deploy_service(request)


def pipeline(request: PipelineRequest | argparse.Namespace) -> int:
    """Выполняет dry-run, build и deploy latest как одну CLI-команду."""
    if isinstance(request, argparse.Namespace):
        request = pipeline_request_from_args(request)
    return _pipeline_service(request)


def set_baseline(request: SetBaselineRequest | argparse.Namespace) -> int:
    """Запускает set-baseline через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = set_baseline_request_from_args(request)
    return _set_baseline_service(request)


def mark_applied(request: MarkAppliedRequest | argparse.Namespace) -> int:
    """Запускает mark-applied через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = mark_applied_request_from_args(request)
    return _mark_applied_service(request)


def mark_failed(request: MarkFailedRequest | argparse.Namespace) -> int:
    """Запускает mark-failed через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = mark_failed_request_from_args(request)
    return _mark_failed_service(request)


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы legacy Windows runner CLI."""
    parser = argparse.ArgumentParser(
        description="Windows-only simple-deploy runner"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE
    )
    parser.add_argument(
        "--config-file", type=Path, default=DEFAULT_CONFIG_FILE
    )
    parser.add_argument("--timeout", type=int, default=3600)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help=(
            "Deprecated no-op: data SQL artifacts are checked and built "
            "by default."
        ),
    )
    dry_run_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact validation for an explicit "
            "schema-only run."
        ),
    )
    dry_run_parser.add_argument("--app-only", action="store_true")

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help="Deprecated no-op: data SQL artifacts are built by default.",
    )
    build_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact generation for an explicit "
            "schema-only build."
        ),
    )

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--build-version", default="")
    deploy_parser.add_argument("--latest", action="store_true")
    deploy_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    deploy_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help=(
            "Include kind=set_default data SQL in the update runner. "
            "Disabled by default."
        ),
    )
    deploy_parser.add_argument("--app-only", action="store_true")

    pipeline_parser = subparsers.add_parser("pipeline")
    pipeline_parser.add_argument("--build-version", default="")
    pipeline_parser.add_argument("--latest", action="store_true")
    pipeline_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    pipeline_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help=(
            "Include kind=set_default data SQL in the update runner. "
            "Disabled by default."
        ),
    )
    pipeline_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help=(
            "Deprecated no-op: data SQL artifacts are checked and built "
            "by default."
        ),
    )
    pipeline_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact validation/generation for an "
            "explicit schema-only run."
        ),
    )
    pipeline_parser.add_argument("--app-only", action="store_true")

    baseline_parser = subparsers.add_parser("set-baseline")
    baseline_parser.add_argument("--contour", choices=CONTOURS, required=True)
    baseline_parser.add_argument("--build-version", default="")
    baseline_parser.add_argument("--backend-commit", default="")

    mark_applied_parser = subparsers.add_parser("mark-applied")
    mark_applied_parser.add_argument(
        "--contour", choices=CONTOURS, required=True
    )
    mark_applied_parser.add_argument("--build-version", required=True)

    mark_failed_parser = subparsers.add_parser("mark-failed")
    mark_failed_parser.add_argument(
        "--contour", choices=CONTOURS, required=True
    )
    mark_failed_parser.add_argument("--build-version", required=True)
    mark_failed_parser.add_argument("--error", required=True)
    return parser.parse_args()


def main() -> int:
    """Запускает выбранную CLI-команду и возвращает process exit code."""
    args = parse_args()
    with tee_output(args.command):
        try:
            request = request_from_args(args)
            if args.command == "dry-run":
                return 0 if dry_run(request) else 1
            if args.command == "build":
                return build(request)
            if args.command == "deploy":
                return deploy(request)
            if args.command == "pipeline":
                return pipeline(request)
            if args.command == "set-baseline":
                return set_baseline(request)
            if args.command == "mark-applied":
                return mark_applied(request)
            if args.command == "mark-failed":
                return mark_failed(request)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 1


from simple_deploy.config.runtime_loader import (  # noqa: E402,F401
    DEFAULT_RUNTIME_CONFIG,
    check_runtime_config,
    load_runtime_config,
    load_runtime_config_model,
    runtime_default_preview,
)
from simple_deploy.core.build_env import (  # noqa: E402,F401
    INCLUDE_DATA_SQL_ENV,
    data_sql_artifacts_enabled,
    prepare_build_env,
    prepare_frontend_env_files,
    set_env_line,
)
from simple_deploy.core.commands import (  # noqa: E402,F401
    CommandResult,
    decode_subprocess_output,
    mask_text,
    run_command,
    run_or_raise,
    stream_command,
)
from simple_deploy.core.db import db_psql_base_command  # noqa: E402,F401
from simple_deploy.core.email import (  # noqa: E402,F401
    SafeFormatDict,
    format_outlook_template,
    normalize_email_list,
)
from simple_deploy.core.env import (  # noqa: E402,F401
    load_dotenv_file,
    load_env,
    require_value,
    to_git_bash_path,
    windows_release_root,
    wsl_to_windows_path,
)
from simple_deploy.core.paths import (  # noqa: E402,F401
    BUILDER_ROOT,
    DEFAULT_BACKEND_APP_ROOT_DIR,
    DEFAULT_TIMEOUT,
    PIP_TRUSTED_HOSTS,
    ROOT,
    TOOLS_CI_ROOT,
)
from simple_deploy.core.release_paths import (  # noqa: E402,F401
    resolve_release_dir,
)
from simple_deploy.core.ssh import (  # noqa: E402,F401
    resolve_ssh_key_path,
    scp_file,
    sh_quote,
    ssh_base_args,
    ssh_command,
    ssh_key_args,
    stream_ssh_command,
)
from simple_deploy.processes.data_sql import (  # noqa: E402,F401
    DB_DATA_UPDATE_APP_NAME,
    DB_DATA_UPDATE_PROCESS_CLEANUP_SCRIPT,
    cleanup_db_data_update_leftovers,
    remote_db_schema_unpack_command,
    remote_db_sql_unpack_command,
    run_db_data_insert,
    run_db_data_update_parallel,
    run_db_maintenance,
    run_db_schema_summary,
    upload_unpack_db_sql_artifact,
)
from simple_deploy.processes.app_deploy import (  # noqa: E402,F401
    backup_app_artifacts,
    deploy_summary_lines,
    management_commands,
    remote_clean_unpack_command,
    run_service_steps,
    unpack_app_artifact,
    upload_app_artifacts,
)
from simple_deploy.processes.mark import (  # noqa: E402,F401
    mark_contour_applied,
    mark_contour_failed,
    mark_contour_failed_best_effort,
)
from simple_deploy.registry.state import validate_contour  # noqa: E402,F401
from simple_deploy.release.artifacts import (  # noqa: E402,F401
    DEFAULT_MAINTENANCE_STUB_ARCHIVE,
    Artifact,
    DbSqlArtifact,
    require_artifact,
    resolve_artifacts,
    resolve_db_data_artifact,
    resolve_db_schema_artifact,
    resolve_maintenance_stub_artifact,
)
from simple_deploy.release.manifest import (  # noqa: E402,F401
    RELEASE_MANIFEST_NAME,
    find_previous_release_manifest,
    load_release_manifest,
)
from simple_deploy.processes.dry_run_checks import (  # noqa: E402,F401
    CATALOG_BUSINESS_KEYS,
    DATA_SQL_INSERT_DIRS,
    DATA_SQL_INSERT_IF_MISSING_DIRS,
    DATA_SQL_MIXED_DIRS,
    DATABASE_SCRIPTS_PREFIX,
    Reporter,
    SqlBusinessKey,
    SqlInsertRow,
    SqlValidationProblem,
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
    check_remote_directory,
    check_repo,
    check_service_permissions,
    check_ssh_key_files,
    check_ssh_runtime,
    check_windows_command,
    derive_service_permission_check,
    find_catalog_business_key_conflicts,
    is_data_insert_idempotent,
    is_insert_if_missing_idempotent,
    is_readable_systemctl_status_result,
    is_sudo_command,
    iter_sql_files,
    iter_values_tuples,
    non_idempotent_data_insert_scripts,
    normalize_sql_table,
    parse_insert_rows,
    parse_sql_literal,
    runtime_local_path,
    split_sql_csv,
    split_sql_statements,
    sudo_list_command,
    validate_backend_data_insert_sql,
)
from simple_deploy.processes.healthcheck import (  # noqa: E402,F401
    ScriptSrcParser,
    check_portal_release_version,
    healthcheck,
    read_http_text,
    script_urls_from_html,
    verify_maintenance_stub_http,
    version_found_in_text,
)
from simple_deploy.processes.notifications import (  # noqa: E402,F401
    git_log_merge_commits,
    merge_request_line,
    release_changelog_text,
    repo_changelog_text,
    send_outlook_success_email,
)

if __name__ == "__main__":
    raise SystemExit(main())
