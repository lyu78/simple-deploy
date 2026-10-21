"""Защита рабочих копий: только временные каталоги и подменённые команды."""

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "tools-ci" / "builder")
)
for contour in ("DEV", "TEST", "PROD"):
    os.environ.setdefault(f"FRONTEND_{contour}_SERVER_NAME", contour.lower())

from simple_deploy.application.requests import BuildRequest
from simple_deploy.core.repositories import require_distinct_repositories
from simple_deploy.processes.build import build
from src.build_backend import build_backend
from src.build_frontend import build_frontend
from src.files import copy_directory_contents, sync_source_top_level_items


@pytest.mark.parametrize(
    "operation", [copy_directory_contents, sync_source_top_level_items]
)
@pytest.mark.parametrize("alias", [".", "child/.."])
def test_copy_to_self_preserves_source(tmp_path, operation, alias):
    source = tmp_path / "source"
    source.mkdir()
    (source / "child").mkdir()
    marker = source / "keep.txt"
    marker.write_bytes(b"source must survive")
    with pytest.raises(RuntimeError, match="source и target совпадают"):
        operation(str(source), str(source / alias))
    assert marker.read_bytes() == b"source must survive"
    assert (source / "child").is_dir()


def test_distinct_directories_are_allowed(tmp_path):
    require_distinct_repositories(
        str(tmp_path / "source"), str(tmp_path / "target"), "test"
    )


@pytest.mark.skipif(os.name != "nt", reason="Регистр путей Windows")
def test_windows_case_alias_is_rejected(tmp_path):
    source = tmp_path / "Source"
    source.mkdir()
    with pytest.raises(RuntimeError, match="совпадают"):
        require_distinct_repositories(str(source), str(source).upper(), "test")


def test_directory_link_is_rejected(tmp_path):
    source = tmp_path / "source"
    alias = tmp_path / "alias"
    source.mkdir()
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(source), str(alias))
        else:
            alias.symlink_to(source, target_is_directory=True)
        with pytest.raises(RuntimeError, match="совпадают"):
            require_distinct_repositories(str(source), str(alias), "test")
    finally:
        if alias.exists():
            if os.name == "nt":
                alias.rmdir()
            else:
                alias.unlink()


@pytest.mark.parametrize("component", ["BACKEND", "FRONTEND"])
def test_build_checks_both_pairs_before_writing_env_or_launching_builder(
    tmp_path, component
):
    env = {
        f"{name}_{role}_REPO_PATH": str(tmp_path / f"{name}-{role}")
        for name in ("BACKEND", "FRONTEND")
        for role in ("SOURCE", "TARGET")
    }
    env[f"{component}_TARGET_REPO_PATH"] = env[f"{component}_SOURCE_REPO_PATH"]
    with (
        patch("simple_deploy.processes.build.load_env", return_value=env),
        patch(
            "simple_deploy.processes.build.prepare_frontend_env_files"
        ) as prepare,
        patch("simple_deploy.processes.build.stream_command") as command,
    ):
        with pytest.raises(RuntimeError, match="совпадают"):
            build(BuildRequest())
    prepare.assert_not_called()
    command.assert_not_called()


@pytest.mark.parametrize(
    "component,operation",
    [("backend", build_backend), ("frontend", build_frontend)],
)
def test_direct_component_build_rejects_self_before_git(
    tmp_path, component, operation
):
    marker = tmp_path / "keep.txt"
    marker.write_bytes(b"unchanged")
    env = {
        f"{component.upper()}_{role}_REPO_PATH": str(tmp_path)
        for role in ("SOURCE", "TARGET")
    }
    with (
        patch.dict(os.environ, env),
        patch(f"src.build_{component}.check_repo") as git,
    ):
        with pytest.raises(RuntimeError, match="совпадают"):
            operation(build_version="1.2.3", branch_name="release/test")
    git.assert_not_called()
    assert marker.read_bytes() == b"unchanged"
