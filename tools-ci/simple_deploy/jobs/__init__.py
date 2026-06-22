"""Пакет локальных заданий для долгих операций simple-deploy.

Web/API создает queued job и возвращает ее состояние, а выполнение делегируется
local runner-у. Источник истины остается в общей SQLite-базе registry state.
"""

from simple_deploy.jobs.runner import (
    create_job_for_request,
    job_kind_for_request,
    LocalJobRunResult,
    request_from_job,
    request_payload,
    run_local_job,
)
from simple_deploy.jobs.worker import (
    WORKER_IDLE_EXIT_CODE,
    WorkerOnceResult,
    run_worker_loop,
    run_worker_once,
)

__all__ = [
    "LocalJobRunResult",
    "WORKER_IDLE_EXIT_CODE",
    "WorkerOnceResult",
    "create_job_for_request",
    "job_kind_for_request",
    "request_from_job",
    "request_payload",
    "run_worker_loop",
    "run_worker_once",
    "run_local_job",
]
