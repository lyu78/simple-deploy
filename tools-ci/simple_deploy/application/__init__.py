"""
Прикладной слой use cases simple-deploy.

Application layer - это стабильная граница для CLI, web/API и будущих local
jobs. Он принимает request-модели, вызывает process/use-case реализации и
возвращает результат без знания о HTTP, argparse dispatch или SQLite schema
details.

На текущем срезе сервисы делегируют существующим ``processes`` modules через
приватный adapter к их namespace-like контракту. Это сохраняет поведение
Windows runner-а и дает отдельную точку подключения для будущих API/job
endpoints.
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
from simple_deploy.application.services import (
    build,
    deploy,
    dry_run,
    mark_applied,
    mark_failed,
    pipeline,
    set_baseline,
)

__all__ = [
    "BuildRequest",
    "DeployRequest",
    "DryRunRequest",
    "MarkAppliedRequest",
    "MarkFailedRequest",
    "PipelineRequest",
    "RunnerCommandRequest",
    "SetBaselineRequest",
    "build",
    "deploy",
    "dry_run",
    "mark_applied",
    "mark_failed",
    "pipeline",
    "set_baseline",
]
