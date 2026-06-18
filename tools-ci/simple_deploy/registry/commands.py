"""Write/use-case boundary поверх registry state.

Команды этого модуля выполняют небольшие атомарные с точки зрения приложения
изменения локального registry: двигают baseline контура и записывают attempts.
Они не читают release artifacts и не знают про CLI/HTTP. Если для команды нужен
backend commit из ``release_manifest.json``, его должен заранее извлечь
process/application слой и передать сюда готовым значением.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

from simple_deploy.registry import state


@dataclass(frozen=True)
class DeploymentMarkResult:
    """Результат registry-команды фиксации deploy state."""

    contour: str
    build_version: str
    backend_commit: str


@dataclass(frozen=True)
class BuildAttemptResult:
    """Результат registry-команды фиксации build attempt."""

    attempt_id: int
    build_version: str
    backend_commit: str
    frontend_commit: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class ReleaseBundleRecordResult:
    """Результат registry-команды записи успешного release bundle."""

    build_version: str
    backend_commit: str
    frontend_commit: str | None


def record_release_bundle(
    build_version: str,
    backend_commit: str,
    frontend_commit: str | None,
    artifacts: dict,
) -> ReleaseBundleRecordResult:
    """Записывает метаданные успешно собранного release bundle."""
    with closing(state.connect_state_db()) as connection:
        state.record_release(
            connection,
            build_version=build_version,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
            artifacts=artifacts,
        )
    return ReleaseBundleRecordResult(build_version, backend_commit, frontend_commit)


def start_build_attempt(
    build_version: str,
    backend_commit: str = "",
    frontend_commit: str = "",
) -> BuildAttemptResult:
    """Создает запись о начале build attempt."""
    with closing(state.connect_state_db()) as connection:
        attempt_id = state.record_build_attempt_started(
            connection,
            build_version=build_version,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
        )
    return BuildAttemptResult(
        attempt_id=attempt_id,
        build_version=build_version,
        backend_commit=backend_commit,
        frontend_commit=frontend_commit,
        status="started",
    )


def finish_build_attempt(
    attempt_id: int,
    status: str,
    build_version: str = "",
    backend_commit: str = "",
    frontend_commit: str = "",
    error: str = "",
) -> BuildAttemptResult:
    """Фиксирует терминальный статус build attempt."""
    status = state.validate_status(status, {"success", "failed"})
    with closing(state.connect_state_db()) as connection:
        state.record_build_attempt_finished(
            connection,
            attempt_id=attempt_id,
            status=status,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
            error=error,
        )
    return BuildAttemptResult(
        attempt_id=attempt_id,
        build_version=build_version,
        backend_commit=backend_commit,
        frontend_commit=frontend_commit,
        status=status,
        error=error,
    )


def set_contour_baseline(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Двигает baseline контура без записи deployment attempt."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(connection, contour, build_version, backend_commit)
    return DeploymentMarkResult(contour, build_version, backend_commit)


def record_deployment_applied(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Фиксирует успешное применение релиза и двигает baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(connection, contour, build_version, backend_commit)
        state.record_attempt(connection, contour, build_version, backend_commit, "success")
    return DeploymentMarkResult(contour, build_version, backend_commit)


def record_deployment_failed(
    contour: str,
    build_version: str,
    backend_commit: str,
    error_text: str,
) -> DeploymentMarkResult:
    """Фиксирует неуспешную deploy attempt без изменения baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.record_attempt(connection, contour, build_version, backend_commit, "failed", error_text)
    return DeploymentMarkResult(contour, build_version, backend_commit)


__all__ = [
    "BuildAttemptResult",
    "DeploymentMarkResult",
    "ReleaseBundleRecordResult",
    "finish_build_attempt",
    "record_deployment_applied",
    "record_deployment_failed",
    "record_release_bundle",
    "set_contour_baseline",
    "start_build_attempt",
]
