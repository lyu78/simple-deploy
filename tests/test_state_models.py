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
    ContourStateModel,
    JobModel,
    ReleaseRecordModel,
    StateSnapshotModel,
)
from simple_deploy.release.state import ContourState


class StateModelTests(unittest.TestCase):
    """Проверяет внутренние модели чтения над текущими state rows."""

    def test_contour_state_model_accepts_state_dataclass(self):
        """ContourStateModel строится из dataclass слоя SQLite state."""
        state = ContourState(
            contour="dev",
            last_success_release=TEST_BUILD_VERSION,
            last_success_backend_commit=TEST_BACKEND_COMMIT,
            updated_at=TEST_TIMESTAMP,
        )

        model = ContourStateModel.model_validate(state)

        self.assertEqual(model.contour, "dev")
        self.assertEqual(model.last_success_release, TEST_BUILD_VERSION)

    def test_state_models_accept_sqlite_row_dicts_and_are_frozen(self):
        """Read-модели принимают dict rows и не меняются после создания."""
        release = ReleaseRecordModel.model_validate(
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

    def test_state_snapshot_model_converts_to_api_dto(self):
        """StateSnapshotModel конвертируется во внешний DTO без смены формы JSON."""
        snapshot = StateSnapshotModel(
            contours={
                "dev": ContourStateModel(
                    contour="dev",
                    last_success_release=TEST_BUILD_VERSION,
                    last_success_backend_commit=TEST_BACKEND_COMMIT,
                    updated_at=TEST_TIMESTAMP,
                ),
                "test": None,
                "prod": None,
            },
            releases=[
                ReleaseRecordModel(
                    build_version=TEST_BUILD_VERSION,
                    backend_commit=TEST_BACKEND_COMMIT,
                    frontend_commit=TEST_FRONTEND_COMMIT,
                    artifacts_json="{}",
                    created_at=TEST_TIMESTAMP,
                )
            ],
            build_attempts=[
                BuildAttemptModel(
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
                JobModel(
                    id=1,
                    kind="deploy",
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
        self.assertEqual(payload["releases"][0]["build_version"], TEST_BUILD_VERSION)
        self.assertEqual(payload["jobs"][0]["contour"], "")


if __name__ == "__main__":
    unittest.main()
