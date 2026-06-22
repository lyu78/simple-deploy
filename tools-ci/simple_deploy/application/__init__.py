"""
Прикладной слой use cases simple-deploy.

Application layer - это стабильная граница для CLI, web/API и будущих local
jobs. Он принимает request-модели, вызывает process/use-case реализации и
возвращает результат без знания о HTTP, argparse dispatch или SQLite schema
details.

Сервисы делегируют существующим ``processes`` modules через типизированные
request DTO. CLI остается внешним adapter-ом: он разбирает ``argparse`` и
сразу преобразует результат в request-модель, поэтому application/process
граница не зависит от формы командной строки.
"""

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
from simple_deploy.application.services import (
    build,
    build_result,
    deploy,
    deploy_result,
    dry_run,
    dry_run_result,
    mark_applied,
    mark_applied_result,
    mark_failed,
    mark_failed_result,
    pipeline,
    pipeline_result,
    result_for_request,
    set_baseline,
    set_baseline_result,
)

__all__ = [
    "BuildRequest",
    "DeployRequest",
    "DryRunRequest",
    "MarkAppliedRequest",
    "MarkFailedRequest",
    "PipelineRequest",
    "ProcessResult",
    "RunnerCommandRequest",
    "SetBaselineRequest",
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
