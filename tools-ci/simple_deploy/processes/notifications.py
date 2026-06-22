"""Вспомогательные функции deploy-уведомлений."""

from __future__ import annotations

import json
from pathlib import Path
import re

from simple_deploy.core.commands import run_command
from simple_deploy.core.email import (
    format_outlook_template,
    normalize_email_list,
)
from simple_deploy.core.env import require_value
from simple_deploy.core.job_logging import job_log
from simple_deploy.release.artifacts import Artifact
from simple_deploy.release.manifest import (
    find_previous_release_manifest,
    load_release_manifest,
    RELEASE_MANIFEST_NAME,
)


def git_log_merge_commits(
    repo_path: str, previous_sha: str, current_sha: str
) -> list[dict[str, str]]:
    """Возвращает merge-коммиты first-parent истории между двумя SHA."""
    result = run_command(
        [
            "git",
            "-C",
            repo_path,
            "log",
            f"{previous_sha}..{current_sha}",
            "--first-parent",
            "--merges",
            "--pretty=format:%H%x1f%s%x1f%b%x1e",
        ],
        timeout=60,
    )
    if result.rc != 0:
        detail = (result.stderr or result.stdout).strip() or f"rc={result.rc}"
        raise RuntimeError(detail)

    commits = []
    for raw_entry in result.stdout.strip("\x1e\n").split("\x1e"):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = entry.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commits.append(
            {
                "sha": parts[0].strip(),
                "subject": parts[1].strip(),
                "body": parts[2].strip(),
            }
        )
    return commits


def merge_request_line(commit: dict[str, str]) -> str | None:
    """Извлекает строку changelog из GitLab merge request footer-а."""
    body = commit["body"]
    mr_match = re.search(r"See merge request\s+(.+?!(\d+))", body)
    if not mr_match:
        return None

    title = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("See merge request"):
            title = stripped
            break
    if not title:
        title = commit["subject"]
    return f"- !{mr_match.group(2)} {title}"


def repo_changelog_text(
    name: str, current_repo: dict, previous_repo: dict
) -> str:
    """Строит changelog репозитория по release manifest metadata."""
    current_sha = str(current_repo.get("commit_sha", "")).strip()
    previous_sha = str(previous_repo.get("commit_sha", "")).strip()
    repo_path = str(current_repo.get("source_repo_path", "")).strip()

    if not current_sha or not previous_sha:
        return (
            f"{name}:\nМетаданные коммитов неполные, "
            "список изменений недоступен."
        )
    if current_sha == previous_sha:
        return f"{name}:\nИзменений нет."
    if not repo_path:
        return (
            f"{name}:\nПуть к source-репозиторию не задан, "
            "список изменений недоступен."
        )

    try:
        commits = git_log_merge_commits(repo_path, previous_sha, current_sha)
    except Exception as exc:
        return (
            f"{name}:\nПРЕДУПРЕЖДЕНИЕ: не удалось построить "
            f"список изменений: {exc}"
        )
    lines = [
        line for commit in commits if (line := merge_request_line(commit))
    ]
    if not lines:
        return (
            f"{name}:\nИзменения есть, но в first-parent истории "
            "не найдены влитые merge request."
        )
    return f"{name}:\n" + "\n".join(lines)


def release_changelog_text(release_dir: Path) -> str:
    """Строит changelog текущего релиза относительно предыдущего manifest-а."""
    current_manifest = load_release_manifest(release_dir)
    if not current_manifest:
        return (
            "Метаданные текущего релиза не найдены, "
            "список изменений недоступен."
        )

    previous = find_previous_release_manifest(release_dir)
    if not previous:
        return (
            "Метаданные предыдущего релиза не найдены, "
            "список изменений недоступен."
        )
    previous_dir, previous_manifest = previous

    current_repos = current_manifest.get("repositories", {})
    previous_repos = previous_manifest.get("repositories", {})
    sections = [
        "Предыдущий релиз: "
        f"{previous_manifest.get('build_version', previous_dir.name)}"
    ]
    repo_names = {"backend": "Backend", "frontend": "Frontend"}
    for repo_key, label in repo_names.items():
        current_repo = current_repos.get(repo_key)
        previous_repo = previous_repos.get(repo_key)
        if not current_repo or not previous_repo:
            sections.append(
                f"{label}:\nМетаданные релиза неполные, "
                "список изменений недоступен."
            )
            continue
        sections.append(
            repo_changelog_text(label, current_repo, previous_repo)
        )
    return "\n\n".join(sections)


def send_outlook_success_email(
    env: dict[str, str],
    runtime: dict,
    build_version: str,
    release_dir: Path,
    artifacts: list[Artifact],
) -> None:
    """Отправляет Outlook-письмо об успешном deploy с manifest attachment."""
    if not runtime.get("outlook_email_enabled", False):
        job_log("SKIP Outlook success email: отключено")
        return

    recipients = normalize_email_list(
        runtime.get("outlook_email_recipients", [])
    )
    if not recipients:
        job_log("SKIP Outlook success email: список получателей пуст")
        return

    cc = normalize_email_list(runtime.get("outlook_email_cc", []))
    artifact_lines = [
        f"- {artifact.name}: {artifact.local_path} -> {artifact.extract_path}"
        for artifact in artifacts
    ]
    try:
        changelog_text = release_changelog_text(release_dir)
    except Exception as exc:
        changelog_text = (
            "ПРЕДУПРЕЖДЕНИЕ: не удалось построить список "
            f"изменений релиза: {exc}"
        )
        job_log(f"WARN release changelog failed: {exc}")
    context = {
        "build_version": build_version,
        "release_dir": str(release_dir),
        "dev_domain": require_value(env, "DEV_DOMAIN"),
        "stand_url": f"https://{require_value(env, 'DEV_DOMAIN')}/",
        "artifacts_text": "\n".join(artifact_lines),
        "release_changelog_text": changelog_text,
    }
    subject = format_outlook_template(
        runtime.get("outlook_email_subject", ""), context
    )
    body = format_outlook_template(
        runtime.get("outlook_email_body", ""), context
    )
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    attachment_paths = [str(manifest_path)] if manifest_path.is_file() else []
    if attachment_paths:
        job_log(f"INFO Outlook success email attachment: {manifest_path}")
    else:
        job_log(
            f"WARN Outlook success email attachment missing: {manifest_path}"
        )
    payload = {
        "to": recipients,
        "cc": cc,
        "subject": subject,
        "body": body,
        "attachments": attachment_paths,
    }
    powershell = """
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$outlook = New-Object -ComObject Outlook.Application
$mail = $outlook.CreateItem(0)
$mail.To = ($payload.to -join ';')
if ($payload.cc -and $payload.cc.Count -gt 0) {
    $mail.CC = ($payload.cc -join ';')
}
$mail.Subject = [string]$payload.subject
$mail.BodyFormat = 2
$encodedBody = [System.Net.WebUtility]::HtmlEncode([string]$payload.body)
$encodedBody = $encodedBody -replace "(`r`n|`n|`r)", "<br>"
$mail.HTMLBody = (
    "<html><body style=""font-family: Arial, sans-serif; " +
    "font-size: 10pt;"">" +
    $encodedBody +
    "</body></html>"
)
if ($payload.attachments) {
    foreach ($attachment in $payload.attachments) {
        if (-not [string]::IsNullOrWhiteSpace([string]$attachment)) {
            [void]$mail.Attachments.Add([string]$attachment)
        }
    }
}
$mail.Send()
Write-Output 'sent'
""".strip()

    job_log(f"RUN Outlook success email: {', '.join(recipients)}")
    result = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            powershell,
        ],
        input_text=json.dumps(payload),
        timeout=60,
    )
    if result.rc == 0:
        job_log("PASS Outlook success email")
        return

    detail = (result.stderr or result.stdout).strip() or f"rc={result.rc}"
    if runtime.get("outlook_email_required", False):
        raise RuntimeError(
            f"Не удалось отправить письмо через Outlook: {detail}"
        )
    job_log(f"WARN Outlook success email failed: {detail}")


__all__ = [
    "git_log_merge_commits",
    "merge_request_line",
    "repo_changelog_text",
    "release_changelog_text",
    "send_outlook_success_email",
]
