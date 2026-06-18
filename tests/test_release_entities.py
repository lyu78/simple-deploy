"""Тесты чистых DDD entities релиза."""

import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
TEST_BUILD_VERSION = "1.2.4"
TEST_TIMESTAMP = "2026-06-11T10:00:00Z"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.entities.release import (
    Release,
    ReleaseArtifactRef,
    ReleaseBundle,
    ReleasePlacement,
    SourceRepositoryRevision,
    SourceSnapshot,
)


class ReleaseEntityTests(unittest.TestCase):
    """Проверяет доменные инварианты release entities без storage/runtime."""

    def _snapshot(self) -> SourceSnapshot:
        return SourceSnapshot(
            revisions=(
                SourceRepositoryRevision(
                    repo_id="backend",
                    ref="dev",
                    commit_sha="abc123",
                    origin_id="backend-primary",
                ),
            ),
            resolved_at=TEST_TIMESTAMP,
            trigger_type="manual",
        )

    def _bundle(self, build_version: str = TEST_BUILD_VERSION) -> ReleaseBundle:
        return ReleaseBundle(
            build_version=build_version,
            source_snapshot=self._snapshot(),
            artifacts=(
                ReleaseArtifactRef(
                    artifact_id="backend.tar.gz",
                    kind="backend",
                    scope="shared",
                ),
            ),
            created_at=TEST_TIMESTAMP,
            build_attempt_id=1,
        )

    def test_release_accepts_single_successful_bundle(self):
        """Release получает ровно один successful bundle и остается immutable."""
        release = Release(build_version=TEST_BUILD_VERSION)

        updated = release.with_successful_bundle(self._bundle())

        self.assertIsNone(release.successful_bundle)
        self.assertEqual(updated.successful_bundle.build_version, TEST_BUILD_VERSION)
        self.assertEqual(updated.source_snapshot.revisions[0].repo_id, "backend")
        with self.assertRaises(FrozenInstanceError):
            updated.build_version = "1.2.5"

    def test_release_rejects_second_different_successful_bundle(self):
        """Release не принимает второй successful bundle с другим содержимым."""
        first_bundle = self._bundle()
        release = Release(build_version=TEST_BUILD_VERSION).with_successful_bundle(first_bundle)
        second_snapshot = SourceSnapshot(
            revisions=(
                SourceRepositoryRevision(
                    repo_id="backend",
                    ref="dev",
                    commit_sha="def456",
                    origin_id="backend-primary",
                ),
            ),
            resolved_at=TEST_TIMESTAMP,
        )
        second_bundle = ReleaseBundle(
            build_version=TEST_BUILD_VERSION,
            source_snapshot=second_snapshot,
            artifacts=first_bundle.artifacts,
            created_at=TEST_TIMESTAMP,
            build_attempt_id=2,
        )

        with self.assertRaisesRegex(ValueError, "source_snapshot"):
            release.with_successful_bundle(second_bundle)

    def test_release_rejects_bundle_and_placement_for_another_release(self):
        """Bundle и placement обязаны ссылаться на тот же release version."""
        release = Release(build_version=TEST_BUILD_VERSION)

        with self.assertRaisesRegex(ValueError, "build_version"):
            release.with_successful_bundle(self._bundle("1.2.5"))
        with self.assertRaisesRegex(ValueError, "build_version"):
            release.with_placement(
                ReleasePlacement(
                    build_version="1.2.5",
                    contour="dev",
                    status="success",
                    updated_at=TEST_TIMESTAMP,
                )
            )

    def test_release_placement_is_separate_from_successful_bundle(self):
        """Placement обновляется отдельно и не меняет successful bundle."""
        bundle = self._bundle()
        release = Release(build_version=TEST_BUILD_VERSION).with_successful_bundle(bundle)

        placed = release.with_placement(
            ReleasePlacement(
                build_version=TEST_BUILD_VERSION,
                contour="dev",
                status="success",
                updated_at=TEST_TIMESTAMP,
                deployment_attempt_id=1,
            )
        )

        self.assertEqual(placed.successful_bundle, bundle)
        self.assertEqual(placed.placements[0].contour, "dev")
        self.assertEqual(release.placements, ())

    def test_source_snapshot_requires_non_empty_unique_revisions(self):
        """SourceSnapshot требует непустой набор уникальных repo revisions."""
        with self.assertRaisesRegex(ValueError, "at least one"):
            SourceSnapshot(revisions=(), resolved_at=TEST_TIMESTAMP)
        with self.assertRaisesRegex(ValueError, "unique repo_id"):
            SourceSnapshot(
                revisions=(
                    SourceRepositoryRevision("backend", "dev", "abc123", "origin"),
                    SourceRepositoryRevision("backend", "main", "def456", "origin"),
                ),
                resolved_at=TEST_TIMESTAMP,
            )

    def test_release_bundle_requires_positive_build_attempt_id(self):
        """ReleaseBundle ссылается на реальную build attempt."""
        with self.assertRaisesRegex(ValueError, "build_attempt_id"):
            ReleaseBundle(
                build_version=TEST_BUILD_VERSION,
                source_snapshot=self._snapshot(),
                artifacts=(),
                created_at=TEST_TIMESTAMP,
                build_attempt_id=0,
            )


if __name__ == "__main__":
    unittest.main()
