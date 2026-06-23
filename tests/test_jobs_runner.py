"""Тесты local job runner поверх application request boundary."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS_CI_ROOT = ROOT / "tools-ci"
STATE_DB_NAME = "state.sqlite3"

sys.path.insert(0, str(TOOLS_CI_ROOT))

from simple_deploy.application.requests import BuildRequest  # noqa: E402
from simple_deploy.application.results import ProcessResult  # noqa: E402
from simple_deploy.jobs.runner import (  # noqa: E402
    create_job_for_request,
    request_from_job,
    run_local_job,
)
from simple_deploy.jobs.worker import (  # noqa: E402
    WORKER_IDLE_EXIT_CODE,
    run_worker_loop,
)
from simple_deploy.registry.commands import (  # noqa: E402
    cancel_local_job,
    requeue_local_job,
)
from simple_deploy.registry.queries import (  # noqa: E402
    job_read_model_from_state,
    worker_health_read_model_from_state,
)


class LocalJobRunnerTests(unittest.TestCase):
    """Проверяет создание и выполнение local jobs без HTTP/CLI adapter-а."""

    def test_create_and_run_local_job_from_application_request(self):
        """Runner восстанавливает request из payload и двигает lifecycle job."""
        request = BuildRequest(timeout=77, skip_data_sql_artifacts=True)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_job_for_request(request)
                restored = request_from_job(created)
                with patch(
                    "simple_deploy.jobs.runner.result_for_request",
                    return_value=ProcessResult.success("ok"),
                ) as run_mock:
                    result = run_local_job(created.id)

        self.assertEqual(created.kind, "build")
        self.assertEqual(created.status, "queued")
        self.assertEqual(restored.timeout, 77)
        self.assertTrue(restored.skip_data_sql_artifacts)
        self.assertEqual(result.job.status, "success")
        self.assertTrue(result.process_result.ok)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0].timeout, 77)

    def test_run_local_job_records_failure_result(self):
        """Runner фиксирует failed job, если use case вернул неуспешный result."""
        request = BuildRequest(timeout=77)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_job_for_request(request)
                with patch(
                    "simple_deploy.jobs.runner.result_for_request",
                    return_value=ProcessResult.failure(
                        "build failed", exit_code=5
                    ),
                ):
                    result = run_local_job(created.id)

        self.assertEqual(result.job.status, "failed")
        self.assertEqual(result.job.error, "build failed")
        self.assertEqual(result.process_result.exit_code, 5)

    def test_worker_once_claims_job_and_writes_log_path(self):
        """Worker --once забирает queued job, выполняет ее и пишет log file."""
        request = BuildRequest(timeout=77)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            log_path = Path(tmp) / "job.log"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_job_for_request(request)
                with patch(
                    "simple_deploy.jobs.worker.create_log_file",
                    return_value=log_path,
                ):
                    with patch(
                        "simple_deploy.jobs.runner.result_for_request",
                        return_value=ProcessResult.success("ok"),
                    ):
                        exit_code = run_worker_loop(once=True)
                restored = request_from_job(created)
                updated = job_read_model_from_state(created.id)
                health = worker_health_read_model_from_state()

            log_text = log_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(restored.timeout, 77)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "success")
        self.assertEqual(updated.log_path, str(log_path))
        self.assertEqual(health.status, "offline")
        self.assertIsNotNone(health.heartbeat)
        self.assertEqual(health.heartbeat.status, "stopped")
        self.assertEqual(health.queued_jobs, 0)
        self.assertEqual(health.running_jobs, 0)
        self.assertIn("WORKER claimed job", log_text)
        self.assertIn("WORKER finished job", log_text)

    def test_worker_once_returns_idle_code_without_queued_jobs(self):
        """Worker --once возвращает отдельный код, если очередь пуста."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                exit_code = run_worker_loop(once=True)
                health = worker_health_read_model_from_state()

        self.assertEqual(exit_code, WORKER_IDLE_EXIT_CODE)
        self.assertEqual(health.status, "offline")
        self.assertIsNotNone(health.heartbeat)
        self.assertEqual(health.heartbeat.status, "stopped")

    def test_worker_ignores_cancelled_job_and_runs_requeued_job(self):
        """Worker не claim-ит cancelled job, но выполняет requeued job."""
        request = BuildRequest(timeout=77)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / STATE_DB_NAME
            log_path = Path(tmp) / "retry.log"
            with patch.dict(os.environ, {"SIMPLE_DEPLOY_STATE_DB": str(db_path)}):
                created = create_job_for_request(request)
                cancelled = cancel_local_job(created.id)
                idle_code = run_worker_loop(once=True)
                after_idle = job_read_model_from_state(created.id)
                requeued = requeue_local_job(cancelled.job.id)
                with patch(
                    "simple_deploy.jobs.worker.create_log_file",
                    return_value=log_path,
                ):
                    with patch(
                        "simple_deploy.jobs.runner.result_for_request",
                        return_value=ProcessResult.success("ok"),
                    ):
                        run_code = run_worker_loop(once=True)
                updated = job_read_model_from_state(created.id)

        self.assertEqual(idle_code, WORKER_IDLE_EXIT_CODE)
        self.assertIsNotNone(after_idle)
        self.assertEqual(after_idle.status, "cancelled")
        self.assertEqual(requeued.job.id, created.id)
        self.assertEqual(run_code, 0)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "success")
        self.assertEqual(updated.log_path, str(log_path))


if __name__ == "__main__":
    unittest.main()
