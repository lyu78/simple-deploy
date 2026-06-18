"""Общие типы и ограниченные примитивы simple-deploy.

Types содержат небольшие shared vocabulary элементы: contour codes, release
version strings, commit SHA strings, artifact kinds/scopes, job kinds/statuses,
deploy entrypoint roles и runtime service phases.

Этот пакет не должен знать про SQLite, CLI, FastAPI или SSH. Его задача -
нормализовать и ограничить базовые значения, чтобы ``config``, ``models``,
``dto`` и ``entities`` использовали один словарь вместо произвольных строк.
"""

from simple_deploy.types.artifact import (
    ARTIFACT_KINDS,
    ARTIFACT_SCOPES,
    ArtifactKindEnum,
    ArtifactScopeEnum,
)
from simple_deploy.types.component import (
    COMPONENT_IDS,
    ComponentIdEnum,
)
from simple_deploy.types.contour import (
    CONTOUR_CODES,
    ContourCodeEnum,
    JOB_CONTOUR_SCOPE_CODES,
    JobContourScope,
)
from simple_deploy.types.job import JOB_KINDS, JobKindEnum
from simple_deploy.types.machine import MachineId
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
    ReleaseVersionString,
)
from simple_deploy.types.request import (
    EXTERNAL_REQUEST_TYPES,
    ExternalRequestTypeEnum,
)
from simple_deploy.types.runtime import (
    MAINTENANCE_SQL_PHASES,
    MaintenanceSqlPhaseEnum,
    NGINX_STOP_START_ACTIONS,
    NGINX_UNSUPPORTED_ACTIONS,
    SERVICE_STEP_PHASES,
    ServiceStepPhaseEnum,
    SYSTEMCTL_ACTIONS,
    SystemctlActionEnum,
)
from simple_deploy.types.source import (
    CommitShaString,
    OptionalCommitShaString,
    RepoId,
    SOURCE_ORIGIN_KINDS,
    SourceOriginKindEnum,
)
from simple_deploy.types.status import (
    BUILD_ATTEMPT_STATUSES,
    BuildAttemptStatusEnum,
    DEPLOYMENT_ATTEMPT_STATUSES,
    DeploymentAttemptStatusEnum,
    EXTERNAL_REQUEST_STATUSES,
    ExternalRequestStatusEnum,
    JOB_STATUSES,
    JobStatusEnum,
)
from simple_deploy.types.target import (
    DEPLOYMENT_TARGET_ROLES,
    DeploymentTargetRoleEnum,
)
from simple_deploy.types.trigger import (
    RELEASE_TRIGGER_TYPES,
    ReleaseTriggerTypeEnum,
)

__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_SCOPES",
    "BUILD_ATTEMPT_STATUSES",
    "COMPONENT_IDS",
    "CONTOUR_CODES",
    "DEPLOYMENT_ATTEMPT_STATUSES",
    "DEPLOYMENT_TARGET_ROLES",
    "EXTERNAL_REQUEST_STATUSES",
    "EXTERNAL_REQUEST_TYPES",
    "JOB_KINDS",
    "JOB_STATUSES",
    "MAINTENANCE_SQL_PHASES",
    "NGINX_STOP_START_ACTIONS",
    "NGINX_UNSUPPORTED_ACTIONS",
    "JOB_CONTOUR_SCOPE_CODES",
    "RELEASE_TRIGGER_TYPES",
    "SERVICE_STEP_PHASES",
    "SOURCE_ORIGIN_KINDS",
    "SYSTEMCTL_ACTIONS",
    "ArtifactKindEnum",
    "ArtifactScopeEnum",
    "BuildVersionString",
    "BuildAttemptStatusEnum",
    "CommitShaString",
    "ComponentIdEnum",
    "ContourCodeEnum",
    "DeploymentAttemptStatusEnum",
    "DeploymentTargetRoleEnum",
    "ExternalRequestStatusEnum",
    "JobStatusEnum",
    "JobContourScope",
    "JobKindEnum",
    "MachineId",
    "ExternalRequestTypeEnum",
    "MaintenanceSqlPhaseEnum",
    "OptionalCommitShaString",
    "OptionalBuildVersionString",
    "RepoId",
    "ReleaseVersionString",
    "ReleaseTriggerTypeEnum",
    "ServiceStepPhaseEnum",
    "SourceOriginKindEnum",
    "SystemctlActionEnum",
]
