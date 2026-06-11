"""Тесты constrained types для версий релиза."""

import sys
import unittest
from pathlib import Path

from pydantic import TypeAdapter, ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.types.artifact import ArtifactKind, ArtifactScope
from simple_deploy.types.component import ComponentId
from simple_deploy.types.contour import ContourCode, OptionalContourCode
from simple_deploy.types.release import BuildVersionString, OptionalBuildVersionString
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
from simple_deploy.types.status import (
    BuildAttemptStatus,
    DeploymentAttemptStatus,
    ExternalRequestStatus,
    JobStatus,
)
from simple_deploy.types.target import DeploymentTargetRole


class ReleaseTypeTests(unittest.TestCase):
    """Проверяет первый безопасный слой custom primitive типов."""

    def test_build_version_accepts_current_and_legacy_values(self):
        """BuildVersionString принимает текущий, старый и ручной baseline форматы."""
        adapter = TypeAdapter(BuildVersionString)

        self.assertEqual(adapter.validate_python("1.0.3.30052026_1437"), "1.0.3.30052026_1437")
        self.assertEqual(adapter.validate_python("1.2.3"), "1.2.3")
        self.assertEqual(adapter.validate_python("manual-baseline"), "manual-baseline")
        self.assertEqual(adapter.validate_python(" 1.2.3 "), "1.2.3")

    def test_build_version_rejects_empty_and_path_like_values(self):
        """BuildVersionString не принимает пустые и path-подобные значения."""
        adapter = TypeAdapter(BuildVersionString)

        for value in ("", "   ", "../release", "release/1.2.3", "release\\1.2.3"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_optional_build_version_allows_empty_job_marker(self):
        """OptionalBuildVersionString оставляет пустую строку для черновых job записей."""
        adapter = TypeAdapter(OptionalBuildVersionString)

        self.assertEqual(adapter.validate_python(""), "")
        self.assertEqual(adapter.validate_python("  "), "")
        self.assertEqual(adapter.validate_python("1.2.3"), "1.2.3")

    def test_contour_code_normalizes_known_contours(self):
        """ContourCode нормализует регистр и принимает только известные контуры."""
        adapter = TypeAdapter(ContourCode)

        self.assertEqual(adapter.validate_python("DEV"), "dev")
        self.assertEqual(adapter.validate_python(" test "), "test")
        self.assertEqual(adapter.validate_python("prod"), "prod")
        with self.assertRaises(ValidationError):
            adapter.validate_python("stage")

    def test_optional_contour_code_allows_empty_job_marker(self):
        """OptionalContourCode оставляет пустой contour для черновых job записей."""
        adapter = TypeAdapter(OptionalContourCode)

        self.assertEqual(adapter.validate_python(""), "")
        self.assertEqual(adapter.validate_python("  "), "")
        self.assertEqual(adapter.validate_python("TEST"), "test")
        with self.assertRaises(ValidationError):
            adapter.validate_python("stage")

    def test_status_types_accept_only_their_own_dictionaries(self):
        """Status types проверяют значения по своим жизненным циклам."""
        self.assertEqual(TypeAdapter(BuildAttemptStatus).validate_python("SUCCESS"), "success")
        self.assertEqual(TypeAdapter(DeploymentAttemptStatus).validate_python(" failed "), "failed")
        self.assertEqual(TypeAdapter(JobStatus).validate_python("queued"), "queued")
        self.assertEqual(TypeAdapter(ExternalRequestStatus).validate_python("approved"), "approved")

        with self.assertRaises(ValidationError):
            TypeAdapter(BuildAttemptStatus).validate_python("queued")
        with self.assertRaises(ValidationError):
            TypeAdapter(JobStatus).validate_python("submitted")
        with self.assertRaises(ValidationError):
            TypeAdapter(ExternalRequestStatus).validate_python("running")

    def test_commit_sha_accepts_short_and_full_hex_values(self):
        """CommitShaString принимает короткий и полный Git SHA."""
        adapter = TypeAdapter(CommitShaString)

        self.assertEqual(adapter.validate_python("ABC123"), "abc123")
        self.assertEqual(
            adapter.validate_python("0123456789abcdef0123456789abcdef01234567"),
            "0123456789abcdef0123456789abcdef01234567",
        )

    def test_commit_sha_rejects_empty_unknown_and_path_like_values(self):
        """CommitShaString отклоняет пустые и не похожие на SHA значения."""
        adapter = TypeAdapter(CommitShaString)

        for value in ("", "unknown", "abc12", "branch/main", "../abc123"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_optional_commit_sha_allows_empty_attempt_marker(self):
        """OptionalCommitShaString оставляет пустой commit для незавершенных attempts."""
        adapter = TypeAdapter(OptionalCommitShaString)

        self.assertEqual(adapter.validate_python(""), "")
        self.assertEqual(adapter.validate_python("  "), "")
        self.assertEqual(adapter.validate_python("DEF456"), "def456")

    def test_component_id_accepts_initial_domain_components(self):
        """ComponentId принимает начальный словарь DDD components."""
        adapter = TypeAdapter(ComponentId)

        self.assertEqual(adapter.validate_python("BACKEND"), "backend")
        self.assertEqual(adapter.validate_python(" frontend "), "frontend")
        self.assertEqual(adapter.validate_python("database"), "database")
        with self.assertRaises(ValidationError):
            adapter.validate_python("cache")

    def test_artifact_types_accept_kind_and_scope_dictionaries(self):
        """ArtifactKind и ArtifactScope проверяют DDD-справочники артефактов."""
        kind_adapter = TypeAdapter(ArtifactKind)
        scope_adapter = TypeAdapter(ArtifactScope)

        self.assertEqual(kind_adapter.validate_python("DB_SCHEMA"), "db_schema")
        self.assertEqual(kind_adapter.validate_python("manifest"), "manifest")
        self.assertEqual(scope_adapter.validate_python("CONTOUR_SPECIFIC"), "contour_specific")
        self.assertEqual(scope_adapter.validate_python("shared"), "shared")
        with self.assertRaises(ValidationError):
            kind_adapter.validate_python("db_insert")
        with self.assertRaises(ValidationError):
            scope_adapter.validate_python("global")

    def test_deployment_target_role_accepts_initial_role_dictionary(self):
        """DeploymentTargetRole принимает роли target-ов, а не components."""
        adapter = TypeAdapter(DeploymentTargetRole)

        self.assertEqual(adapter.validate_python("DATABASE"), "database")
        self.assertEqual(adapter.validate_python(" reporting "), "reporting")
        self.assertEqual(adapter.validate_python("s3"), "s3")
        with self.assertRaises(ValidationError):
            adapter.validate_python("worker")


if __name__ == "__main__":
    unittest.main()
