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
    ArtifactKindEnum,
    ArtifactScopeEnum,
)
from simple_deploy.types.component import COMPONENT_IDS, ComponentIdEnum
from simple_deploy.types.contour import (
    CONTOUR_CODES,
    ContourCodeEnum,
    JOB_CONTOUR_SCOPE_CODES,
    JobContourScope,
)
from simple_deploy.types.fields import ResolvedAtString
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
    NGINX_STOP_START_ACTIONS,
    NGINX_UNSUPPORTED_ACTIONS,
    SERVICE_STEP_PHASES,
    SYSTEMCTL_ACTIONS,
    MaintenanceSqlPhaseEnum,
    ServiceStepPhaseEnum,
    SystemctlActionEnum,
)
from simple_deploy.types.source import (
    SOURCE_ORIGIN_KINDS,
    CommitShaString,
    OptionalCommitShaString,
    RepoId,
    SourceOriginKindEnum,
)
from simple_deploy.types.status import (
    BUILD_ATTEMPT_STATUSES,
    DEPLOYMENT_ATTEMPT_STATUSES,
    EXTERNAL_REQUEST_STATUSES,
    JOB_STATUSES,
    BuildAttemptStatusEnum,
    DeploymentAttemptStatusEnum,
    ExternalRequestStatusEnum,
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

    def test_annotated_string_types_expose_schema_descriptions(self):
        """Annotated string aliases отдают описания в JSON schema."""
        build_schema = TypeAdapter(BuildVersionString).json_schema()
        release_schema = TypeAdapter(ReleaseVersionString).json_schema()
        repo_schema = TypeAdapter(RepoId).json_schema()
        resolved_schema = TypeAdapter(ResolvedAtString).json_schema()

        self.assertIn("release resource", release_schema["description"])
        self.assertIn("release bundle", build_schema["description"])
        self.assertIn("не сам bundle", build_schema["description"])
        self.assertIn("Строковый код", repo_schema["description"])
        self.assertIn("не числовой", repo_schema["description"])
        self.assertIn("source snapshot", resolved_schema["description"])

    def test_contour_code_accepts_only_exact_known_contours(self):
        """ContourCodeEnum принимает только точные значения известных контуров."""
        adapter = TypeAdapter(ContourCodeEnum)

        self.assertIs(adapter.validate_python("dev"), ContourCodeEnum.DEV)
        self.assertIs(adapter.validate_python("test"), ContourCodeEnum.TEST)
        self.assertIs(adapter.validate_python("prod"), ContourCodeEnum.PROD)
        for value in ("DEV", " test ", "stage"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_job_contour_scope_allows_unscoped_job_marker(self):
        """JobContourScope допускает unscoped job marker и реальные контуры."""
        adapter = TypeAdapter(JobContourScope)

        self.assertEqual(adapter.validate_python(""), "")
        self.assertEqual(adapter.validate_python("test"), "test")
        self.assertEqual(
            JOB_CONTOUR_SCOPE_CODES,
            ("", *CONTOUR_CODES),
        )
        for value in ("  ", "TEST", "stage"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_status_types_accept_only_their_own_dictionaries(self):
        """Status types проверяют значения по своим жизненным циклам."""
        self.assertIs(
            TypeAdapter(BuildAttemptStatusEnum).validate_python("success"),
            BuildAttemptStatusEnum.SUCCESS,
        )
        self.assertIs(
            TypeAdapter(BuildAttemptStatusEnum).validate_python("undefined"),
            BuildAttemptStatusEnum.UNDEFINED,
        )
        self.assertIs(
            TypeAdapter(DeploymentAttemptStatusEnum).validate_python("failed"),
            DeploymentAttemptStatusEnum.FAILED,
        )
        self.assertIs(
            TypeAdapter(JobStatusEnum).validate_python("queued"),
            JobStatusEnum.QUEUED,
        )
        self.assertIs(
            TypeAdapter(ExternalRequestStatusEnum).validate_python("approved"),
            ExternalRequestStatusEnum.APPROVED,
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(BuildAttemptStatusEnum).validate_python("SUCCESS")
        with self.assertRaises(ValidationError):
            TypeAdapter(DeploymentAttemptStatusEnum).validate_python(" failed ")
        with self.assertRaises(ValidationError):
            TypeAdapter(BuildAttemptStatusEnum).validate_python("queued")
        with self.assertRaises(ValidationError):
            TypeAdapter(JobStatusEnum).validate_python("submitted")
        with self.assertRaises(ValidationError):
            TypeAdapter(ExternalRequestStatusEnum).validate_python("running")

    def test_runtime_phase_types_accept_only_pipeline_phases(self):
        """Runtime phase types проверяют фазы SQL, service step и systemctl actions."""
        self.assertIs(
            TypeAdapter(MaintenanceSqlPhaseEnum).validate_python("before_unpack"),
            MaintenanceSqlPhaseEnum.BEFORE_UNPACK,
        )
        self.assertIs(
            TypeAdapter(ServiceStepPhaseEnum).validate_python("after_frontend_unpack"),
            ServiceStepPhaseEnum.AFTER_FRONTEND_UNPACK,
        )
        self.assertIs(
            TypeAdapter(SystemctlActionEnum).validate_python("try-restart"),
            SystemctlActionEnum.TRY_RESTART,
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(MaintenanceSqlPhaseEnum).validate_python(" BEFORE_UNPACK ")
        with self.assertRaises(ValidationError):
            TypeAdapter(ServiceStepPhaseEnum).validate_python("AFTER_FRONTEND_UNPACK")
        with self.assertRaises(ValidationError):
            TypeAdapter(SystemctlActionEnum).validate_python("TRY-RESTART")
        with self.assertRaises(ValidationError):
            TypeAdapter(MaintenanceSqlPhaseEnum).validate_python("during_deploy")
        with self.assertRaises(ValidationError):
            TypeAdapter(ServiceStepPhaseEnum).validate_python("before_migrate")
        with self.assertRaises(ValidationError):
            TypeAdapter(SystemctlActionEnum).validate_python("enable")

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
        """JobKindEnum и ExternalRequestTypeEnum проверяют операционные словари."""
        self.assertIs(
            TypeAdapter(JobKindEnum).validate_python("mark_applied"),
            JobKindEnum.MARK_APPLIED,
        )
        self.assertIs(
            TypeAdapter(JobKindEnum).validate_python("deploy"),
            JobKindEnum.DEPLOY,
        )
        self.assertIs(
            TypeAdapter(ExternalRequestTypeEnum).validate_python("deploy"),
            ExternalRequestTypeEnum.DEPLOY,
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(JobKindEnum).validate_python("MARK_APPLIED")
        with self.assertRaises(ValidationError):
            TypeAdapter(JobKindEnum).validate_python(" deploy ")
        with self.assertRaises(ValidationError):
            TypeAdapter(ExternalRequestTypeEnum).validate_python(" DEPLOY ")
        with self.assertRaises(ValidationError):
            TypeAdapter(JobKindEnum).validate_python("rollback")
        with self.assertRaises(ValidationError):
            TypeAdapter(ExternalRequestTypeEnum).validate_python("rollback")

    def test_release_trigger_type_accepts_current_trigger_dictionary(self):
        """ReleaseTriggerTypeEnum проверяет словарь technical release triggers."""
        self.assertIs(
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("manual"),
            ReleaseTriggerTypeEnum.MANUAL,
        )
        self.assertIs(
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("backend_branch_push"),
            ReleaseTriggerTypeEnum.BACKEND_BRANCH_PUSH,
        )
        self.assertIs(
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("scheduled"),
            ReleaseTriggerTypeEnum.SCHEDULED,
        )
        self.assertIs(
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("undefined"),
            ReleaseTriggerTypeEnum.UNDEFINED,
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("MANUAL")
        with self.assertRaises(ValidationError):
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python(" backend_branch_push ")
        with self.assertRaises(ValidationError):
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("SCHEDULED")
        with self.assertRaises(ValidationError):
            TypeAdapter(ReleaseTriggerTypeEnum).validate_python("frontend_branch_push")

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
        """SourceOriginKindEnum проверяет словарь источников Git-данных."""
        self.assertIs(
            TypeAdapter(SourceOriginKindEnum).validate_python("primary_remote"),
            SourceOriginKindEnum.PRIMARY_REMOTE,
        )
        self.assertIs(
            TypeAdapter(SourceOriginKindEnum).validate_python("mirror"),
            SourceOriginKindEnum.MIRROR,
        )
        self.assertIs(
            TypeAdapter(SourceOriginKindEnum).validate_python("local_bare_clone"),
            SourceOriginKindEnum.LOCAL_BARE_CLONE,
        )

        with self.assertRaises(ValidationError):
            TypeAdapter(SourceOriginKindEnum).validate_python("PRIMARY_REMOTE")
        with self.assertRaises(ValidationError):
            TypeAdapter(SourceOriginKindEnum).validate_python(" mirror ")
        with self.assertRaises(ValidationError):
            TypeAdapter(SourceOriginKindEnum).validate_python("LOCAL_BARE_CLONE")
        with self.assertRaises(ValidationError):
            TypeAdapter(SourceOriginKindEnum).validate_python("ftp_remote")

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
        """ComponentIdEnum принимает начальный словарь DDD components."""
        adapter = TypeAdapter(ComponentIdEnum)

        self.assertIs(adapter.validate_python("backend"), ComponentIdEnum.BACKEND)
        self.assertIs(adapter.validate_python("frontend"), ComponentIdEnum.FRONTEND)
        self.assertIs(adapter.validate_python("database"), ComponentIdEnum.DATABASE)
        for value in ("BACKEND", " frontend ", "cache"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)

    def test_artifact_types_accept_kind_and_scope_dictionaries(self):
        """ArtifactKindEnum и ArtifactScopeEnum проверяют справочники артефактов."""
        kind_adapter = TypeAdapter(ArtifactKindEnum)
        scope_adapter = TypeAdapter(ArtifactScopeEnum)

        self.assertIs(kind_adapter.validate_python("db_schema"), ArtifactKindEnum.DB_SCHEMA)
        self.assertIs(kind_adapter.validate_python("manifest"), ArtifactKindEnum.MANIFEST)
        self.assertIs(
            scope_adapter.validate_python("contour_specific"),
            ArtifactScopeEnum.CONTOUR_SPECIFIC,
        )
        self.assertIs(scope_adapter.validate_python("shared"), ArtifactScopeEnum.SHARED)
        with self.assertRaises(ValidationError):
            kind_adapter.validate_python("DB_SCHEMA")
        with self.assertRaises(ValidationError):
            scope_adapter.validate_python("CONTOUR_SPECIFIC")
        with self.assertRaises(ValidationError):
            kind_adapter.validate_python("db_insert")
        with self.assertRaises(ValidationError):
            scope_adapter.validate_python("global")

    def test_deployment_target_role_accepts_initial_role_dictionary(self):
        """DeploymentTargetRoleEnum принимает роли deploy entrypoints."""
        adapter = TypeAdapter(DeploymentTargetRoleEnum)

        self.assertIs(adapter.validate_python("database"), DeploymentTargetRoleEnum.DATABASE)
        self.assertIs(adapter.validate_python("reporting"), DeploymentTargetRoleEnum.REPORTING)
        self.assertIs(adapter.validate_python("s3"), DeploymentTargetRoleEnum.S3)
        for value in ("DATABASE", " reporting ", "worker"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)


if __name__ == "__main__":
    unittest.main()
