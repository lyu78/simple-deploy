"""
Read/query слой поверх registry state.

Модуль собирает внутренние read models для dashboard/API из локального SQLite
registry. Он не меняет состояние, не запускает процессы и не знает про HTTP.
Web/API получает отсюда готовые проекции, а затем преобразует их во внешние
DTO.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from simple_deploy.models.state import (
    BuildAttemptReadModel,
    ContourStateReadModel,
    DeploymentAttemptReadModel,
    ExternalRequestReadModel,
    JobReadModel,
    ReleaseBundleReadModel,
    ReleaseReadModel,
    ReleaseReferenceReadModel,
    StateSnapshotReadModel,
    WorkerHealthReadModel,
    WorkerHeartbeatReadModel,
)
from simple_deploy.registry.state import (
    all_contour_states,
    connect_state_db,
    count_jobs_by_status,
    get_job,
    get_release,
    get_worker_heartbeat,
    list_build_attempts,
    list_deployment_attempts,
    list_external_requests,
    list_jobs,
    list_releases,
)
from simple_deploy.types.status import BuildAttemptStatusEnum


def bounded_limit(limit: int) -> int:
    """Ограничивает пользовательский ``limit`` безопасным диапазоном."""
    return max(1, min(limit, 200))


def utc_timestamp_age_seconds(value: str) -> float | None:
    """Возвращает возраст UTC timestamp в секундах или ``None``."""
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - timestamp).total_seconds()


def worker_health_status(
    heartbeat: WorkerHeartbeatReadModel | None,
    *,
    stale_after_seconds: int,
) -> str:
    """Классифицирует доступность worker-а для operator dashboard."""
    if heartbeat is None or heartbeat.status == "stopped":
        return "offline"
    age_seconds = utc_timestamp_age_seconds(heartbeat.updated_at)
    if age_seconds is None or age_seconds > stale_after_seconds:
        return "stale"
    if heartbeat.status == "running" or heartbeat.current_job_id is not None:
        return "running"
    if heartbeat.status == "error":
        return "error"
    return "idle"


def release_sort_key(release: ReleaseReadModel) -> tuple[str, str]:
    """Возвращает ключ сортировки ресурса релиза для API/read models."""
    timestamps = [attempt.finished_at for attempt in release.build_attempts]
    timestamps.extend(
        attempt.finished_at for attempt in release.deployment_attempts
    )
    timestamps.extend(
        request.updated_at for request in release.external_requests
    )
    if release.bundle is not None:
        timestamps.append(release.bundle.created_at)
    return (max(timestamps, default=""), release.build_version)


def release_read_models(
    bundles: list[ReleaseBundleReadModel],
    build_attempts: list[BuildAttemptReadModel],
    deployment_attempts: list[DeploymentAttemptReadModel],
    external_requests: list[ExternalRequestReadModel],
    *,
    limit: int,
) -> list[ReleaseReadModel]:
    """Собирает ресурсные модели чтения релизов поверх строк registry state."""
    records: dict[str, dict] = {}

    def ensure(build_version: str) -> dict:
        return records.setdefault(
            build_version,
            {
                "bundle": None,
                "build_attempts": [],
                "deployment_attempts": [],
                "external_requests": [],
            },
        )

    for bundle in bundles:
        ensure(bundle.build_version)["bundle"] = bundle
    for attempt in build_attempts:
        ensure(attempt.build_version)["build_attempts"].append(attempt)
    for attempt in deployment_attempts:
        ensure(attempt.build_version)["deployment_attempts"].append(attempt)
    for request in external_requests:
        ensure(request.build_version)["external_requests"].append(request)

    releases = []
    for build_version, record in records.items():
        bundle = record["bundle"]
        attempts = sorted(
            record["build_attempts"],
            key=lambda attempt: attempt.id,
            reverse=True,
        )
        latest_attempt = attempts[0] if attempts else None
        if bundle is not None:
            build_status = BuildAttemptStatusEnum.SUCCESS
            backend_commit = bundle.backend_commit
            frontend_commit = bundle.frontend_commit
        elif latest_attempt is not None:
            build_status = latest_attempt.status
            backend_commit = latest_attempt.backend_commit
            frontend_commit = latest_attempt.frontend_commit
        else:
            build_status = BuildAttemptStatusEnum.UNDEFINED
            backend_commit = ""
            frontend_commit = ""
        releases.append(
            ReleaseReadModel(
                build_version=build_version,
                build_status=build_status,
                backend_commit=backend_commit,
                frontend_commit=frontend_commit,
                bundle=bundle,
                build_attempts=attempts,
                deployment_attempts=sorted(
                    record["deployment_attempts"],
                    key=lambda attempt: attempt.id,
                    reverse=True,
                ),
                external_requests=sorted(
                    record["external_requests"],
                    key=lambda request: request.id,
                    reverse=True,
                ),
            )
        )

    return sorted(releases, key=release_sort_key, reverse=True)[:limit]


def release_read_models_from_state(limit: int = 50) -> list[ReleaseReadModel]:
    """Читает registry state и возвращает ресурсные модели чтения релизов."""
    limit = bounded_limit(limit)
    with closing(connect_state_db()) as connection:
        bundles = [
            ReleaseBundleReadModel.model_validate(record)
            for record in list_releases(connection, limit=limit)
        ]
        build_attempts = [
            BuildAttemptReadModel.model_validate(record)
            for record in list_build_attempts(connection, limit=limit)
        ]
        deployment_attempts = [
            DeploymentAttemptReadModel.model_validate(record)
            for record in list_deployment_attempts(connection, limit=limit)
        ]
        external_requests = [
            ExternalRequestReadModel.model_validate(request)
            for request in list_external_requests(connection, limit=limit)
        ]

    return release_read_models(
        bundles,
        build_attempts,
        deployment_attempts,
        external_requests,
        limit=limit,
    )


def release_bundle_read_model_from_state(
    build_version: str,
) -> ReleaseBundleReadModel | None:
    """Читает один release bundle из registry state по build version."""
    with closing(connect_state_db()) as connection:
        release = get_release(connection, build_version)
    if release is None:
        return None
    return ReleaseBundleReadModel.model_validate(release)


def release_reference_read_model(
    release: ReleaseReadModel,
) -> ReleaseReferenceReadModel:
    """Строит компактную ссылку на ресурс релиза для вложенных проекций."""
    return ReleaseReferenceReadModel(
        build_version=release.build_version,
        build_status=release.build_status,
        backend_commit=release.backend_commit,
        frontend_commit=release.frontend_commit,
    )


def contour_state_read_models(
    contour_states: dict,
    releases: list[ReleaseReadModel],
) -> dict[str, ContourStateReadModel | None]:
    """Обогащает состояния контуров ссылками на ресурсы релизов."""
    release_refs = {
        release.build_version: release_reference_read_model(release)
        for release in releases
    }
    contours: dict[str, ContourStateReadModel | None] = {}
    for contour, state in contour_states.items():
        if state is None:
            contours[contour] = None
            continue
        model = ContourStateReadModel.model_validate(state)
        release_ref = release_refs.get(model.last_success_release)
        if release_ref is None:
            release_ref = ReleaseReferenceReadModel(
                build_version=model.last_success_release,
                build_status=BuildAttemptStatusEnum.SUCCESS,
                backend_commit=model.last_success_backend_commit,
            )
        contours[contour] = model.model_copy(
            update={"last_success_release_ref": release_ref}
        )
    return contours


def job_read_models_from_state(limit: int = 50) -> list[JobReadModel]:
    """Читает последние локальные jobs из registry state."""
    with closing(connect_state_db()) as connection:
        return [
            JobReadModel.model_validate(job)
            for job in list_jobs(connection, limit=bounded_limit(limit))
        ]


def job_read_model_from_state(job_id: int) -> JobReadModel | None:
    """Читает одну local job как read model без раскрытия storage dataclass."""
    with closing(connect_state_db()) as connection:
        job = get_job(connection, job_id)
    if job is None:
        return None
    return JobReadModel.model_validate(job)


def external_request_read_models_from_state(
    limit: int = 50,
) -> list[ExternalRequestReadModel]:
    """Читает последние external TEST/PROD requests из registry state."""
    with closing(connect_state_db()) as connection:
        return [
            ExternalRequestReadModel.model_validate(request)
            for request in list_external_requests(
                connection, limit=bounded_limit(limit)
            )
        ]


def worker_health_read_model_from_state(
    *,
    stale_after_seconds: int = 10,
) -> WorkerHealthReadModel:
    """Читает heartbeat и счетчики jobs для operator dashboard."""
    with closing(connect_state_db()) as connection:
        heartbeat_record = get_worker_heartbeat(connection)
        job_counts = count_jobs_by_status(connection)
    heartbeat = (
        WorkerHeartbeatReadModel.model_validate(heartbeat_record)
        if heartbeat_record is not None
        else None
    )
    return WorkerHealthReadModel(
        status=worker_health_status(
            heartbeat, stale_after_seconds=stale_after_seconds
        ),
        heartbeat=heartbeat,
        queued_jobs=job_counts.get("queued", 0),
        running_jobs=job_counts.get("running", 0),
        stale_after_seconds=stale_after_seconds,
    )


def state_snapshot_read_model(limit: int = 50) -> StateSnapshotReadModel:
    """Собирает внутреннюю модель чтения локального состояния релизов."""
    limit = bounded_limit(limit)
    with closing(connect_state_db()) as connection:
        contour_states = all_contour_states(connection)
        bundles = [
            ReleaseBundleReadModel.model_validate(record)
            for record in list_releases(connection, limit=limit)
        ]
        build_attempts = [
            BuildAttemptReadModel.model_validate(record)
            for record in list_build_attempts(connection, limit=limit)
        ]
        deployment_attempts = [
            DeploymentAttemptReadModel.model_validate(record)
            for record in list_deployment_attempts(connection, limit=limit)
        ]
        external_requests = [
            ExternalRequestReadModel.model_validate(request)
            for request in list_external_requests(connection, limit=limit)
        ]
        releases = release_read_models(
            bundles,
            build_attempts,
            deployment_attempts,
            external_requests,
            limit=limit,
        )
        return StateSnapshotReadModel(
            contours=contour_state_read_models(contour_states, releases),
            releases=releases,
            build_attempts=build_attempts,
            deployment_attempts=deployment_attempts,
            jobs=[
                JobReadModel.model_validate(job)
                for job in list_jobs(connection, limit=limit)
            ],
            external_requests=external_requests,
        )


__all__ = [
    "bounded_limit",
    "contour_state_read_models",
    "external_request_read_models_from_state",
    "job_read_model_from_state",
    "job_read_models_from_state",
    "release_read_models",
    "release_read_models_from_state",
    "release_bundle_read_model_from_state",
    "release_reference_read_model",
    "release_sort_key",
    "state_snapshot_read_model",
    "utc_timestamp_age_seconds",
    "worker_health_read_model_from_state",
    "worker_health_status",
]
