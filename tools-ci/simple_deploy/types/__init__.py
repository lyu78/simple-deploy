"""Общие типы и ограниченные примитивы simple-deploy.

Types содержат небольшие shared vocabulary элементы: contour codes, release
version strings, commit SHA strings, artifact kinds/scopes, job kinds/statuses,
deployment target roles и runtime service phases.

Этот пакет не должен знать про SQLite, CLI, FastAPI или SSH. Его задача -
нормализовать и ограничить базовые значения, чтобы ``config``, ``models``,
``dto`` и ``entities`` использовали один словарь вместо произвольных строк.
"""

from simple_deploy.types.artifact import (
    ARTIFACT_KINDS,
    ARTIFACT_SCOPES,
    ArtifactKind,
    ArtifactKindEnum,
    ArtifactScope,
    ArtifactScopeEnum,
)
from simple_deploy.types.component import COMPONENT_IDS, ComponentId, ComponentIdEnum
from simple_deploy.types.contour import (
    CONTOUR_CODES,
    ContourCode,
    ContourCodeEnum,
    OptionalContourCode,
)
from simple_deploy.types.job import JOB_KINDS, JobKind, JobKindEnum
from simple_deploy.types.machine import MachineId
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
    ReleaseVersionString,
)
from simple_deploy.types.request import (
    EXTERNAL_REQUEST_TYPES,
    ExternalRequestType,
    ExternalRequestTypeEnum,
)
from simple_deploy.types.runtime import (
    MAINTENANCE_SQL_PHASES,
    NGINX_STOP_START_ACTIONS,
    NGINX_UNSUPPORTED_ACTIONS,
    SERVICE_STEP_PHASES,
    SYSTEMCTL_ACTIONS,
    MaintenanceSqlPhase,
    MaintenanceSqlPhaseEnum,
    ServiceStepPhase,
    ServiceStepPhaseEnum,
    SystemctlAction,
    SystemctlActionEnum,
)
from simple_deploy.types.source import (
    SOURCE_ORIGIN_KINDS,
    CommitShaString,
    OptionalCommitShaString,
    RepoId,
    SourceOriginKind,
    SourceOriginKindEnum,
)
from simple_deploy.types.status import (
    BUILD_ATTEMPT_STATUSES,
    DEPLOYMENT_ATTEMPT_STATUSES,
    EXTERNAL_REQUEST_STATUSES,
    JOB_STATUSES,
    BuildAttemptStatus,
    BuildAttemptStatusEnum,
    DeploymentAttemptStatus,
    DeploymentAttemptStatusEnum,
    ExternalRequestStatus,
    ExternalRequestStatusEnum,
    JobStatus,
    JobStatusEnum,
)
from simple_deploy.types.target import (
    DEPLOYMENT_TARGET_ROLES,
    DeploymentTargetRole,
    DeploymentTargetRoleEnum,
)
from simple_deploy.types.trigger import (
    RELEASE_TRIGGER_TYPES,
    ReleaseTriggerType,
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
    "RELEASE_TRIGGER_TYPES",
    "SERVICE_STEP_PHASES",
    "SOURCE_ORIGIN_KINDS",
    "SYSTEMCTL_ACTIONS",
    "ArtifactKind",
    "ArtifactKindEnum",
    "ArtifactScope",
    "ArtifactScopeEnum",
    "BuildVersionString",
    "BuildAttemptStatus",
    "BuildAttemptStatusEnum",
    "CommitShaString",
    "ComponentId",
    "ComponentIdEnum",
    "ContourCode",
    "ContourCodeEnum",
    "DeploymentAttemptStatus",
    "DeploymentAttemptStatusEnum",
    "DeploymentTargetRole",
    "DeploymentTargetRoleEnum",
    "ExternalRequestStatus",
    "ExternalRequestStatusEnum",
    "JobStatus",
    "JobStatusEnum",
    "JobKind",
    "JobKindEnum",
    "MachineId",
    "ExternalRequestType",
    "ExternalRequestTypeEnum",
    "MaintenanceSqlPhase",
    "MaintenanceSqlPhaseEnum",
    "OptionalCommitShaString",
    "OptionalContourCode",
    "OptionalBuildVersionString",
    "RepoId",
    "ReleaseVersionString",
    "ReleaseTriggerType",
    "ReleaseTriggerTypeEnum",
    "ServiceStepPhase",
    "ServiceStepPhaseEnum",
    "SourceOriginKind",
    "SourceOriginKindEnum",
    "SystemctlAction",
    "SystemctlActionEnum",
]
