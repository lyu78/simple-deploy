"""Общие типы и ограниченные примитивы simple-deploy."""

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
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
    ReleaseVersionString,
)
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
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

__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_SCOPES",
    "BUILD_ATTEMPT_STATUSES",
    "COMPONENT_IDS",
    "CONTOUR_CODES",
    "DEPLOYMENT_ATTEMPT_STATUSES",
    "DEPLOYMENT_TARGET_ROLES",
    "EXTERNAL_REQUEST_STATUSES",
    "JOB_STATUSES",
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
    "OptionalCommitShaString",
    "OptionalContourCode",
    "OptionalBuildVersionString",
    "ReleaseVersionString",
]
