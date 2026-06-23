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
    record_worker_heartbeat,
    set_local_job_log_path,
)
from simple_deploy.models.state import JobReadModel

DEFAULT_WORKER_ID = "local"
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


def run_worker_once(*, worker_id: str = DEFAULT_WORKER_ID) -> WorkerOnceResult:
    """Claims and runs at most one queued local job."""
    record_worker_heartbeat(
        worker_id=worker_id,
        status="idle",
        message="polling local_jobs",
    )
    claimed = claim_next_local_job()
    if claimed is None:
        record_worker_heartbeat(
            worker_id=worker_id,
            status="idle",
            message="queue empty",
        )
        return WorkerOnceResult(job=None)

    job = claimed.job
    record_worker_heartbeat(
        worker_id=worker_id,
        status="running",
        current_job_id=job.id,
        message=f"claimed job id={job.id}",
    )
    log_path = create_log_file(_job_log_command(job))
    job = set_local_job_log_path(job.id, str(log_path)).job
    try:
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
    except Exception as exc:
        record_worker_heartbeat(
            worker_id=worker_id,
            status="error",
            current_job_id=job.id,
            message=str(exc),
        )
        raise
    record_worker_heartbeat(
        worker_id=worker_id,
        status="idle",
        message=(
            f"finished job id={run_result.job.id} "
            f"status={run_result.job.status.value}"
        ),
    )
    return WorkerOnceResult(job=job, run_result=run_result)


def _record_worker_stopped(worker_id: str, message: str) -> None:
    """Best-effort запись остановки worker-а перед выходом."""
    try:
        record_worker_heartbeat(
            worker_id=worker_id,
            status="stopped",
            message=message,
        )
    except Exception:
        logging.getLogger(__name__).debug(
            "Failed to record worker stop heartbeat", exc_info=True
        )


def run_worker_loop(
    *,
    once: bool = False,
    poll_interval: float = 2.0,
    worker_id: str = DEFAULT_WORKER_ID,
) -> int:
    """Runs the polling worker until stopped or one iteration finishes."""
    interval = max(0.1, poll_interval)
    stopped_message = ""
    record_worker_heartbeat(
        worker_id=worker_id,
        status="starting",
        message="worker starting",
    )
    try:
        while True:
            result = run_worker_once(worker_id=worker_id)
            if result.claimed:
                if once:
                    stopped_message = "worker --once stopped"
                    return 0
                continue
            if once:
                stopped_message = "worker --once stopped"
                return WORKER_IDLE_EXIT_CODE
            time.sleep(interval)
    except KeyboardInterrupt:
        stopped_message = "worker interrupted"
        raise
    except Exception as exc:
        record_worker_heartbeat(
            worker_id=worker_id,
            status="error",
            message=str(exc),
        )
        raise
    finally:
        if stopped_message:
            _record_worker_stopped(worker_id, stopped_message)


__all__ = [
    "DEFAULT_WORKER_ID",
    "WORKER_IDLE_EXIT_CODE",
    "WorkerOnceResult",
    "run_worker_loop",
    "run_worker_once",
]
