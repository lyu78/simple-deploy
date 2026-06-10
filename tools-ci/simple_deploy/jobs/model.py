"""Модель локальных заданий, записанных в SQLite-состоянии.

Модуль дает import path для записей и операций ``local_jobs``, ориентированный
на задания. Источником истины остается общая SQLite-база состояния релизов,
поэтому этот файл только переэкспортирует dataclass-модель и функции жизненного
цикла задания без изменения формата данных.
"""

from __future__ import annotations

from simple_deploy.release.state import (
    JOB_STATUSES,
    JobRecord,
    create_job,
    get_job,
    list_jobs,
    mark_job_finished,
    mark_job_started,
)

__all__ = [
    "JOB_STATUSES",
    "JobRecord",
    "create_job",
    "get_job",
    "list_jobs",
    "mark_job_finished",
    "mark_job_started",
]
