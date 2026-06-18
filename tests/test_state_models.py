"""Тесты read-моделей локального состояния релизов."""

import sys
import unittest
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
TEST_BUILD_VERSION = "1.2.4"
TEST_BACKEND_COMMIT = "abc123"
TEST_FRONTEND_COMMIT = "def456"
TEST_TIMESTAMP = "2026-06-11T10:00:00Z"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.dto.state import StateSnapshotDto, dto_dump
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
    ReleaseBundleReadModel,
    ReleaseModel,
    ReleaseReadModel,
    ReleaseReferenceModel,
    ReleaseReferenceReadModel,
    ReleaseRecordModel,
    ReleaseRecordReadModel,
    StateSnapshotModel,
    StateSnapshotReadModel,
)
from simple_deploy.release.state import ContourState


class StateModelTests(unittest.TestCase):
    """Проверяет внутренние модели чтения над текущими строками состояния."""

    def test_read_model_aliases_keep_old_import_names(self):
        """Старые имена Model остаются совместимыми псевдонимами моделей чтения."""
        self.assertIs(BuildAttemptModel, BuildAttemptReadModel)
        self.assertIs(ContourStateModel, ContourStateReadModel)
        self.assertIs(DeploymentAttemptModel, DeploymentAttemptReadModel)
        self.assertIs(ExternalRequestModel, ExternalRequestReadModel)
        self.assertIs(JobModel, JobReadModel)
        self.assertIs(ReleaseModel, ReleaseReadModel)
        self.assertIs(ReleaseReferenceModel, ReleaseReferenceReadModel)
        self.assertIs(ReleaseRecordModel, ReleaseBundleReadModel)
        self.assertIs(ReleaseRecordReadModel, ReleaseBundleReadModel)
        self.assertIs(StateSnapshotModel, StateSnapshotReadModel)

    def test_contour_state_read_model_accepts_state_dataclass(self):
        """Модель состояния контура строится из объекта SQLite-слоя."""
        state = ContourState(
            contour="dev",
            last_success_release=TEST_BUILD_VERSION,
            last_success_backend_commit=TEST_BACKEND_COMMIT,
            updated_at=TEST_TIMESTAMP,
        )

        model = ContourStateReadModel.model_validate(state)

        self.assertEqual(model.contour, "dev")
        self.assertEqual(model.last_success_release, TEST_BUILD_VERSION)
        self.assertIsNone(model.last_success_release_ref)

    def test_state_models_accept_sqlite_row_dicts_and_are_frozen(self):
        """Модели чтения принимают словари строк SQLite и не меняются после создания."""
        release = ReleaseBundleReadModel.model_validate(
            {
                "build_version": TEST_BUILD_VERSION,
                "backend_commit": TEST_BACKEND_COMMIT,
                "frontend_commit": TEST_FRONTEND_COMMIT,
                "artifacts_json": "{}",
                "created_at": TEST_TIMESTAMP,
            }
        )

        self.assertEqual(release.backend_commit, TEST_BACKEND_COMMIT)
        with self.assertRaises(ValidationError):
            release.backend_commit = "654321"

    def test_state_read_model_schema_contains_field_descriptions(self):
        """Read-модели отдают описания смысловых строковых полей."""
        release_schema = ReleaseBundleReadModel.model_json_schema()
        job_schema = JobReadModel.model_json_schema()
        request_schema = ExternalRequestReadModel.model_json_schema()

        self.assertIn(
            "UTC timestamp",
            release_schema["properties"]["created_at"]["description"],
        )
        self.assertIn(
            "log-файлу",
            job_schema["properties"]["log_path"]["description"],
        )
        self.assertIn(
            "Строковый идентификатор",
            request_schema["properties"]["external_id"]["description"],
        )

    def test_state_snapshot_read_model_converts_to_api_dto(self):
        """Снимок состояния конвертируется во внешний DTO без смены формы JSON."""
        snapshot = StateSnapshotReadModel(
            contours={
                "dev": ContourStateReadModel(
                    contour="dev",
                    last_success_release=TEST_BUILD_VERSION,
                    last_success_backend_commit=TEST_BACKEND_COMMIT,
                    last_success_release_ref=ReleaseReferenceReadModel(
                        build_version=TEST_BUILD_VERSION,
                        build_status="success",
                        backend_commit=TEST_BACKEND_COMMIT,
                        frontend_commit=TEST_FRONTEND_COMMIT,
                    ),
                    updated_at=TEST_TIMESTAMP,
                ),
                "test": None,
                "prod": None,
            },
            releases=[
                ReleaseReadModel(
                    build_version=TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    build_status="success",
                    bundle=ReleaseBundleReadModel(
                        build_version=TEST_BUILD_VERSION,
                        backend_commit=TEST_BACKEND_COMMIT,
                        frontend_commit=TEST_FRONTEND_COMMIT,
                        artifacts_json="{}",
                        created_at=TEST_TIMESTAMP,
                    ),
                    build_attempts=[
                        BuildAttemptReadModel(
                            id=1,
                            build_version=TEST_BUILD_VERSION,
                            status="success",
                            backend_commit=TEST_BACKEND_COMMIT,
                            frontend_commit=TEST_FRONTEND_COMMIT,
                            error="",
                            started_at=TEST_TIMESTAMP,
                            finished_at=TEST_TIMESTAMP,
                        )
                    ],
                    deployment_attempts=[],
                    external_requests=[],
                )
            ],
            build_attempts=[
                BuildAttemptReadModel(
                    id=1,
                    build_version=TEST_BUILD_VERSION,
                    status="success",
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    error="",
                    started_at=TEST_TIMESTAMP,
                    finished_at=TEST_TIMESTAMP,
                )
            ],
            deployment_attempts=[],
            jobs=[
                JobReadModel(
                    id=1,
                    kind="build",
                    contour="",
                    build_version="",
                    status="queued",
                    payload_json="{}",
                    log_path="",
                    error="",
                    created_at=TEST_TIMESTAMP,
                    started_at="",
                    finished_at="",
                )
            ],
            external_requests=[],
        )

        dto = StateSnapshotDto.model_validate(snapshot)
        payload = dto_dump(dto)

        self.assertEqual(payload["contours"]["dev"]["last_success_release"], TEST_BUILD_VERSION)
        self.assertEqual(
            payload["contours"]["dev"]["last_success_release_ref"]["build_version"],
            TEST_BUILD_VERSION,
        )
        self.assertEqual(
            payload["contours"]["dev"]["last_success_release_ref"]["backend_commit"],
            TEST_BACKEND_COMMIT,
        )
        self.assertEqual(payload["releases"][0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(payload["jobs"][0]["contour"], "")

    def test_state_models_validate_job_and_request_dictionaries(self):
        """Модели чтения проверяют справочники заданий и внешних заявок."""
        job = JobReadModel(
            id=1,
            kind="deploy",
            contour="dev",
            build_version=TEST_BUILD_VERSION,
            status="queued",
            payload_json="{}",
            log_path="",
            error="",
            created_at=TEST_TIMESTAMP,
            started_at="",
            finished_at="",
        )
        request = ExternalRequestReadModel(
            id=1,
            contour="test",
            build_version=TEST_BUILD_VERSION,
            request_type="deploy",
            status="draft",
            external_id="",
            payload_json="{}",
            error="",
            created_at=TEST_TIMESTAMP,
            updated_at=TEST_TIMESTAMP,
        )

        self.assertEqual(job.kind, "deploy")
        self.assertEqual(request.request_type, "deploy")
        with self.assertRaises(ValidationError):
            JobReadModel(
                id=1,
                kind="DEPLOY",
                contour="dev",
                build_version=TEST_BUILD_VERSION,
                status="queued",
                payload_json="{}",
                log_path="",
                error="",
                created_at=TEST_TIMESTAMP,
                started_at="",
                finished_at="",
            )
        with self.assertRaises(ValidationError):
            ExternalRequestReadModel(
                id=1,
                contour="test",
                build_version=TEST_BUILD_VERSION,
                request_type="DEPLOY",
                status="draft",
                external_id="",
                payload_json="{}",
                error="",
                created_at=TEST_TIMESTAMP,
                updated_at=TEST_TIMESTAMP,
            )
        with self.assertRaises(ValidationError):
            JobReadModel(
                id=1,
                kind="rollback",
                contour="dev",
                build_version=TEST_BUILD_VERSION,
                status="queued",
                payload_json="{}",
                log_path="",
                error="",
                created_at=TEST_TIMESTAMP,
                started_at="",
                finished_at="",
            )
        with self.assertRaises(ValidationError):
            ExternalRequestReadModel(
                id=1,
                contour="test",
                build_version=TEST_BUILD_VERSION,
                request_type="rollback",
                status="draft",
                external_id="",
                payload_json="{}",
                error="",
                created_at=TEST_TIMESTAMP,
                updated_at=TEST_TIMESTAMP,
            )


if __name__ == "__main__":
    unittest.main()
