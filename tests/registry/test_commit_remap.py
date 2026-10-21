"""Проверки переноса baseline на настоящих SQLite и локальной Git history."""

from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools-ci"))

from simple_deploy.cli import remap_commits as cli  # noqa: E402
from simple_deploy.cli.remap_commits import main  # noqa: E402
from simple_deploy.registry import commit_remap as remap  # noqa: E402
from simple_deploy.registry import state  # noqa: E402
from simple_deploy.registry.state import connect_state_db  # noqa: E402


OLD_FIRST = "1" * 40
OLD_SECOND = "2" * 40


def git(repo, *args, input=None):
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Example",
            "-c",
            "user.email=example@example.invalid",
            *args,
        ],
        input=input,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    repo = tmp_path_factory.mktemp("source")
    git(repo, "init", "-b", "dev")
    migrations = repo / "project" / "app_example" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "0001_initial.py").write_text("# initial\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial")
    first = git(repo, "rev-parse", "HEAD")
    (migrations / "0002_field.py").write_text("# field\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Field")
    second = git(repo, "rev-parse", "HEAD")
    unrelated = git(
        repo, "commit-tree", "HEAD^{tree}", input="Separate history\n"
    )
    return repo, first, second, unrelated


@pytest.fixture
def inputs(tmp_path, source):
    repo, first, second, _ = source
    db_path = tmp_path / "runner.sqlite3"
    with closing(connect_state_db(db_path)) as con:
        con.executemany(
            "INSERT INTO contour_state VALUES (?, ?, ?, ?)",
            [
                ("dev", "release-2", OLD_SECOND, "before"),
                ("test", "release-1", OLD_FIRST, "before"),
                ("prod", "release-1", OLD_FIRST, "before"),
            ],
        )
        con.execute(
            "INSERT INTO releases VALUES (?, ?, ?, ?, ?)",
            ("release-1", OLD_FIRST, "f" * 40, '{"commit":"old"}', "before"),
        )
        con.execute(
            "INSERT INTO deployment_attempts "
            "(contour, build_version, backend_commit, status, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("prod", "release-1", OLD_FIRST, "success", "before", "before"),
        )
        con.commit()
    map_path = tmp_path / "commit-map"
    map_path.write_text(
        f"old new\n{OLD_FIRST} {first}\n{OLD_SECOND} {second}\n"
    )
    return db_path, map_path, repo


def snapshot(db_path):
    with closing(sqlite3.connect(db_path)) as con:
        return "\n".join(con.iterdump())


def test_preview_changes_nothing_and_does_not_create_backup(inputs):
    db_path, _, _ = inputs
    before = db_path.read_bytes()
    files = set(db_path.parent.iterdir())
    plan = remap.inspect_remap(*inputs)
    assert plan.valid
    assert len(plan.changes) == 3
    assert db_path.read_bytes() == before
    assert set(db_path.parent.iterdir()) == files


@pytest.mark.parametrize("wal", [False, True])
def test_apply_backups_all_data_preserves_history_and_is_repeatable(
    inputs, source, wal
):
    db_path, _, _ = inputs
    with closing(sqlite3.connect(db_path)) as keeper:
        if wal:
            keeper.execute("PRAGMA journal_mode=WAL")
            keeper.execute("UPDATE releases SET created_at='committed in WAL'")
            keeper.commit()
        before = snapshot(db_path)
        backup = remap.apply_remap(remap.inspect_remap(*inputs))
        assert backup.is_file()
        assert snapshot(backup) == before
        with closing(sqlite3.connect(db_path)) as con:
            assert con.execute(
                "SELECT contour, last_success_release, last_success_backend_commit "
                "FROM contour_state ORDER BY contour"
            ).fetchall() == [
                ("dev", "release-2", source[2]),
                ("prod", "release-1", source[1]),
                ("test", "release-1", source[1]),
            ]
            with closing(sqlite3.connect(backup)) as old:
                for table in (
                    "releases",
                    "deployment_attempts",
                    "build_attempts",
                    "local_jobs",
                ):
                    assert (
                        con.execute(f"SELECT * FROM {table}").fetchall()
                        == old.execute(f"SELECT * FROM {table}").fetchall()
                    )
        before_repeat = snapshot(db_path)
        assert remap.apply_remap(remap.inspect_remap(*inputs)) is None
        assert snapshot(db_path) == before_repeat
        assert len(list(db_path.parent.glob("*.before-commit-remap-*"))) == 1


@pytest.mark.parametrize(
    "replacement", ["0" * 40, "a" * 40, None, "unrelated"]
)
def test_bad_mapping_blocks_all_contours(inputs, source, replacement):
    db_path, map_path, _ = inputs
    if replacement == "unrelated":
        replacement = source[3]
    line = f"{OLD_FIRST} {replacement}\n" if replacement is not None else ""
    map_path.write_text(f"old new\n{line}{OLD_SECOND} {source[2]}\n")
    before = snapshot(db_path)
    plan = remap.inspect_remap(*inputs)
    assert not plan.valid
    assert any(row.error for row in plan.baselines)
    with pytest.raises(remap.RemapError, match="План содержит ошибки"):
        remap.apply_remap(plan)
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*"))


@pytest.mark.parametrize("change", ["baseline", "map"])
def test_stale_plan_is_rejected(inputs, change):
    db_path, map_path, _ = inputs
    plan = remap.inspect_remap(*inputs)
    if change == "baseline":
        with closing(sqlite3.connect(db_path)) as con:
            con.execute("UPDATE contour_state SET updated_at='changed'")
            con.commit()
    else:
        map_path.write_text(map_path.read_text() + "\n")
    before = snapshot(db_path)
    with pytest.raises(remap.RemapError, match="изменились после проверки"):
        remap.apply_remap(plan)
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*"))


def test_sql_error_rolls_back_every_contour(inputs):
    db_path, _, _ = inputs
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TRIGGER reject_prod BEFORE UPDATE ON contour_state "
            "WHEN NEW.contour = 'prod' BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
        con.commit()
    before = snapshot(db_path)
    with pytest.raises(sqlite3.IntegrityError, match="blocked"):
        remap.apply_remap(remap.inspect_remap(*inputs))
    assert snapshot(db_path) == before
    (backup,) = db_path.parent.glob("*.before-commit-remap-*")
    assert snapshot(backup) == before


def test_backup_failure_prevents_changes(inputs, monkeypatch):
    def fail_backup(_):
        raise OSError("backup failed")

    before = snapshot(inputs[0])
    monkeypatch.setattr(remap, "_backup_database", fail_backup)
    with pytest.raises(OSError, match="backup failed"):
        remap.apply_remap(remap.inspect_remap(*inputs))
    assert snapshot(inputs[0]) == before


@pytest.mark.parametrize(
    "table,status",
    [
        ("local_jobs", "running"),
        ("build_attempts", "started"),
        ("deployment_attempts", "started"),
    ],
)
def test_unfinished_operations_block_apply(inputs, table, status):
    db_path, _, _ = inputs
    with closing(sqlite3.connect(db_path)) as con:
        columns = con.execute(f"PRAGMA table_info({table})").fetchall()
        names = [row[1] for row in columns if row[1] != "id"]
        values = [status if name == "status" else "example" for name in names]
        con.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
            values,
        )
        con.commit()
    plan = remap.inspect_remap(*inputs)
    assert not plan.valid
    assert table in plan.blockers[0]


def test_missing_database_is_not_created(inputs, tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(remap.RemapError, match="не найдена"):
        remap.inspect_remap(missing, inputs[1], inputs[2])
    assert not missing.exists()


def test_empty_registry_is_not_initialized(inputs):
    db_path, _, _ = inputs
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("DELETE FROM contour_state")
        con.commit()
    before = snapshot(db_path)
    with pytest.raises(remap.RemapError, match="нет baseline"):
        remap.inspect_remap(*inputs)
    assert snapshot(db_path) == before


@pytest.mark.parametrize(
    "text",
    [
        "",
        "old new\n",
        "new old\n",
        "old new\nshort short\n",
        f"old new\n{OLD_FIRST} {OLD_SECOND}\n{OLD_FIRST} {OLD_SECOND}\n",
    ],
)
def test_invalid_map_is_rejected(tmp_path, text):
    path = tmp_path / "commit-map"
    path.write_text(text)
    with pytest.raises(remap.RemapError):
        remap.read_commit_map(path)


def test_prefixes_already_mapped_and_ambiguous_values():
    assert (
        remap.mapped_commit("1111111", {OLD_FIRST: OLD_SECOND}) == OLD_SECOND
    )
    assert (
        remap.mapped_commit(OLD_SECOND, {OLD_FIRST: OLD_SECOND}) == OLD_SECOND
    )
    assert remap.mapped_commit(OLD_FIRST, {OLD_FIRST: OLD_FIRST}) == OLD_FIRST
    with pytest.raises(remap.RemapError, match="Неоднозначный"):
        remap.mapped_commit("1111111", {OLD_FIRST: "1111111" + "a" * 33})
    with pytest.raises(remap.RemapError, match="одновременно old и new"):
        remap.mapped_commit(
            OLD_SECOND, {OLD_FIRST: OLD_SECOND, OLD_SECOND: "a" * 40}
        )


def test_cli_default_preview_and_explicit_apply(inputs, capsys):
    db_path, map_path, repo = inputs
    args = [
        "--db",
        str(db_path),
        "--commit-map",
        str(map_path),
        "--source-repo",
        str(repo),
    ]
    before = snapshot(db_path)
    assert main(args) == 0
    assert "Предварительный просмотр" in capsys.readouterr().out
    assert snapshot(db_path) == before
    assert main([*args, "--apply"]) == 0
    assert "Резервная копия" in capsys.readouterr().out


def test_cli_reports_deleted_mapping_without_writing(inputs, capsys):
    db_path, map_path, repo = inputs
    map_path.write_text(
        f"old new\n{OLD_FIRST} {'0' * 40}\n{OLD_SECOND} {'0' * 40}\n"
    )
    before = snapshot(db_path)
    assert (
        main(
            [
                "--db",
                str(db_path),
                "--commit-map",
                str(map_path),
                "--source-repo",
                str(repo),
                "--apply",
            ]
        )
        == 1
    )
    assert "Перенос заблокирован" in capsys.readouterr().out
    assert snapshot(db_path) == before


@pytest.fixture
def configured_runner(inputs, tmp_path, monkeypatch):
    """Настройки отдельного runner-а без доступа к рабочим путям машины."""
    db_path, map_path, repo = inputs
    env_file = tmp_path / "runner.env"
    env_file.write_text(
        f'BACKEND_SOURCE_REPO_PATH="{repo.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.setattr(cli, "BUNDLED_COMMIT_MAP", map_path)
    monkeypatch.setenv("SIMPLE_DEPLOY_STATE_DB", str(db_path))
    return inputs, env_file


def test_cli_without_paths_reads_config_applies_and_repeats(
    configured_runner, source, capsys
):
    (db_path, _, _), _ = configured_runner
    before = snapshot(db_path)
    assert main([]) == 0
    assert "Предварительный просмотр" in capsys.readouterr().out
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*.sqlite3"))

    assert main(["--apply"]) == 0
    assert "Резервная копия" in capsys.readouterr().out
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT last_success_backend_commit FROM contour_state "
            "WHERE contour='dev'"
        ).fetchone()[0] == source[2]
    backups = list(db_path.parent.glob("*.before-commit-remap-*.sqlite3"))
    assert len(backups) == 1
    assert snapshot(backups[0]) == before

    after = snapshot(db_path)
    assert main(["--apply"]) == 0
    assert "Изменения не требуются" in capsys.readouterr().out
    assert snapshot(db_path) == after
    assert list(db_path.parent.glob("*.before-commit-remap-*.sqlite3")) == backups


def test_cli_without_db_uses_registry_default_path(
    inputs, monkeypatch, capsys
):
    db_path, map_path, repo = inputs
    monkeypatch.delenv("SIMPLE_DEPLOY_STATE_DB", raising=False)
    monkeypatch.setattr(state, "default_state_db_path", lambda: db_path)
    before = snapshot(db_path)
    assert main([
        "--commit-map", str(map_path), "--source-repo", str(repo),
    ]) == 0
    assert str(db_path.resolve()) in capsys.readouterr().out
    assert snapshot(db_path) == before


@pytest.mark.parametrize("broken_input", ["map", "env", "source", "db"])
def test_cli_auto_paths_fail_closed(
    configured_runner, broken_input, monkeypatch, tmp_path, capsys
):
    (db_path, _, _), env_file = configured_runner
    before = snapshot(db_path)
    if broken_input == "map":
        monkeypatch.setattr(cli, "BUNDLED_COMMIT_MAP", tmp_path / "missing.map")
    elif broken_input == "env":
        monkeypatch.setattr(cli, "DEFAULT_ENV_FILE", tmp_path / "missing.env")
    elif broken_input == "source":
        env_file.write_text("BACKEND_SOURCE_REPO_PATH=\n", encoding="utf-8")
    else:
        monkeypatch.setenv("SIMPLE_DEPLOY_STATE_DB", str(tmp_path / "missing.db"))
    assert main(["--apply"]) == 1
    assert "Ошибка переноса baseline" in capsys.readouterr().err
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*.sqlite3"))
    assert not (tmp_path / "missing.db").exists()


def test_cli_conflicting_database_setting_requires_explicit_path(
    configured_runner, tmp_path, capsys
):
    (db_path, _, _), env_file = configured_runner
    with env_file.open("a", encoding="utf-8") as stream:
        stream.write(
            f'SIMPLE_DEPLOY_STATE_DB="{(tmp_path / "other.db").as_posix()}"\n'
        )
    before = snapshot(db_path)
    assert main(["--apply"]) == 1
    assert "Укажите нужную рабочую базу" in capsys.readouterr().err
    assert snapshot(db_path) == before
    assert main(["--db", str(db_path)]) == 0


def test_cli_explicit_paths_override_all_automatic_inputs(
    configured_runner, tmp_path, monkeypatch, capsys
):
    (db_path, map_path, repo), _ = configured_runner
    monkeypatch.setattr(cli, "BUNDLED_COMMIT_MAP", tmp_path / "missing.map")
    monkeypatch.setattr(cli, "DEFAULT_ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("SIMPLE_DEPLOY_STATE_DB", str(tmp_path / "missing.db"))
    before = snapshot(db_path)
    assert main([
        "--db", str(db_path), "--commit-map", str(map_path),
        "--source-repo", str(repo),
    ]) == 0
    assert "Предварительный просмотр" in capsys.readouterr().out
    assert snapshot(db_path) == before


def test_bundled_map_is_the_complete_pinned_rewrite():
    """Ресурс поставки содержит исходную карту, включая удалённые commits."""
    mapping, digest = remap.read_commit_map(cli.BUNDLED_COMMIT_MAP)
    assert digest == (
        "1ff2787de44097e70005f9a828c292883348e967636c0a74e65fbd8bdac68134"
    )
    assert len(mapping) == 4632
    assert sum(target == "0" * 40 for target in mapping.values()) == 804


@pytest.fixture
def interrupted_inputs(inputs):
    """Прерванные записи трёх типов рядом с очередью и успешной историей."""
    with closing(sqlite3.connect(inputs[0])) as con:
        for table, status in (
            ("local_jobs", "running"),
            ("build_attempts", "started"),
            ("deployment_attempts", "started"),
            ("local_jobs", "queued"),
        ):
            columns = con.execute(f"PRAGMA table_info({table})").fetchall()
            names = [row[1] for row in columns if row[1] != "id"]
            values = [status if name == "status" else "example" for name in names]
            con.execute(
                f"INSERT INTO {table} ({','.join(names)}) "
                f"VALUES ({','.join('?' for _ in names)})",
                values,
            )
        con.commit()
    return inputs


def test_interrupted_preview_requires_explicit_flag_and_never_writes(
    interrupted_inputs,
):
    before = snapshot(interrupted_inputs[0])
    blocked = remap.inspect_remap(*interrupted_inputs)
    assert not blocked.valid
    assert len(blocked.blockers) == 3
    assert len(blocked.incomplete_operations) == 3
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    assert plan.valid
    assert plan.incomplete_operations == blocked.incomplete_operations
    assert snapshot(interrupted_inputs[0]) == before
    assert not list(interrupted_inputs[0].parent.glob("*.before-commit-remap-*"))


@pytest.mark.parametrize("wal", [False, True])
def test_close_interrupted_backups_preserves_other_fields_and_repeats(
    interrupted_inputs, wal
):
    db_path = interrupted_inputs[0]
    with closing(sqlite3.connect(db_path)) as keeper:
        if wal:
            keeper.execute("PRAGMA journal_mode=WAL")
            keeper.execute("UPDATE releases SET created_at='committed in WAL'")
            keeper.commit()
        before = snapshot(db_path)
        plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
        backup = remap.apply_remap(plan)
        assert snapshot(backup) == before
        with closing(sqlite3.connect(db_path)) as con:
            con.row_factory = sqlite3.Row
            with closing(sqlite3.connect(backup)) as old:
                old.row_factory = sqlite3.Row
                for table in (
                    "local_jobs", "build_attempts", "deployment_attempts",
                ):
                    after = con.execute(
                        f"SELECT * FROM {table} ORDER BY id"
                    ).fetchall()
                    original = old.execute(
                        f"SELECT * FROM {table} ORDER BY id"
                    ).fetchall()
                    assert len(after) == len(original)
                    for row, previous in zip(after, original):
                        if previous["status"] not in {"running", "started"}:
                            assert dict(row) == dict(previous)
                            continue
                        assert row["status"] == "failed"
                        assert row["finished_at"] != previous["finished_at"]
                        assert row["error"].startswith(previous["error"] + "\n")
                        assert "--close-interrupted" in row["error"]
                        for key in previous.keys():
                            if key not in {"status", "error", "finished_at"}:
                                assert row[key] == previous[key]
                assert con.execute("SELECT * FROM releases").fetchall() == (
                    old.execute("SELECT * FROM releases").fetchall()
                )
                assert {
                    row[0] for row in con.execute(
                        "SELECT last_success_backend_commit FROM contour_state"
                    )
                } == {row.new_commit for row in plan.baselines}
        after = snapshot(db_path)
        repeated = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
        assert remap.apply_remap(repeated) is None
        assert snapshot(db_path) == after
        assert len(list(db_path.parent.glob("*.before-commit-remap-*"))) == 1


@pytest.mark.parametrize("change", ["details", "replacement", "finished"])
def test_close_interrupted_rechecks_records_not_just_counts(
    interrupted_inputs, change
):
    db_path = interrupted_inputs[0]
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    with closing(sqlite3.connect(db_path)) as con:
        if change == "details":
            con.execute("UPDATE local_jobs SET log_path='changed' WHERE status='running'")
        elif change == "replacement":
            con.execute("UPDATE local_jobs SET id=id+100 WHERE status='running'")
        else:
            con.execute("UPDATE local_jobs SET status='success' WHERE status='running'")
        con.commit()
    before = snapshot(db_path)
    with pytest.raises(remap.RemapError, match="изменились после проверки"):
        remap.apply_remap(plan)
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*"))


def test_close_interrupted_rolls_back_statuses_when_baseline_write_fails(
    interrupted_inputs,
):
    db_path = interrupted_inputs[0]
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TRIGGER reject_prod BEFORE UPDATE ON contour_state "
            "WHEN NEW.contour = 'prod' BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
        con.commit()
    before = snapshot(db_path)
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    with pytest.raises(sqlite3.IntegrityError, match="blocked"):
        remap.apply_remap(plan)
    assert snapshot(db_path) == before
    (backup,) = db_path.parent.glob("*.before-commit-remap-*")
    assert snapshot(backup) == before


def test_close_interrupted_does_not_override_bad_sha(interrupted_inputs):
    db_path, map_path, _ = interrupted_inputs
    map_path.write_text(
        f"old new\n{OLD_FIRST} {'0' * 40}\n{OLD_SECOND} {'0' * 40}\n"
    )
    before = snapshot(db_path)
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    assert not plan.valid
    with pytest.raises(remap.RemapError, match="План содержит ошибки"):
        remap.apply_remap(plan)
    assert snapshot(db_path) == before
    assert not list(db_path.parent.glob("*.before-commit-remap-*"))


def test_close_interrupted_backup_failure_leaves_statuses_intact(
    interrupted_inputs, monkeypatch,
):
    def fail_backup(_):
        raise OSError("backup failed")

    before = snapshot(interrupted_inputs[0])
    monkeypatch.setattr(remap, "_backup_database", fail_backup)
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    with pytest.raises(OSError, match="backup failed"):
        remap.apply_remap(plan)
    assert snapshot(interrupted_inputs[0]) == before


def test_close_interrupted_can_finish_after_sha_already_remapped(
    interrupted_inputs, source,
):
    db_path = interrupted_inputs[0]
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "UPDATE contour_state SET last_success_backend_commit=?",
            (source[2],),
        )
        con.commit()
    plan = remap.inspect_remap(*interrupted_inputs, close_interrupted=True)
    assert plan.valid and not plan.changes
    assert remap.apply_remap(plan).is_file()
    after = remap.inspect_remap(*interrupted_inputs)
    assert after.valid and not after.incomplete_operations
    assert after.baselines == plan.baselines


def test_cli_close_interrupted_preview_and_apply(
    interrupted_inputs, configured_runner, capsys,
):
    before = snapshot(interrupted_inputs[0])
    assert main([]) == 1
    assert "--close-interrupted" in capsys.readouterr().out
    assert main(["--close-interrupted"]) == 0
    output = capsys.readouterr().out
    assert "Незавершённая запись: local_jobs id=" in output
    assert "будут закрыты как failed" in output
    assert snapshot(interrupted_inputs[0]) == before
    assert main(["--close-interrupted", "--apply"]) == 0
    assert "Закрыто прерванных операций: 3" in capsys.readouterr().out
