"""Pydantic-модели целевой runtime topology конфигурации.

Runtime topology - это карта системы, а не набор флагов запуска runner-а. Она
описывает, откуда берутся исходники, какие логические компоненты есть в
продукте, какие VM доступны, какие deployment targets находятся в каждом
контуре и какие execution environments можно использовать для deploy или
validation pipeline.

Упрощенный пример DEV topology::

    {
        "source_origins": [
            {
                "origin_id": "backend-primary",
                "kind": "primary_remote",
                "remote_url": "git@example.local/backend.git"
            }
        ],
        "source_repositories": [
            {
                "repo_id": "backend",
                "role": "backend",
                "default_origin_id": "backend-primary",
                "default_branch": "dev"
            }
        ],
        "components": [
            {
                "component_id": "backend",
                "source_repository_ids": ["backend"],
                "target_roles": ["backend"]
            }
        ],
        "machines": [
            {
                "machine_id": "dev-app-01",
                "role": "app",
                "hostname": "dev-app.example.local",
                "ssh_user": "deploy"
            }
        ],
        "landscapes": [
            {
                "contour": "dev",
                "targets": [
                    {
                        "target_id": "dev-backend",
                        "role": "backend",
                        "machine_id": "dev-app-01",
                        "remote_path": "/opt/app/backend"
                    }
                ]
            }
        ]
    }

На текущем этапе эти модели фиксируют typed target form для следующих срезов.
Они не являются loader-ом текущего ``windows_pipeline.local.json`` и не содержат
process-policy вроде порядка остановки сервисов или выбора SQL artifacts.
"""

from __future__ import annotations

from typing import Annotated, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictStr, StringConstraints

from simple_deploy.types.component import ComponentId
from simple_deploy.types.contour import ContourCode
from simple_deploy.types.machine import MachineId
from simple_deploy.types.source import RepoId, SourceOriginKind
from simple_deploy.types.target import DeploymentTargetRole


NonEmptyString = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


class _TopologyConfigModel(BaseModel):
    """Базовая immutable-модель topology config без process-логики."""

    model_config = ConfigDict(extra="allow", frozen=True)


class SourceOriginConfigModel(_TopologyConfigModel):
    """Конкретный источник Git-данных: primary remote, mirror или local clone."""

    origin_id: NonEmptyString
    kind: SourceOriginKind
    remote_url: NonEmptyString
    auth_profile: StrictStr = ""


class SourceRepositoryConfigModel(_TopologyConfigModel):
    """Логический исходный репозиторий продукта.

    Source repository не равен VM, deployment target или компоненту. Один repo
    может давать несколько компонентов, а один компонент может со временем
    собираться из нескольких repo.
    """

    repo_id: RepoId
    role: NonEmptyString
    default_origin_id: NonEmptyString
    fallback_origin_ids: list[NonEmptyString] = Field(default_factory=list)
    default_branch: NonEmptyString = "dev"


class ComponentConfigModel(_TopologyConfigModel):
    """Логическая часть продукта и ее связи с source repo и target roles."""

    component_id: ComponentId
    source_repository_ids: list[RepoId] = Field(default_factory=list)
    target_roles: list[DeploymentTargetRole] = Field(default_factory=list)


class VirtualMachineConfigModel(_TopologyConfigModel):
    """Инфраструктурная машина для deploy, диагностики или validation flow.

    VM не равна контуру: одна машина может быть частью landscape, execution
    environment или временной диагностической площадки.
    """

    machine_id: MachineId
    role: NonEmptyString
    hostname: NonEmptyString
    ssh_user: NonEmptyString
    workdir: StrictStr = ""
    auth_profile: StrictStr = ""


class DeploymentTargetConfigModel(_TopologyConfigModel):
    """Техническая точка размещения внутри deployment landscape.

    Target связывает роль размещения, машину и удаленный путь. Например,
    ``dev-backend`` может указывать на backend slot на ``dev-app-01``.
    """

    target_id: NonEmptyString
    role: DeploymentTargetRole
    machine_id: MachineId
    remote_path: StrictStr = ""


class DeploymentLandscapeConfigModel(_TopologyConfigModel):
    """Фактическая форма размещения одного deploy-контура.

    Landscape отвечает за "куда раскладывать release на dev/test/prod", но не
    хранит историю успешных применений. История и baseline живут в registry.
    """

    contour: ContourCode
    targets: list[DeploymentTargetConfigModel] = Field(default_factory=list)


class ExecutionEnvironmentConfigModel(_TopologyConfigModel):
    """Окружение выполнения pipeline-операций над bundle-ом.

    Execution environment может совпадать с contour landscape или быть отдельной
    sandbox/validation площадкой, которая не двигает baseline контура.
    """

    environment_id: NonEmptyString
    kind: NonEmptyString
    machine_ids: list[MachineId] = Field(default_factory=list)
    contour: ContourCode | None = None
    target_ids: list[NonEmptyString] = Field(default_factory=list)


class RuntimeTopologyConfigModel(_TopologyConfigModel):
    """Агрегированная read/config модель source и deployment topology."""

    source_origins: list[SourceOriginConfigModel] = Field(default_factory=list)
    source_repositories: list[SourceRepositoryConfigModel] = Field(default_factory=list)
    components: list[ComponentConfigModel] = Field(default_factory=list)
    machines: list[VirtualMachineConfigModel] = Field(default_factory=list)
    landscapes: list[DeploymentLandscapeConfigModel] = Field(default_factory=list)
    execution_environments: list[ExecutionEnvironmentConfigModel] = Field(default_factory=list)


def runtime_topology_config_model(config: dict) -> RuntimeTopologyConfigModel:
    """Преобразует mapping topology config в структурную Pydantic-модель."""

    return RuntimeTopologyConfigModel.model_validate(config)


def _env_value(env: Mapping[str, object], key: str) -> str:
    """Возвращает trimmed string value из legacy env mapping."""
    return str(env.get(key, "") or "").strip()


def _source_origin_config(repo_id: str, local_path: str) -> dict:
    """Строит source origin для legacy local source repo path."""
    return {
        "origin_id": f"{repo_id}-local",
        "kind": "emergency_clone",
        "remote_url": local_path,
    }


def runtime_topology_from_legacy_env(env: Mapping[str, object]) -> RuntimeTopologyConfigModel:
    """Строит read-only DEV topology из текущего env-контракта runner-а.

    Adapter не меняет формат ``.env``/``local.secrets.env`` и не используется
    deploy-процессом для принятия решений. Он дает typed view уже известных
    значений: source repo paths, app/db VM, backend/frontend/database targets и
    contour-bound execution environment для ``dev``.
    """
    backend_source = _env_value(env, "BACKEND_SOURCE_REPO_PATH")
    frontend_source = _env_value(env, "FRONTEND_SOURCE_REPO_PATH")
    app_host = _env_value(env, "APP_VM_HOST")
    app_user = _env_value(env, "APP_VM_USER")
    db_host = _env_value(env, "DB_VM_HOST")
    db_user = _env_value(env, "DB_VM_USER")
    app_auth = _env_value(env, "APP_SSH_KEY_PATH") or _env_value(env, "SSH_KEY_PATH")
    db_auth = _env_value(env, "DB_SSH_KEY_PATH") or _env_value(env, "SSH_KEY_PATH")

    source_origins = []
    source_repositories = []
    if backend_source:
        source_origins.append(_source_origin_config("backend", backend_source))
        source_repositories.append(
            {
                "repo_id": "backend",
                "role": "backend",
                "default_origin_id": "backend-local",
                "default_branch": "dev",
            }
        )
    if frontend_source:
        source_origins.append(_source_origin_config("frontend", frontend_source))
        source_repositories.append(
            {
                "repo_id": "frontend",
                "role": "frontend",
                "default_origin_id": "frontend-local",
                "default_branch": "dev",
            }
        )

    machines = []
    if app_host and app_user:
        machines.append(
            {
                "machine_id": "dev-app",
                "role": "app",
                "hostname": app_host,
                "ssh_user": app_user,
                "workdir": _env_value(env, "APP_WORKDIR"),
                "auth_profile": app_auth,
            }
        )
    if db_host and db_user:
        machines.append(
            {
                "machine_id": "dev-db",
                "role": "database",
                "hostname": db_host,
                "ssh_user": db_user,
                "auth_profile": db_auth,
            }
        )

    targets = []
    if app_host and app_user:
        targets.extend(
            [
                {
                    "target_id": "dev-backend",
                    "role": "backend",
                    "machine_id": "dev-app",
                    "remote_path": _env_value(env, "BACKEND_RELEASE_PATH"),
                },
                {
                    "target_id": "dev-frontend",
                    "role": "frontend",
                    "machine_id": "dev-app",
                    "remote_path": _env_value(env, "FRONTEND_RELEASE_PATH"),
                },
            ]
        )
    if db_host and db_user:
        targets.append(
            {
                "target_id": "dev-database",
                "role": "database",
                "machine_id": "dev-db",
                "remote_path": _env_value(env, "REMOTE_TMP_ROOT"),
            }
        )

    topology = {
        "source_origins": source_origins,
        "source_repositories": source_repositories,
        "components": [
            {
                "component_id": "backend",
                "source_repository_ids": ["backend"] if backend_source else [],
                "target_roles": ["backend"],
            },
            {
                "component_id": "frontend",
                "source_repository_ids": ["frontend"] if frontend_source else [],
                "target_roles": ["frontend"],
            },
            {
                "component_id": "database",
                "source_repository_ids": [],
                "target_roles": ["database"],
            },
        ],
        "machines": machines,
        "landscapes": [{"contour": "dev", "targets": targets}] if targets else [],
        "execution_environments": [
            {
                "environment_id": "dev-contour",
                "kind": "contour_bound",
                "machine_ids": [machine["machine_id"] for machine in machines],
                "contour": "dev",
                "target_ids": [target["target_id"] for target in targets],
            }
        ]
        if machines or targets
        else [],
    }
    return runtime_topology_config_model(topology)


__all__ = [
    "ComponentConfigModel",
    "DeploymentLandscapeConfigModel",
    "DeploymentTargetConfigModel",
    "ExecutionEnvironmentConfigModel",
    "RuntimeTopologyConfigModel",
    "SourceOriginConfigModel",
    "SourceRepositoryConfigModel",
    "VirtualMachineConfigModel",
    "runtime_topology_config_model",
    "runtime_topology_from_legacy_env",
]
