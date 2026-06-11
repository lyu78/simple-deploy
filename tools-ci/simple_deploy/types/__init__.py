"""Общие типы и ограниченные примитивы simple-deploy."""

from simple_deploy.types.artifact import (
    ARTIFACT_KINDS,
    ARTIFACT_SCOPES,
    ArtifactKind,
    ArtifactScope,
)
from simple_deploy.types.component import COMPONENT_IDS, ComponentId
from simple_deploy.types.contour import CONTOUR_CODES, ContourCode, OptionalContourCode
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
    DeploymentAttemptStatus,
    ExternalRequestStatus,
    JobStatus,
)
from simple_deploy.types.target import DEPLOYMENT_TARGET_ROLES, DeploymentTargetRole

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
    "ArtifactScope",
    "BuildVersionString",
    "BuildAttemptStatus",
    "CommitShaString",
    "ComponentId",
    "ContourCode",
    "DeploymentAttemptStatus",
    "DeploymentTargetRole",
    "ExternalRequestStatus",
    "JobStatus",
    "OptionalCommitShaString",
    "OptionalContourCode",
    "OptionalBuildVersionString",
    "ReleaseVersionString",
]
