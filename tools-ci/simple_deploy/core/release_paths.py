"""Резолвинг локальной директории выбранного релиза."""

from __future__ import annotations

from pathlib import Path

from simple_deploy.core.env import windows_release_root


def resolve_release_dir(env: dict[str, str], build_version: str, latest: bool) -> tuple[str, Path]:
    """Возвращает build version и директорию релиза по явной версии или latest."""

    release_root = windows_release_root(env)
    print(f"RESOLVE release root: {release_root}", flush=True)
    if latest:
        dirs = [path for path in release_root.iterdir() if path.is_dir()] if release_root.exists() else []
        if not dirs:
            raise RuntimeError(f"В {release_root} не найдены директории релизов")
        selected = max(dirs, key=lambda path: path.stat().st_mtime)
        print(f"RESOLVE latest release: {selected.name} ({selected})", flush=True)
        return selected.name, selected
    if not build_version:
        raise RuntimeError("Укажите --build-version или --latest")
    selected = release_root / build_version
    print(f"RESOLVE requested release: {selected.name} ({selected})", flush=True)
    return build_version, selected


__all__ = ["resolve_release_dir"]
