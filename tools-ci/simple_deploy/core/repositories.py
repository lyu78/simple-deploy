"""Проверки каталогов source/target перед изменением рабочих копий."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from simple_deploy.core.env import require_value


def require_distinct_repositories(
    source: str, target: str, label: str
) -> None:
    """Запрещает синхронизацию каталога с самим собой, включая ссылки.

    Сравнение не изменяет файлы. На Windows учитывает регистр, разделители,
    относительные пути и junction/symlink через resolve и samefile.
    """
    source_path = Path(source).expanduser().resolve()
    target_path = Path(target).expanduser().resolve()
    same = os.path.normcase(str(source_path)) == os.path.normcase(
        str(target_path)
    )
    if not same and source_path.exists() and target_path.exists():
        same = source_path.samefile(target_path)
    if same:
        raise RuntimeError(
            f"{label}: source и target совпадают ({source_path}). "
            "Синхронизация запрещена: укажите разные рабочие копии."
        )


def validate_build_repository_pairs(env: Mapping[str, str]) -> None:
    """Проверяет обе пары до первой изменяющей операции build."""
    for component in ("BACKEND", "FRONTEND"):
        require_distinct_repositories(
            require_value(env, f"{component}_SOURCE_REPO_PATH"),
            require_value(env, f"{component}_TARGET_REPO_PATH"),
            f"{component}_SOURCE_REPO_PATH / {component}_TARGET_REPO_PATH",
        )
