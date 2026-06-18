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
    "DeploymentMarkResult",
    "record_deployment_applied",
    "record_deployment_failed",
    "set_contour_baseline",
]
