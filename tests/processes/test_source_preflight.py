"""Read-only проверки на временной SQLite; Git и внешние команды подменены."""

import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

from simple_deploy.core.commands import CommandResult
from simple_deploy.processes.dry_run_checks import (
    Reporter,
    check_backend_build_inputs,
    check_repository_pairs,
    check_schema_baselines,
)

BASELINE = "a" * 40
TARGET = "b" * 40


def baseline_env(tmp_path, commit=BASELINE):
    """Создаёт минимальную временную БД без production state и миграций схемы."""
    db = tmp_path / "state.sqlite3"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute(
            "CREATE TABLE contour_state (contour TEXT, last_success_backend_commit TEXT)"
        )
        connection.executemany(
            "INSERT INTO contour_state VALUES (?, ?)",
            [(contour, commit) for contour in ("dev", "test", "prod")],
        )
        connection.commit()
    return {
        "SIMPLE_DEPLOY_STATE_DB": str(db),
        "BACKEND_SOURCE_REPO_PATH": str(tmp_path / "source"),
    }


def test_missing_state_is_reported_without_creating_database(tmp_path):
    db = tmp_path / "absent.sqlite3"
    reporter = Reporter()
    with patch(
        "simple_deploy.processes.dry_run_checks.run_command"
    ) as command:
        check_schema_baselines(reporter, {"SIMPLE_DEPLOY_STATE_DB": str(db)})
    assert reporter.issues
    assert not db.exists()
    command.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [
        "absent_table",
        "missing_baseline",
        "invalid_sha",
        "valid",
        "missing_commit",
        "not_ancestor",
        "missing_dev",
    ],
)
def test_baseline_checks_are_read_only(tmp_path, state):
    env = baseline_env(
        tmp_path,
        ""
        if state == "missing_baseline"
        else "bad"
        if state == "invalid_sha"
        else BASELINE,
    )
    db = tmp_path / "state.sqlite3"
    if state == "absent_table":
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("DROP TABLE contour_state")
            connection.commit()
    original = db.read_bytes()

    def git(args, **kwargs):
        assert kwargs["cwd"] == tmp_path / "source"
        assert args[:2] == ["git", "--no-replace-objects"]
        if args[2] == "rev-parse":
            if args[-1] == "dev^{commit}":
                return CommandResult(int(state == "missing_dev"), TARGET, "")
            assert args[-1] == BASELINE + "^{commit}"
            return CommandResult(int(state == "missing_commit"), BASELINE, "")
        assert args[2:] == ["merge-base", "--is-ancestor", BASELINE, TARGET]
        return CommandResult(int(state == "not_ancestor"), "", "")

    reporter = Reporter()
    with patch(
        "simple_deploy.processes.dry_run_checks.run_command", side_effect=git
    ):
        check_schema_baselines(reporter, env)
    assert bool(reporter.issues) == (state != "valid")
    assert db.read_bytes() == original
    assert not (tmp_path / "source").exists()


def test_repository_check_reports_same_path_without_commands(tmp_path):
    reporter = Reporter()
    check_repository_pairs(
        reporter,
        {
            "BACKEND_SOURCE_REPO_PATH": str(tmp_path),
            "BACKEND_TARGET_REPO_PATH": str(tmp_path),
        },
    )
    assert "совпадают" in reporter.issues[0]


def test_build_inputs_require_manage_py(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    reporter = Reporter()
    with patch(
        "simple_deploy.processes.dry_run_checks.run_command"
    ) as command:
        check_backend_build_inputs(
            reporter,
            {
                "BACKEND_SOURCE_REPO_PATH": str(tmp_path),
                "BACKEND_APP_ROOT_DIR": "app",
                "DEV_DOMAIN": "dev.example.local",
            },
        )
    assert any("manage.py" in issue for issue in reporter.issues)
    command.assert_not_called()
