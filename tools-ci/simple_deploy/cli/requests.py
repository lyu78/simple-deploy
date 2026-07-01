"""Adapter из legacy CLI args в request DTO application layer."""

from __future__ import annotations

import argparse

from simple_deploy.application.requests import (
    BuildRequest,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DeployRequest,
    DryRunRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    RunnerCommandRequest,
    SetBaselineRequest,
)
from simple_deploy.core.paths import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_ENV_FILE,
    DEFAULT_SECRETS_FILE,
)


def _env_file_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """Возвращает общие пути env/secrets из CLI args или defaults."""
    return {
        "env_file": getattr(args, "env_file", DEFAULT_ENV_FILE),
        "secrets_file": getattr(args, "secrets_file", DEFAULT_SECRETS_FILE),
    }


def _runtime_config_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """Возвращает путь runtime config из CLI args или default."""
    return {
        "config_file": getattr(args, "config_file", DEFAULT_CONFIG_FILE),
    }


def dry_run_request_from_args(args: argparse.Namespace) -> DryRunRequest:
    """Собирает request preflight-проверок из legacy CLI args."""
    return DryRunRequest(
        **_env_file_kwargs(args),
        **_runtime_config_kwargs(args),
        skip_data_sql_artifacts=getattr(
            args, "skip_data_sql_artifacts", False
        ),
        app_only=getattr(args, "app_only", False),
    )


def build_request_from_args(args: argparse.Namespace) -> BuildRequest:
    """Собирает request сборки release bundle из legacy CLI args."""
    return BuildRequest(
        **_env_file_kwargs(args),
        timeout=getattr(args, "timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS),
        skip_data_sql_artifacts=getattr(
            args, "skip_data_sql_artifacts", False
        ),
    )


def deploy_request_from_args(args: argparse.Namespace) -> DeployRequest:
    """Собирает request deploy выбранного release bundle из CLI args."""
    return DeployRequest(
        **_env_file_kwargs(args),
        **_runtime_config_kwargs(args),
        build_version=getattr(args, "build_version", ""),
        latest=getattr(args, "latest", False),
        contour=getattr(args, "contour", "dev"),
        include_set_default_sql=getattr(
            args, "include_set_default_sql", False
        ),
        include_data_migration_sql=getattr(
            args, "include_data_migration_sql", False
        ),
        app_only=getattr(args, "app_only", False),
    )


def pipeline_request_from_args(args: argparse.Namespace) -> PipelineRequest:
    """Собирает request pipeline из legacy CLI args.

    CLI по совместимости принимает ``--build-version`` и ``--latest`` для
    pipeline, но application use case всегда выполняет build, а затем deploy
    latest bundle. Эти legacy flags не входят в request contract.
    """
    return PipelineRequest(
        **_env_file_kwargs(args),
        **_runtime_config_kwargs(args),
        timeout=getattr(args, "timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS),
        contour=getattr(args, "contour", "dev"),
        include_set_default_sql=getattr(
            args, "include_set_default_sql", False
        ),
        include_data_migration_sql=getattr(
            args, "include_data_migration_sql", False
        ),
        skip_data_sql_artifacts=getattr(
            args, "skip_data_sql_artifacts", False
        ),
        app_only=getattr(args, "app_only", False),
    )


def set_baseline_request_from_args(
    args: argparse.Namespace,
) -> SetBaselineRequest:
    """Собирает request ручной установки baseline из legacy CLI args."""
    return SetBaselineRequest(
        **_env_file_kwargs(args),
        **_runtime_config_kwargs(args),
        contour=getattr(args, "contour"),
        build_version=getattr(args, "build_version", ""),
        backend_commit=getattr(args, "backend_commit", ""),
    )


def mark_applied_request_from_args(
    args: argparse.Namespace,
) -> MarkAppliedRequest:
    """Собирает request ручной фиксации успешного deploy из CLI args."""
    return MarkAppliedRequest(
        **_env_file_kwargs(args),
        contour=getattr(args, "contour"),
        build_version=getattr(args, "build_version"),
    )


def mark_failed_request_from_args(
    args: argparse.Namespace,
) -> MarkFailedRequest:
    """Собирает request ручной фиксации failed deploy из CLI args."""
    return MarkFailedRequest(
        **_env_file_kwargs(args),
        contour=getattr(args, "contour"),
        build_version=getattr(args, "build_version"),
        error=getattr(args, "error"),
    )


def request_from_args(args: argparse.Namespace) -> RunnerCommandRequest:
    """Преобразует разобранную CLI-команду в application request DTO."""
    command = getattr(args, "command", "")
    if command == "dry-run":
        return dry_run_request_from_args(args)
    if command == "build":
        return build_request_from_args(args)
    if command == "deploy":
        return deploy_request_from_args(args)
    if command == "pipeline":
        return pipeline_request_from_args(args)
    if command == "set-baseline":
        return set_baseline_request_from_args(args)
    if command == "mark-applied":
        return mark_applied_request_from_args(args)
    if command == "mark-failed":
        return mark_failed_request_from_args(args)
    raise ValueError(f"Unknown command: {command}")


__all__ = [
    "build_request_from_args",
    "deploy_request_from_args",
    "dry_run_request_from_args",
    "mark_applied_request_from_args",
    "mark_failed_request_from_args",
    "pipeline_request_from_args",
    "request_from_args",
    "set_baseline_request_from_args",
]
