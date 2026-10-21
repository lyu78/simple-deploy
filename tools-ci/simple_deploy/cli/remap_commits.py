"""Отдельная maintenance-команда переноса baseline по commit-map.

По умолчанию выполняется только просмотр со встроенной картой. Source берётся
из tools-ci/.env, SQLite — из штатного пути registry. Явные пути имеют приоритет.
--apply переводит текущие source SHA после backup. Конфигурация, реальная БД
приложения и release artifacts этой командой не изменяются.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import subprocess
import sys

from simple_deploy.core.paths import DEFAULT_ENV_FILE
from simple_deploy.registry.commit_remap import (
    RemapError,
    apply_remap,
    inspect_remap,
)


BUNDLED_COMMIT_MAP = (
    Path(__file__).resolve().parents[1]
    / "registry"
    / "commit_maps"
    / "backend-history-v1.map"
)


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Читает пути текущего runner-а без подключения или создания SQLite.

    Явные --db и --source-repo сохраняют автономный режим без чтения .env.
    Автовыбор базы использует ту же настройку процесса, что web/worker.
    """
    db_path = args.db
    source_repo = args.source_repo
    if db_path is None:
        from simple_deploy.registry.state import default_state_db_path

        db_path = default_state_db_path()
    if source_repo is None:
        from simple_deploy.core.env import load_dotenv_file

        try:
            env = load_dotenv_file(args.env_file, required=True)
        except RuntimeError as exc:
            raise RemapError(str(exc)) from exc
        source_path = env.get("BACKEND_SOURCE_REPO_PATH", "").strip()
        if not source_path:
            raise RemapError(
                f"В {args.env_file} не задан BACKEND_SOURCE_REPO_PATH. "
                "Укажите его или передайте --source-repo."
            )
        source_repo = Path(source_path)
        configured_db = env.get("SIMPLE_DEPLOY_STATE_DB", "").strip()
        if (
            args.db is None
            and configured_db
            and Path(configured_db).expanduser().resolve()
            != db_path.expanduser().resolve()
        ):
            raise RemapError(
                "SIMPLE_DEPLOY_STATE_DB в .env отличается от базы web/worker. "
                "Укажите нужную рабочую базу явно через --db."
            )
    return db_path, source_repo


def main(argv: list[str] | None = None) -> int:
    """Показывает план либо явно применяет перевод baseline с backup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path,
        help="SQLite runner-а; по умолчанию штатный путь web/worker.",
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV_FILE,
        help="Настройки source; по умолчанию tools-ci/.env.",
    )
    parser.add_argument(
        "--commit-map",
        type=Path,
        default=BUNDLED_COMMIT_MAP,
        help="Другая карта git-filter-repo; по умолчанию встроенная.",
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        help="Backend source; по умолчанию BACKEND_SOURCE_REPO_PATH из .env.",
    )
    parser.add_argument(
        "--source-ref", default="dev", help="Ветка сборки; по умолчанию dev."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Только просмотр; режим по умолчанию.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Создать backup и изменить baseline.",
    )
    args = parser.parse_args(argv)
    try:
        db_path, source_repo = _resolve_paths(args)
        plan = inspect_remap(
            db_path, args.commit_map, source_repo, args.source_ref
        )
        print(f"База: {plan.db_path}")
        print(f"Карта: {plan.map_path}; SHA-256: {plan.map_sha256}")
        print(
            f"Source: {plan.source_repo}; {plan.source_ref} = {plan.source_commit}"
        )
        for row in plan.baselines:
            print(f"{row.contour}: release={row.release}; {row.old_commit}")
            if row.error:
                print(f"  ОШИБКА: {row.error}")
            elif row.changed:
                print(f"  -> {row.new_commit}")
            else:
                print("  Уже соответствует новой истории.")
        for blocker in plan.blockers:
            print(f"ОШИБКА: {blocker}")
        if not plan.valid:
            print("Перенос заблокирован. База не изменена.")
            return 1
        print(f"Контуров к изменению: {len(plan.changes)}.")
        if not args.apply:
            print("Предварительный просмотр. Для записи добавьте --apply.")
            return 0
        backup = apply_remap(plan)
        if backup is None:
            print("Изменения не требуются.")
        else:
            print(f"Резервная копия: {backup}")
            print("Baseline переведены. История релизов и manifest сохранены.")
        return 0
    except (
        RemapError,
        OSError,
        UnicodeError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Ошибка переноса baseline: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
