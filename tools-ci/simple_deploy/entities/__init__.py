"""Чистые DDD entities/value objects simple-deploy.

Entities описывают смысловые инварианты предметной области без привязки к
SQLite, FastAPI, SSH, файловой системе или текущему runner-у. Например,
``Release`` может проверять, что successful bundle относится к той же версии, а
``SourceSnapshot`` - что набор source revisions непустой и без дублей repo id.

Этот слой не читает registry, не запускает build/deploy и не является DTO для
HTTP. Если объекту нужны side effects, состояние БД или доступ к VM, это уже
application/process/registry слой, а не entity.
"""

from simple_deploy.entities.release import (
    Release,
    ReleaseArtifactRef,
    ReleaseBundle,
    ReleasePlacement,
    SourceRepositoryRevision,
    SourceSnapshot,
)

__all__ = [
    "Release",
    "ReleaseArtifactRef",
    "ReleaseBundle",
    "ReleasePlacement",
    "SourceRepositoryRevision",
    "SourceSnapshot",
]
