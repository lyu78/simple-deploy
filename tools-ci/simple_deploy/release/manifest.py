"""Примитивы переносимого ``release_manifest.json``.

Manifest описывает конкретный собранный релиз: версию, время создания,
исходные backend/frontend репозитории и список артефактов. Он переносится
вместе с директорией релиза и дополняет локальную SQLite-базу, но не заменяет
ее: SQLite хранит операционное состояние контуров, а manifest описывает
содержимое одного артефакта релиза.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

RELEASE_MANIFEST_NAME = "release_manifest.json"


def build_release_manifest(
    build_version: str,
    backend_repo: dict[str, str],
    frontend_repo: dict[str, str],
    backend_artifacts: dict[str, object] | None = None,
) -> dict:
    """Формирует структуру ``release_manifest.json`` в памяти.

    Функция принимает уже собранные метаданные backend/frontend репозиториев и
    backend-артефактов. Она не читает Git и не пишет файл: вызывающий код
    отвечает за получение метаданных и последующую запись manifest в директорию
    релиза.
    """
    return {
        "build_version": build_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "repositories": {
            "backend": backend_repo,
            "frontend": frontend_repo,
        },
        "artifacts": {
            "backend_db": backend_artifacts or {},
        },
    }


def write_release_manifest_file(release_dir: Path, manifest: dict) -> Path:
    """Записывает manifest в директорию релиза.

    Функция создает директорию релиза при необходимости и сохраняет JSON в
    ``release_manifest.json`` с UTF-8 и стабильным переносом строки в конце.
    Она не обновляет SQLite-состояние: фиксация успешной сборки выполняется
    отдельным вызовом ``registry.commands``.
    """
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_release_manifest(release_dir: Path) -> dict | None:
    """Читает manifest из директории релиза, если он существует.

    Возвращает ``None`` при отсутствии файла, чтобы вызывающий код мог отличить
    "релиз без manifest" от поврежденного JSON. Ошибки чтения или парсинга не
    подавляются, потому что такой manifest нельзя считать надежным источником
    метаданных релиза.
    """
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def release_backend_commit(release_dir: Path) -> str:
    """
    Возвращает backend commit из manifest релиза.

    Функция используется командами mark/deploy для записи результата в
    registry. Она только читает переносимый manifest и не двигает baseline
    сама; изменение baseline выполняет ``registry.commands`` после успешного
    применения релиза.

    """
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest = load_release_manifest(release_dir)
    if not manifest:
        raise RuntimeError(f"Release manifest not found: {manifest_path}")
    commit = str(
        manifest.get("repositories", {})
        .get("backend", {})
        .get("commit_sha", "")
    ).strip()
    if not commit:
        raise RuntimeError(
            "Backend commit is missing in release manifest: "
            f"{manifest_path}"
        )
    return commit


def find_previous_release_manifest(
    release_dir: Path,
) -> tuple[Path, dict] | None:
    """Ищет предыдущий релиз с manifest рядом с текущей директорией релиза.

    Поиск идет по соседним директориям в release root и выбирает самый свежий
    кандидат по времени модификации. Функция best-effort: если предыдущий
    manifest отсутствует, она возвращает ``None`` и оставляет вызывающему коду
    право показать changelog как недоступный.
    """
    release_root = release_dir.parent
    if not release_root.exists():
        return None
    candidates = [
        path
        for path in release_root.iterdir()
        if path.is_dir()
        and path.resolve() != release_dir.resolve()
        and (path / RELEASE_MANIFEST_NAME).exists()
    ]
    for candidate in sorted(
        candidates, key=lambda path: path.stat().st_mtime, reverse=True
    ):
        manifest = load_release_manifest(candidate)
        if manifest:
            return candidate, manifest
    return None


__all__ = [
    "RELEASE_MANIFEST_NAME",
    "build_release_manifest",
    "find_previous_release_manifest",
    "load_release_manifest",
    "release_backend_commit",
    "write_release_manifest_file",
]
