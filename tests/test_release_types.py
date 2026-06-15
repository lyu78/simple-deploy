"""Тесты constrained types для версий релиза."""

import sys
import unittest
from pathlib import Path

from pydantic import TypeAdapter, ValidationError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.types._enum import DomainStringEnum
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
from simple_deploy.types.release import BuildVersionString, OptionalBuildVersionString
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


class ReleaseTypeTests(unittest.TestCase):
    """Проверяет первый безопасный слой custom primitive типов."""

    def test_dictionary_constants_are_backed_by_enums(self):
        """Справочные tuple-константы собираются из enum-классов."""
        cases = (
            (ARTIFACT_KINDS, ArtifactKindEnum),
            (ARTIFACT_SCOPES, ArtifactScopeEnum),
            (COMPONENT_IDS, ComponentIdEnum),
            (CONTOUR_CODES, ContourCodeEnum),
            (BUILD_ATTEMPT_STATUSES, BuildAttemptStatusEnum),
            (DEPLOYMENT_ATTEMPT_STATUSES, DeploymentAttemptStatusEnum),
            (JOB_STATUSES, JobStatusEnum),
            (EXTERNAL_REQUEST_STATUSES, ExternalRequestStatusEnum),
            (DEPLOYMENT_TARGET_ROLES, DeploymentTargetRoleEnum),
            (MAINTENANCE_SQL_PHASES, MaintenanceSqlPhaseEnum),
            (SERVICE_STEP_PHASES, ServiceStepPhaseEnum),
            (SYSTEMCTL_ACTIONS, SystemctlActionEnum),
            (JOB_KINDS, JobKindEnum),
            (EXTERNAL_REQUEST_TYPES, ExternalRequestTypeEnum),
            (RELEASE_TRIGGER_TYPES, ReleaseTriggerTypeEnum),
            (SOURCE_ORIGIN_KINDS, SourceOriginKindEnum),
        )

        for constant_values, enum_class in cases:
            with self.subTest(enum_class=enum_class.__name__):
                self.assertEqual(constant_values, enum_class.get_values())
                self.assertEqual(enum_class.get_values(), tuple(item.value for item in enum_class))
                self.assertTrue(issubclass(enum_class, DomainStringEnum))

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

    def test_runtime_phase_types_accept_only_pipeline_phases(self):
        """Runtime phase types проверяют фазы SQL, service step и systemctl actions."""
        self.assertEqual(TypeAdapter(MaintenanceSqlPhase).validate_python(" BEFORE_UNPACK "), "before_unpack")
        self.assertEqual(
            TypeAdapter(ServiceStepPhase).validate_python("AFTER_FRONTEND_UNPACK"),
            "after_frontend_unpack",
        )
        self.assertEqual(TypeAdapter(SystemctlAction).validate_python("TRY-RESTART"), "try-restart")

        with self.assertRaises(ValidationError):
            TypeAdapter(MaintenanceSqlPhase).validate_python("during_deploy")
        with self.assertRaises(ValidationError):
            TypeAdapter(ServiceStepPhase).validate_python("before_migrate")
        with self.assertRaises(ValidationError):
            TypeAdapter(SystemctlAction).validate_python("enable")

    def test_nginx_action_policy_sets_are_backed_by_systemctl_enum(self):
        """Nginx action policy sets собираются из SystemctlActionEnum values."""
        self.assertEqual(
            NGINX_STOP_START_ACTIONS,
            frozenset(
                {
                    SystemctlActionEnum.STOP.value,
                    SystemctlActionEnum.START.value,
                }
            ),
        )
        self.assertEqual(
            NGINX_UNSUPPORTED_ACTIONS,
            frozenset(
                {
                    SystemctlActionEnum.RESTART.value,
                    SystemctlActionEnum.RELOAD.value,
                    SystemctlActionEnum.TRY_RESTART.value,
                    SystemctlActionEnum.RELOAD_OR_RESTART.value,
                    SystemctlActionEnum.RELOAD_OR_TRY_RESTART.value,
                }
            ),
        )

    def test_job_and_request_types_accept_current_operation_dictionaries(self):
        """JobKind и ExternalRequestType проверяют текущие операционные словари."""
        self.assertEqual(TypeAdapter(JobKind).validate_python("MARK_APPLIED"), "mark_applied")
        self.assertEqual(TypeAdapter(JobKind).validate_python(" deploy "), "deploy")
        self.assertEqual(TypeAdapter(ExternalRequestType).validate_python(" DEPLOY "), "deploy")

        with self.assertRaises(ValidationError):
            TypeAdapter(JobKind).validate_python("rollback")
        with self.assertRaises(ValidationError):
            TypeAdapter(ExternalRequestType).validate_python("rollback")

    def test_release_trigger_type_accepts_current_trigger_dictionary(self):
        """ReleaseTriggerType проверяет текущий словарь technical release triggers."""
        self.assertEqual(TypeAdapter(ReleaseTriggerType).validate_python("MANUAL"), "manual")
        self.assertEqual(
            TypeAdapter(ReleaseTriggerType).validate_python(" backend_branch_push "),
            "backend_branch_push",
        )
        self.assertEqual(TypeAdapter(ReleaseTriggerType).validate_python("SCHEDULED"), "scheduled")

        with self.assertRaises(ValidationError):
            TypeAdapter(ReleaseTriggerType).validate_python("frontend_branch_push")

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

    def test_source_origin_kind_accepts_current_origin_dictionary(self):
        """SourceOriginKind проверяет словарь источников Git-данных."""
        self.assertEqual(TypeAdapter(SourceOriginKind).validate_python("PRIMARY_REMOTE"), "primary_remote")
        self.assertEqual(TypeAdapter(SourceOriginKind).validate_python(" mirror "), "mirror")
        self.assertEqual(
            TypeAdapter(SourceOriginKind).validate_python("LOCAL_BARE_CLONE"),
            "local_bare_clone",
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(SourceOriginKind).validate_python("ftp_remote")

    def test_repo_id_accepts_stable_repository_identifiers(self):
        """RepoId принимает стабильные идентификаторы репозиториев без path-синтаксиса."""
        adapter = TypeAdapter(RepoId)

        self.assertEqual(adapter.validate_python("backend"), "backend")
        self.assertEqual(adapter.validate_python(" frontend-app "), "frontend-app")
        self.assertEqual(adapter.validate_python("db.migrations"), "db.migrations")

        for value in ("", "   ", "../backend", "group/backend", "group\\backend"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_machine_id_accepts_stable_machine_identifiers(self):
        """MachineId принимает стабильные идентификаторы VM без path-синтаксиса."""
        adapter = TypeAdapter(MachineId)

        self.assertEqual(adapter.validate_python("dev-app-01"), "dev-app-01")
        self.assertEqual(adapter.validate_python(" prod.db.01 "), "prod.db.01")

        for value in ("", "   ", "../dev-app", "prod/db", "prod\\db"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

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
