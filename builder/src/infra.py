from datetime import datetime
import logging

from src.utils import get_required_env, run_command

def get_new_build_version() -> str:
    """Возвращает версию для нового билда."""
    build_version_base = get_required_env("BUILD_VERSION_BASE")
    return f"{build_version_base}.{datetime.now().strftime('%d%m%Y_%H%M')}"

def get_new_branch_name(build_version: str) -> str:
    """Возвращает название для новой ветки."""
    current_time = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    return f"feature/works-sync-{build_version}-{current_time}"


def git_pull(repo_path):
    """Выполняет git pull в указанной директории."""
    logging.info(f"\n--- Выполняю git pull в {repo_path} ---")
    return run_command("git stash && git pull", cwd=repo_path)


def git_checkout_dev(repo_path):
    """Выполняет git checkout dev."""
    logging.info(f"\n--- Выполняю git checkout dev в {repo_path} ---")
    return run_command("git stash && git checkout dev", cwd=repo_path)


def git_checkout_new_branch(repo_path: str, branch_name: str):
    """Создает новую ветку и переключается на нее."""
    logging.info(f"\n--- Создаю новую ветку  {branch_name} в {repo_path} ---")
    return run_command(f"git checkout -b {branch_name}", cwd=repo_path)


def git_add_commit_push(repo_path, commit_message=None):
    """Выполняет git add, commit и push"""
    logging.info(f"\n--- Выполняю git add, commit, push в {repo_path} ---")

    if commit_message is None:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"Sync from repo1 at {current_time}"

    if not run_command("git add .", cwd=repo_path):
        return False

    if not run_command(f'git commit -m "{commit_message}"', cwd=repo_path):
        return False

    if not run_command("git push --set-upstream origin HEAD", cwd=repo_path):
        logging.info("Попытка простого push...")
        if not run_command("git push", cwd=repo_path):
            return False
    return True


def git_npm_i(repo_path):
    """Выполняет npm i."""
    logging.info(f"\n--- Выполняю npm i в {repo_path} ---")
    return run_command("npm i", cwd=repo_path)
