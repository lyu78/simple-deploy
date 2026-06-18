"""Внутренние read/application модели simple-deploy.

Models - это промежуточная форма данных между registry/query слоями и внешними
DTO. Они удобны для сборки dashboard/API проекций: release с attempts,
contour baseline со ссылкой на release, jobs и external requests.

В отличие от ``entities``, эти модели не задают доменные инварианты. В отличие
от ``dto``, они не являются публичным JSON-контрактом и могут меняться вместе с
внутренней структурой read/query слоя.
"""

from simple_deploy.models.state import (
    BuildAttemptModel,
    BuildAttemptReadModel,
    ContourStateModel,
    ContourStateReadModel,
    DeploymentAttemptModel,
    DeploymentAttemptReadModel,
    ExternalRequestModel,
    ExternalRequestReadModel,
    JobModel,
    JobReadModel,
    ReleaseBundleModel,
    ReleaseBundleReadModel,
    ReleaseModel,
    ReleaseReadModel,
    ReleaseRecordModel,
    ReleaseRecordReadModel,
    ReleaseReferenceModel,
    ReleaseReferenceReadModel,
    StateSnapshotModel,
    StateSnapshotReadModel,
)

__all__ = [
    "BuildAttemptReadModel",
    "BuildAttemptModel",
    "ContourStateReadModel",
    "ContourStateModel",
    "DeploymentAttemptReadModel",
    "DeploymentAttemptModel",
    "ExternalRequestReadModel",
    "ExternalRequestModel",
    "JobReadModel",
    "JobModel",
    "ReleaseBundleReadModel",
    "ReleaseBundleModel",
    "ReleaseReadModel",
    "ReleaseModel",
    "ReleaseReferenceReadModel",
    "ReleaseReferenceModel",
    "ReleaseRecordReadModel",
    "ReleaseRecordModel",
    "StateSnapshotReadModel",
    "StateSnapshotModel",
]
