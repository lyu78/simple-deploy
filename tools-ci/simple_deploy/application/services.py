"""Сервисы application layer для release/deploy команд.

Сервисный слой отделяет внешние adapters от операторских процессов:

* CLI adapter отвечает за ``argparse``, лог-файл и dispatch;
* web/API или local job runner смогут вызывать те же функции без импорта
  CLI-модуля;
* process modules пока остаются владельцами подробной orchestration-логики
  build/deploy/mark.

Функции принимают request DTO из ``application.requests``. Совместимость с
текущими process modules, которые пока ожидают namespace-like input, спрятана
в приватном adapter-е этого модуля.
"""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from simple_deploy.application.requests import (
    BuildRequest,
    DeployRequest,
    DryRunRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    SetBaselineRequest,
)
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


def _process_args(request: BaseModel) -> SimpleNamespace:
    """Преобразует application request во временный process input."""
    return SimpleNamespace(**request.model_dump(mode="python"))


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
        app_only=request.app_only,
    )


def dry_run(request: DryRunRequest) -> bool:
    """Запускает application use case preflight-проверок."""
    return _dry_run_process(_process_args(request))


def build(request: BuildRequest) -> int:
    """Запускает application use case сборки release bundle."""
    return _build_process(_process_args(request))


def deploy(request: DeployRequest) -> int:
    """Запускает application use case применения release bundle на контур."""
    return _deploy_process(_process_args(request))


def pipeline(request: PipelineRequest) -> int:
    """Выполняет dry-run, build и deploy latest как один use case."""
    if not dry_run(_pipeline_dry_run_request(request)):
        return 1
    build_rc = build(_pipeline_build_request(request))
    if build_rc != 0:
        return build_rc
    return deploy(_pipeline_deploy_request(request))


def set_baseline(request: SetBaselineRequest) -> int:
    """Запускает application use case ручной установки baseline контура."""
    return _set_baseline_process(_process_args(request))


def mark_applied(request: MarkAppliedRequest) -> int:
    """Запускает application use case ручной фиксации успешного deploy."""
    return _mark_applied_process(_process_args(request))


def mark_failed(request: MarkFailedRequest) -> int:
    """Запускает application use case ручной фиксации неуспешного deploy."""
    return _mark_failed_process(_process_args(request))


__all__ = [
    "build",
    "deploy",
    "dry_run",
    "mark_applied",
    "mark_failed",
    "pipeline",
    "set_baseline",
]
