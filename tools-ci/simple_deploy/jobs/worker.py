"""Polling worker for SQLite-backed local jobs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from simple_deploy.core.job_logging import (
    JOB_LOGGER_NAME,
    create_log_file,
    job_log_output,
)
from simple_deploy.jobs.runner import LocalJobRunResult, run_claimed_job
from simple_deploy.registry.commands import (
    claim_next_local_job,
    set_local_job_log_path,
)
from simple_deploy.models.state import JobReadModel

WORKER_IDLE_EXIT_CODE = 2


@dataclass(frozen=True)
class WorkerOnceResult:
    """Result of one worker polling iteration."""

    job: JobReadModel | None
    run_result: LocalJobRunResult | None = None

    @property
    def claimed(self) -> bool:
        return self.job is not None


def _job_log_command(job: JobReadModel) -> str:
    parts = ["job", str(job.id), job.kind.value]
    if job.contour:
        parts.append(job.contour)
    if job.build_version:
        parts.append(job.build_version)
    return "-".join(parts)


def run_worker_once() -> WorkerOnceResult:
    """Claims and runs at most one queued local job."""
    claimed = claim_next_local_job()
    if claimed is None:
        return WorkerOnceResult(job=None)

    job = claimed.job
    log_path = create_log_file(_job_log_command(job))
    job = set_local_job_log_path(job.id, str(log_path)).job
    with job_log_output(_job_log_command(job), log_path=log_path):
        logger = logging.getLogger(JOB_LOGGER_NAME)
        logger.info(
            "WORKER claimed job id=%s kind=%s", job.id, job.kind.value
        )
        run_result = run_claimed_job(job.id)
        logger.info(
            "WORKER finished job id=%s status=%s",
            run_result.job.id,
            run_result.job.status.value,
        )
    return WorkerOnceResult(job=job, run_result=run_result)


def run_worker_loop(
    *,
    once: bool = False,
    poll_interval: float = 2.0,
) -> int:
    """Runs the polling worker until stopped or one iteration finishes."""
    interval = max(0.1, poll_interval)
    while True:
        result = run_worker_once()
        if result.claimed:
            if once:
                return 0
            continue
        if once:
            return WORKER_IDLE_EXIT_CODE
        time.sleep(interval)


__all__ = [
    "WORKER_IDLE_EXIT_CODE",
    "WorkerOnceResult",
    "run_worker_loop",
    "run_worker_once",
]
