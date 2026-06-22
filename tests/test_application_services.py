"""Тесты request boundary application services."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.application import services  # noqa: E402
from simple_deploy.application.requests import (  # noqa: E402
    BuildRequest,
    DeployRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    SetBaselineRequest,
)
from simple_deploy.application.results import ProcessResult  # noqa: E402
from simple_deploy.types import ContourCodeEnum  # noqa: E402


class ApplicationServiceTests(unittest.TestCase):
    """Проверяет, что application services открывают DTO-based use cases."""

    def test_build_service_passes_request_to_process(self):
        request = BuildRequest(timeout=77, skip_data_sql_artifacts=True)
        with patch(
            "simple_deploy.application.services._build_process",
            return_value=ProcessResult.failure(
                "build failed", exit_code=11
            ),
        ) as process_mock:
            self.assertEqual(services.build(request), 11)

        process_args = process_mock.call_args.args[0]
        self.assertIs(process_args, request)
        self.assertEqual(process_args.timeout, 77)
        self.assertTrue(process_args.skip_data_sql_artifacts)

    def test_deploy_service_passes_request_to_process(self):
        request = DeployRequest(
            build_version="1.2.3",
            contour=ContourCodeEnum.TEST,
            include_set_default_sql=True,
            app_only=True,
        )
        with patch(
            "simple_deploy.application.services._deploy_process",
            return_value=ProcessResult.success("deploy completed"),
        ) as process_mock:
            self.assertEqual(services.deploy(request), 0)

        process_args = process_mock.call_args.args[0]
        self.assertIs(process_args, request)
        self.assertEqual(process_args.build_version, "1.2.3")
        self.assertEqual(process_args.contour, ContourCodeEnum.TEST)
        self.assertTrue(process_args.include_set_default_sql)
        self.assertTrue(process_args.app_only)

    def test_mark_services_pass_requests_to_processes(self):
        cases = [
            (
                "set_baseline",
                "_set_baseline_process",
                SetBaselineRequest(
                    contour=ContourCodeEnum.TEST,
                    backend_commit="abc123",
                ),
                "backend_commit",
            ),
            (
                "mark_applied",
                "_mark_applied_process",
                MarkAppliedRequest(
                    contour=ContourCodeEnum.PROD,
                    build_version="1.2.3",
                ),
                "build_version",
            ),
            (
                "mark_failed",
                "_mark_failed_process",
                MarkFailedRequest(
                    contour=ContourCodeEnum.TEST,
                    build_version="1.2.3",
                    error="sql failed",
                ),
                "error",
            ),
        ]

        for public_name, process_name, request, expected_attr in cases:
            with self.subTest(public_name=public_name):
                patch_target = (
                    f"simple_deploy.application.services.{process_name}"
                )
                with patch(
                    patch_target,
                    return_value=ProcessResult.success("marked"),
                ) as process_mock:
                    self.assertEqual(
                        getattr(services, public_name)(request), 0
                    )

                process_args = process_mock.call_args.args[0]
                self.assertIs(process_args, request)
                self.assertEqual(process_args.contour, request.contour)
                self.assertEqual(
                    getattr(process_args, expected_attr),
                    getattr(request, expected_attr),
                )

    def test_pipeline_builds_phase_requests_without_mutating_source(self):
        request = PipelineRequest(
            timeout=77,
            contour=ContourCodeEnum.TEST,
            include_set_default_sql=True,
            skip_data_sql_artifacts=True,
            app_only=True,
        )

        with patch(
            "simple_deploy.application.services._dry_run_process",
            return_value=ProcessResult.success("dry-run ok"),
        ) as dry_run_mock:
            with patch(
                "simple_deploy.application.services._build_process",
                return_value=ProcessResult.success("build ok"),
            ) as build_mock:
                with patch(
                    "simple_deploy.application.services._deploy_process",
                    return_value=ProcessResult.success("deploy ok"),
                ) as deploy_mock:
                    self.assertEqual(services.pipeline(request), 0)

        dry_run_args = dry_run_mock.call_args.args[0]
        build_args = build_mock.call_args.args[0]
        deploy_args = deploy_mock.call_args.args[0]

        self.assertTrue(dry_run_args.skip_data_sql_artifacts)
        self.assertTrue(dry_run_args.app_only)
        self.assertEqual(build_args.timeout, 77)
        self.assertTrue(build_args.skip_data_sql_artifacts)
        self.assertTrue(deploy_args.latest)
        self.assertEqual(deploy_args.build_version, "")
        self.assertEqual(deploy_args.contour, ContourCodeEnum.TEST)
        self.assertTrue(deploy_args.include_set_default_sql)
        self.assertTrue(deploy_args.app_only)


if __name__ == "__main__":
    unittest.main()
