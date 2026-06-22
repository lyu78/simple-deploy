"""Локальный runner для queued jobs simple-deploy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TypeAlias

from pydantic import BaseModel

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
from simple_deploy.application.services import result_for_request
from simple_deploy.models.state import JobReadModel
from simple_deploy.registry.commands import (
    create_local_job,
    finish_local_job,
    mark_local_job_started,
)
from simple_deploy.registry.queries import job_read_model_from_state
from simple_deploy.types.job import JobKindEnum

RequestModel: TypeAlias = type[RunnerCommandRequest]

REQUEST_MODELS: dict[JobKindEnum, RequestModel] = {
    JobKindEnum.DRY_RUN: DryRunRequest,
    JobKindEnum.BUILD: BuildRequest,
    JobKindEnum.DEPLOY: DeployRequest,
    JobKindEnum.PIPELINE: PipelineRequest,
    JobKindEnum.SET_BASELINE: SetBaselineRequest,
    JobKindEnum.MARK_APPLIED: MarkAppliedRequest,
    JobKindEnum.MARK_FAILED: MarkFailedRequest,
}


@dataclass(frozen=True)
class LocalJobRunResult:
    """Результат выполнения одной local job."""

    job: JobReadModel
    process_result: ProcessResult


def job_kind_for_request(request: RunnerCommandRequest) -> JobKindEnum:
    """Возвращает kind local job для application request."""
    if isinstance(request, DryRunRequest):
        return JobKindEnum.DRY_RUN
    if isinstance(request, BuildRequest):
        return JobKindEnum.BUILD
    if isinstance(request, DeployRequest):
        return JobKindEnum.DEPLOY
    if isinstance(request, PipelineRequest):
        return JobKindEnum.PIPELINE
    if isinstance(request, SetBaselineRequest):
        return JobKindEnum.SET_BASELINE
    if isinstance(request, MarkAppliedRequest):
        return JobKindEnum.MARK_APPLIED
    if isinstance(request, MarkFailedRequest):
        return JobKindEnum.MARK_FAILED
    raise TypeError(f"Unsupported application request: {type(request)!r}")


def _request_scope(request: RunnerCommandRequest) -> tuple[str, str]:
    """Извлекает contour/build_version для storage-index полей job."""
    contour = getattr(request, "contour", "")
    build_version = getattr(request, "build_version", "")
    contour_value = contour.value if hasattr(contour, "value") else str(contour)
    return contour_value, str(build_version)


def request_payload(request: RunnerCommandRequest) -> dict[str, object]:
    """Сериализует application request в JSON-friendly payload local job."""
    if not isinstance(request, BaseModel):
        raise TypeError(f"Unsupported job request payload: {type(request)!r}")
    return request.model_dump(mode="json")


def create_job_for_request(
    request: RunnerCommandRequest,
    *,
    log_path: str = "",
) -> JobReadModel:
    """Создает queued local job для уже валидированного application request."""
    kind = job_kind_for_request(request)
    contour, build_version = _request_scope(request)
    return create_local_job(
        kind,
        contour=contour,
        build_version=build_version,
        payload=request_payload(request),
        log_path=log_path,
    ).job


def request_from_job(job: JobReadModel) -> RunnerCommandRequest:
    """Восстанавливает application request из payload local job."""
    model = REQUEST_MODELS.get(job.kind)
    if model is None:
        raise ValueError(f"Unsupported local job kind: {job.kind}")
    payload = json.loads(job.payload_json or "{}")
    if job.contour and "contour" not in payload:
        payload["contour"] = job.contour
    if job.build_version and "build_version" not in payload:
        payload["build_version"] = job.build_version
    return model.model_validate(payload)


def run_local_job(job_id: int) -> LocalJobRunResult:
    """Выполняет queued local job и фиксирует terminal status."""
    job = job_read_model_from_state(job_id)
    if job is None:
        raise ValueError(f"Local job not found: id={job_id}")
    if job.status != "queued":
        raise ValueError(
            f"Local job must be queued before run: "
            f"id={job_id} status={job.status}"
        )

    running = mark_local_job_started(job_id).job
    return run_claimed_job(running.id)


def run_claimed_job(job_id: int) -> LocalJobRunResult:
    """Executes a claimed/running local job and stores terminal status."""
    running = job_read_model_from_state(job_id)
    if running is None:
        raise ValueError(f"Local job not found: id={job_id}")
    if running.status != "running":
        raise ValueError(
            f"Local job must be running before execution: "
            f"id={job_id} status={running.status}"
        )

    try:
        request = request_from_job(running)
        process_result = result_for_request(request)
    except Exception as exc:
        process_result = ProcessResult.failure(str(exc))

    status = "success" if process_result.ok else "failed"
    error = "" if process_result.ok else process_result.message
    finished = finish_local_job(job_id, status, error=error).job
    return LocalJobRunResult(finished, process_result)


__all__ = [
    "LocalJobRunResult",
    "REQUEST_MODELS",
    "create_job_for_request",
    "job_kind_for_request",
    "request_from_job",
    "request_payload",
    "run_claimed_job",
    "run_local_job",
]
