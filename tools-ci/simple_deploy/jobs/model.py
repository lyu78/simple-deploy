"""Модель локальных заданий, записанных в SQLite-состоянии.

Модуль дает import path для записей и операций ``local_jobs``, ориентированный
на задания. Источником истины остается общая SQLite-база состояния релизов,
поэтому этот файл только переэкспортирует dataclass-модель и функции жизненного
цикла задания без изменения формата данных.
"""

from __future__ import annotations

from simple_deploy.registry.state import (
    cancel_job,
    claim_next_job,
    create_job,
    get_job,
    JOB_STATUSES,
    JobRecord,
    list_jobs,
    mark_job_finished,
    mark_job_started,
    requeue_job,
    set_job_log_path,
)

__all__ = [
    "JOB_STATUSES",
    "JobRecord",
    "cancel_job",
    "claim_next_job",
    "create_job",
    "get_job",
    "list_jobs",
    "mark_job_finished",
    "mark_job_started",
    "requeue_job",
    "set_job_log_path",
]
