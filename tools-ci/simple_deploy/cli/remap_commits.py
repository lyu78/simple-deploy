"""Отдельная maintenance-команда переноса baseline по commit-map.

По умолчанию выполняется только просмотр. --apply переводит текущие source
SHA в явно указанной SQLite-базе runner-а. Основной CLI, его конфигурация,
реальная БД приложения и release artifacts этой командой не изменяются.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
import subprocess
import sys

from simple_deploy.registry.commit_remap import (
    RemapError,
    apply_remap,
    inspect_remap,
)


def main(argv: list[str] | None = None) -> int:
    """Показывает план либо явно применяет перевод baseline с backup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, required=True, help="SQLite-база рабочего runner-а."
    )
    parser.add_argument(
        "--commit-map",
        type=Path,
        required=True,
        help="Файл git-filter-repo commit-map.",
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        required=True,
        help="Backend source с новой историей.",
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
        plan = inspect_remap(
            args.db, args.commit_map, args.source_repo, args.source_ref
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
