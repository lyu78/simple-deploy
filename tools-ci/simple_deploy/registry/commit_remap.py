"""Перевод текущих baseline runner-а после переписывания source Git history.

Источник соответствий — переданный git-filter-repo commit-map. Инструмент
не проверяет реальную БД приложения и не применяет миграции. Он переводит
только contour_state.last_success_backend_commit, сохраняя release version,
историю сборок/размещений и manifest. Явный режим close_interrupted также
закрывает указанные в плане running/started записи как failed, без удаления.
Схема runner-а не инициализируется.
Применение атомарно, предваряется SQLite backup и требует остановки worker-а
и других операций runner-а. Зависимости ограничены стандартной библиотекой.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid


SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
PREFIX_RE = re.compile(r"[0-9a-f]{7,64}\Z")
CONTOURS = {"dev", "test", "prod"}
INCOMPLETE_STATUSES = {
    "local_jobs": "running",
    "build_attempts": "started",
    "deployment_attempts": "started",
}


class RemapError(ValueError):
    """Ошибка, при которой перенос baseline выполнять нельзя."""


@dataclass(frozen=True)
class BaselineMapping:
    """Исходная запись контура и её предполагаемый новый source commit."""

    contour: str
    release: str
    old_commit: str
    updated_at: str
    new_commit: str = ""
    error: str = ""

    @property
    def changed(self) -> bool:
        return not self.error and self.old_commit != self.new_commit


@dataclass(frozen=True)
class IncompleteOperation:
    """Запись, которую оператор считает прерванной; снимок защищает от гонок."""

    table: str
    id: int
    status: str
    started_at: str
    snapshot: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class RemapPlan:
    """Проверенный снимок входов; повторно сверяется перед записью baseline."""

    db_path: Path
    map_path: Path
    source_repo: Path
    source_ref: str
    source_commit: str
    map_sha256: str
    baselines: tuple[BaselineMapping, ...]
    blockers: tuple[str, ...]
    incomplete_operations: tuple[IncompleteOperation, ...] = ()
    close_interrupted: bool = False

    @property
    def changes(self) -> tuple[BaselineMapping, ...]:
        return tuple(row for row in self.baselines if row.changed)

    @property
    def valid(self) -> bool:
        return not self.blockers and all(
            not row.error for row in self.baselines
        )


def read_commit_map(path: Path) -> tuple[dict[str, str], str]:
    """Читает строгую карту old/new и её digest без изменения файла."""
    raw = path.read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    if not lines or lines[0].split() != ["old", "new"]:
        raise RemapError("Ожидается commit-map с заголовком 'old new'.")
    mapping: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.lower().split()
        if (
            len(parts) != 2
            or not all(SHA_RE.fullmatch(value) for value in parts)
            or len(parts[0]) != len(parts[1])
            or set(parts[0]) == {"0"}
        ):
            raise RemapError(f"Некорректная строка commit-map: {number}.")
        old, new = parts
        if old in mapping:
            raise RemapError(f"Повторный old SHA в commit-map: {old}.")
        mapping[old] = new
    if not mapping:
        raise RemapError("Commit-map не содержит соответствий.")
    return mapping, hashlib.sha256(raw).hexdigest()


def mapped_commit(value: str, mapping: dict[str, str]) -> str:
    """Разрешает SHA ровно один раз; удалённые/неясные значения запрещены.

    Уже переведённый SHA сохраняется. Короткий SHA допустим только при
    единственном совпадении среди старых и новых значений карты.
    """
    sha = value.strip().lower()
    if not PREFIX_RE.fullmatch(sha):
        raise RemapError(f"Некорректный baseline SHA: {value!r}.")
    destinations = {v for v in mapping.values() if set(v) != {"0"}}
    candidates = set(mapping) | destinations
    if sha not in candidates:
        matches = {
            candidate for candidate in candidates if candidate.startswith(sha)
        }
        if not matches:
            raise RemapError(f"SHA отсутствует в commit-map: {sha}.")
        if len(matches) != 1:
            raise RemapError(f"Неоднозначный короткий SHA: {sha}.")
        sha = matches.pop()
    if sha in mapping:
        target = mapping[sha]
        if sha in destinations and target != sha:
            raise RemapError(f"SHA одновременно old и new в карте: {sha}.")
        if set(target) == {"0"}:
            raise RemapError(
                f"Коммит удалён при переписывании: {sha}; "
                "автоматического соответствия нет."
            )
        return target
    return sha


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _source_commit(repo: Path, ref: str) -> str:
    result = _git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
    )
    if result.returncode:
        raise RemapError(
            f"Не удалось прочитать source ref {ref!r}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _verify_target(repo: Path, sha: str, source_commit: str) -> None:
    result = _git(repo, "cat-file", "-t", sha)
    if result.returncode or result.stdout.strip() != "commit":
        raise RemapError(f"Нового commit {sha} нет в backend source repo.")
    result = _git(repo, "merge-base", "--is-ancestor", sha, source_commit)
    if result.returncode:
        raise RemapError(
            f"Новый commit {sha} не является предком выбранного source ref "
            "или Git не смог проверить его историю."
        )


def _connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    """Открывает только существующую SQLite; read-only не создаёт схему."""
    if not path.is_file():
        raise RemapError(f"База runner-а не найдена: {path}.")
    mode = "rw" if writable else "ro"
    connection = sqlite3.connect(
        path.as_uri() + f"?mode={mode}", uri=True, timeout=5
    )
    connection.row_factory = sqlite3.Row
    return connection


def _build_plan(
    connection: sqlite3.Connection,
    db_path: Path,
    map_path: Path,
    source_repo: Path,
    source_ref: str,
    close_interrupted: bool = False,
) -> RemapPlan:
    mapping, digest = read_commit_map(map_path)
    source_commit = _source_commit(source_repo, source_ref)
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(contour_state)")
    }
    required = {
        "contour",
        "last_success_release",
        "last_success_backend_commit",
        "updated_at",
    }
    if not required.issubset(columns):
        raise RemapError("В базе нет ожидаемой таблицы contour_state.")
    rows = connection.execute(
        "SELECT contour, last_success_release, last_success_backend_commit, "
        "updated_at FROM contour_state ORDER BY contour"
    ).fetchall()
    if not rows:
        raise RemapError("В contour_state нет baseline для переноса.")
    blockers = []
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    incomplete_operations = []
    for table, status in INCOMPLETE_STATUSES.items():
        if table in tables:
            operations = connection.execute(
                f"SELECT * FROM {table} WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
            for operation in operations:
                if not {"id", "started_at", "finished_at", "error"}.issubset(
                    operation.keys()
                ):
                    raise RemapError(
                        f"В {table} нет полей для завершения операции."
                    )
                incomplete_operations.append(IncompleteOperation(
                    table=table,
                    id=operation["id"],
                    status=status,
                    started_at=operation["started_at"],
                    snapshot=tuple(
                        (key, operation[key]) for key in operation.keys()
                    ),
                ))
            if operations and not close_interrupted:
                blockers.append(
                    f"В {table} есть незавершённые операции "
                    f"({status}: {len(operations)})."
                )
    baselines = []
    for row in rows:
        new_commit = ""
        error = ""
        try:
            if row["contour"] not in CONTOURS:
                raise RemapError(f"Неизвестный контур: {row['contour']!r}.")
            value = row["last_success_backend_commit"]
            if not isinstance(value, str):
                raise RemapError("Baseline должен содержать строковый SHA.")
            new_commit = mapped_commit(value, mapping)
            _verify_target(source_repo, new_commit, source_commit)
        except RemapError as exc:
            error = str(exc)
        baselines.append(
            BaselineMapping(
                contour=row["contour"],
                release=row["last_success_release"],
                old_commit=row["last_success_backend_commit"],
                updated_at=row["updated_at"],
                new_commit=new_commit,
                error=error,
            )
        )
    return RemapPlan(
        db_path,
        map_path,
        source_repo,
        source_ref,
        source_commit,
        digest,
        tuple(baselines),
        tuple(blockers),
        tuple(incomplete_operations),
        close_interrupted,
    )


def inspect_remap(
    db_path: Path, map_path: Path, source_repo: Path, source_ref: str = "dev",
    *, close_interrupted: bool = False,
) -> RemapPlan:
    """Строит read-only план; close_interrupted означает решение оператора.

    Статус SQLite не доказывает работу процесса. Явный флаг разрешает включить
    в план завершение этих записей после остановки процессов оператором.
    Во время просмотра ни baseline, ни статусы не меняются.
    """
    db_path, map_path, source_repo = (
        path.expanduser().resolve()
        for path in (db_path, map_path, source_repo)
    )
    with closing(_connect(db_path)) as connection:
        connection.execute("BEGIN")
        return _build_plan(
            connection, db_path, map_path, source_repo, source_ref,
            close_interrupted,
        )


def _backup_database(db_path: Path) -> Path:
    """Создаёт согласованный SQLite backup, включая committed данные WAL.

    Вызывается до первого UPDATE при удержании write reservation другим
    соединением. Отдельное read-only соединение позволяет SQLite backup
    читать исходное состояние без зависания на собственной write transaction.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = db_path.with_name(
        f"{db_path.name}.before-commit-remap-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3"
    )
    with backup.open("xb"):
        pass
    with closing(_connect(db_path)) as source:
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RemapError(
                    f"Резервная копия не прошла quick_check: {backup}."
                )
    return backup


def _close_interrupted_operations(
    connection: sqlite3.Connection,
    operations: tuple[IncompleteOperation, ...],
    finished_at: str,
) -> None:
    """Закрывает только записи проверенного плана внутри общей транзакции.

    Сохраняет ID, старые SHA, payload, логи и предыдущую ошибку. Не помечает
    релиз применённым, не удаляет историю и не останавливает процессы.
    """
    for operation in operations:
        if INCOMPLETE_STATUSES.get(operation.table) != operation.status:
            raise RemapError("Неизвестный вид незавершённой операции.")
        note = (
            "Оператор подтвердил остановку процесса; операция закрыта как "
            "прерванная через remap_commits --close-interrupted "
            f"(прежний статус: {operation.status})."
        )
        previous_error = dict(operation.snapshot)["error"]
        error = f"{previous_error}\n{note}" if previous_error else note
        cursor = connection.execute(
            f"UPDATE {operation.table} "
            "SET status = 'failed', error = ?, finished_at = ? "
            "WHERE id = ? AND status = ?",
            (error, finished_at, operation.id, operation.status),
        )
        if cursor.rowcount != 1:
            raise RemapError(
                f"Не удалось закрыть {operation.table} id={operation.id}."
            )


def apply_remap(plan: RemapPlan) -> Path | None:
    """Переводит baseline одной транзакцией после повторной проверки и backup.

    Никаких Git fetch/checkout, SQL приложения или изменений старых релизов.
    Явный close_interrupted закрывает записи плана как failed в той же
    транзакции. При ошибке и SHA, и статусы откатываются. Повторный запуск без
    изменений не пишет базу и не создаёт лишнюю резервную копию.
    """
    if not plan.valid:
        raise RemapError("План содержит ошибки; ни один baseline не изменён.")
    with closing(_connect(plan.db_path, writable=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = _build_plan(
                connection,
                plan.db_path,
                plan.map_path,
                plan.source_repo,
                plan.source_ref,
                plan.close_interrupted,
            )
            if current != plan:
                raise RemapError(
                    "База, карта или source ref изменились после проверки. "
                    "Повторите предварительный просмотр."
                )
            if not current.changes and not (
                current.close_interrupted and current.incomplete_operations
            ):
                connection.rollback()
                return None
            backup = _backup_database(plan.db_path)
            updated_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            if current.close_interrupted:
                _close_interrupted_operations(
                    connection, current.incomplete_operations, updated_at
                )
            for row in current.changes:
                cursor = connection.execute(
                    "UPDATE contour_state SET last_success_backend_commit = ?, "
                    "updated_at = ? WHERE contour = ? "
                    "AND last_success_backend_commit = ?",
                    (row.new_commit, updated_at, row.contour, row.old_commit),
                )
                if cursor.rowcount != 1:
                    raise RemapError(
                        f"Не удалось обновить baseline {row.contour}."
                    )
            connection.commit()
            return backup
        except BaseException:
            connection.rollback()
            raise
