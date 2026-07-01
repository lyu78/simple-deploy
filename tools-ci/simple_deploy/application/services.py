"""Сервисы application layer для release/deploy команд.

Сервисный слой отделяет внешние adapters от операторских процессов:

* CLI adapter отвечает за ``argparse``, лог-файл и dispatch;
* web/API или local job runner смогут вызывать те же функции без импорта
  CLI-модуля;
* process modules остаются владельцами подробной orchestration-логики
  build/deploy/mark и получают типизированные request DTO без CLI-деталей.

Функции принимают request DTO из ``application.requests`` и передают их дальше
без промежуточного ``argparse.Namespace``.
"""

from __future__ import annotations

from simple_deploy.application.requests import (
    BuildRequest,
    DeployRequest,
    DryRunRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    RunnerCommandRequest,
    SetBaselineRequest,
)
from simple_deploy.application.results import ProcessResult
from simple_deploy.processes.build import build as _build_process
from simple_deploy.processes.deploy import deploy as _deploy_process
from simple_deploy.processes.dry_run import dry_run as _dry_run_process
from simple_deploy.processes.mark import (
    mark_applied as _mark_applied_process,
)
from simple_deploy.processes.mark import (
    mark_failed as _mark_failed_process,
)
from simple_deploy.processes.mark import (
    set_baseline as _set_baseline_process,
)


def _pipeline_dry_run_request(request: PipelineRequest) -> DryRunRequest:
    """Выделяет dry-run часть pipeline request."""
    return DryRunRequest(
        env_file=request.env_file,
        secrets_file=request.secrets_file,
        config_file=request.config_file,
        skip_data_sql_artifacts=request.skip_data_sql_artifacts,
        app_only=request.app_only,
    )


def _pipeline_build_request(request: PipelineRequest) -> BuildRequest:
    """Выделяет build часть pipeline request."""
    return BuildRequest(
        env_file=request.env_file,
        secrets_file=request.secrets_file,
        timeout=request.timeout,
        skip_data_sql_artifacts=request.skip_data_sql_artifacts,
    )


def _pipeline_deploy_request(request: PipelineRequest) -> DeployRequest:
    """Выделяет deploy latest часть pipeline request."""
    return DeployRequest(
        env_file=request.env_file,
        secrets_file=request.secrets_file,
        config_file=request.config_file,
        build_version="",
        latest=True,
        contour=request.contour,
        include_set_default_sql=request.include_set_default_sql,
        include_data_migration_sql=request.include_data_migration_sql,
        app_only=request.app_only,
    )


def dry_run_result(request: DryRunRequest) -> ProcessResult:
    """Запускает application use case preflight-проверок и возвращает result DTO."""
    return _dry_run_process(request)


def build_result(request: BuildRequest) -> ProcessResult:
    """Запускает application use case сборки release bundle и возвращает result DTO."""
    return _build_process(request)


def deploy_result(request: DeployRequest) -> ProcessResult:
    """Запускает application use case применения release bundle и возвращает result DTO."""
    return _deploy_process(request)


def dry_run(request: DryRunRequest) -> bool:
    """Запускает application use case preflight-проверок."""
    return dry_run_result(request).ok


def build(request: BuildRequest) -> int:
    """Запускает application use case сборки release bundle."""
    return build_result(request).exit_code


def deploy(request: DeployRequest) -> int:
    """Запускает application use case применения release bundle на контур."""
    return deploy_result(request).exit_code


def pipeline_result(request: PipelineRequest) -> ProcessResult:
    """Выполняет dry-run, build и deploy latest как один use case."""
    dry_run_check = dry_run_result(_pipeline_dry_run_request(request))
    if not dry_run_check.ok:
        return dry_run_check
    build_check = build_result(_pipeline_build_request(request))
    if not build_check.ok:
        return build_check
    return deploy_result(_pipeline_deploy_request(request))


def pipeline(request: PipelineRequest) -> int:
    """Выполняет dry-run, build и deploy latest как один use case."""
    return pipeline_result(request).exit_code


def set_baseline_result(request: SetBaselineRequest) -> ProcessResult:
    """Запускает ручную установку baseline и возвращает result DTO."""
    return _set_baseline_process(request)


def set_baseline(request: SetBaselineRequest) -> int:
    """Запускает application use case ручной установки baseline контура."""
    return set_baseline_result(request).exit_code


def mark_applied_result(request: MarkAppliedRequest) -> ProcessResult:
    """Запускает ручную фиксацию успешного deploy и возвращает result DTO."""
    return _mark_applied_process(request)


def mark_applied(request: MarkAppliedRequest) -> int:
    """Запускает application use case ручной фиксации успешного deploy."""
    return mark_applied_result(request).exit_code


def mark_failed_result(request: MarkFailedRequest) -> ProcessResult:
    """Запускает ручную фиксацию неуспешного deploy и возвращает result DTO."""
    return _mark_failed_process(request)


def mark_failed(request: MarkFailedRequest) -> int:
    """Запускает application use case ручной фиксации неуспешного deploy."""
    return mark_failed_result(request).exit_code


def result_for_request(request: RunnerCommandRequest) -> ProcessResult:
    """Запускает application request и возвращает структурированный результат."""
    if isinstance(request, DryRunRequest):
        return dry_run_result(request)
    if isinstance(request, BuildRequest):
        return build_result(request)
    if isinstance(request, DeployRequest):
        return deploy_result(request)
    if isinstance(request, PipelineRequest):
        return pipeline_result(request)
    if isinstance(request, SetBaselineRequest):
        return set_baseline_result(request)
    if isinstance(request, MarkAppliedRequest):
        return mark_applied_result(request)
    if isinstance(request, MarkFailedRequest):
        return mark_failed_result(request)
    raise TypeError(f"Unsupported application request: {type(request)!r}")


__all__ = [
    "build",
    "build_result",
    "deploy",
    "deploy_result",
    "dry_run",
    "dry_run_result",
    "mark_applied",
    "mark_applied_result",
    "mark_failed",
    "mark_failed_result",
    "pipeline",
    "pipeline_result",
    "result_for_request",
    "set_baseline",
    "set_baseline_result",
]
