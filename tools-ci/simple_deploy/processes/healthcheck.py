"""Вспомогательные HTTP healthcheck-функции для deploy."""

from __future__ import annotations

from html.parser import HTMLParser
import re
import ssl
import time
from urllib import error, parse, request

from simple_deploy.core.commands import decode_subprocess_output, run_or_raise
from simple_deploy.core.env import require_value
from simple_deploy.core.job_logging import job_log
from simple_deploy.core.paths import DEFAULT_TIMEOUT
from simple_deploy.core.ssh import ssh_command


class ScriptSrcParser(HTMLParser):
    """Собирает src-атрибуты script-тегов из HTML страницы портала."""

    def __init__(self) -> None:
        """Инициализирует список найденных script src."""
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Сохраняет src для каждого script-тега."""
        if tag.lower() != "script":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.srcs.append(value)


def read_http_text(url: str, context: ssl.SSLContext | None) -> str:
    """Читает HTTP-ответ как текст с fallback-декодированием."""
    with request.urlopen(
        url, timeout=DEFAULT_TIMEOUT, context=context
    ) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        data = response.read()
    try:
        return data.decode(content_type)
    except (LookupError, UnicodeDecodeError):
        return decode_subprocess_output(data)


def script_urls_from_html(base_url: str, html: str) -> list[str]:
    """Возвращает абсолютные URL script assets с того же origin."""
    parser = ScriptSrcParser()
    parser.feed(html)
    urls = []
    base_origin = parse.urlparse(base_url).netloc
    for src in parser.srcs:
        absolute = parse.urljoin(base_url, src)
        parsed = parse.urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.netloc == base_origin:
            urls.append(absolute)
    return urls


def version_found_in_text(text: str, expected_version: str) -> bool:
    """Проверяет версию с учетом пробелов вокруг разделителей."""
    if expected_version in text:
        return True
    escaped = re.escape(expected_version)
    compact_pattern = escaped.replace(r"\.", r"\s*\.\s*").replace(
        r"\-", r"\s*-\s*"
    )
    return re.search(compact_pattern, text) is not None


def check_portal_release_version(
    env: dict[str, str], runtime: dict, expected_version: str
) -> None:
    """Проверяет, что версия видна в HTML или React assets."""
    if not runtime.get("portal_version_check_enabled", True):
        job_log("SKIP portal version check: disabled")
        return
    if not expected_version:
        job_log("SKIP portal version check: build version unknown")
        return

    validate = bool(runtime.get("healthcheck_validate_certs", False))
    context = None if validate else ssl._create_unverified_context()
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    job_log(f"RUN portal version check: {url} expected={expected_version}")

    html = read_http_text(url, context)
    if version_found_in_text(html, expected_version):
        job_log(f"PASS portal version check: found {expected_version} in HTML")
        return

    asset_limit = int(runtime.get("portal_version_asset_limit", 20))
    script_urls = script_urls_from_html(url, html)[:asset_limit]
    job_log(
        f"RUN portal version check: scanning {len(script_urls)} React assets"
    )
    for asset_url in script_urls:
        try:
            asset_text = read_http_text(asset_url, context)
        except Exception as exc:
            job_log(f"SKIP portal asset {asset_url}: {exc}")
            continue
        if version_found_in_text(asset_text, expected_version):
            job_log(
                f"PASS portal version check: found {expected_version} "
                f"in {asset_url}"
            )
            return

    raise RuntimeError(
        f"portal version check failed: {expected_version} not found "
        "in HTML or React assets"
    )


def verify_maintenance_stub_http(env: dict[str, str], runtime: dict) -> None:
    """Проверяет по HTTP, что maintenance stub отдает ожидаемый маркер."""
    if not runtime.get("maintenance_stub_verify_enabled", True):
        job_log("SKIP maintenance stub HTTP check: disabled")
        return

    marker = str(runtime.get("maintenance_stub_verify_marker", "")).strip()
    if not marker:
        raise RuntimeError("maintenance stub HTTP check marker is empty")

    retries = int(runtime.get("maintenance_stub_verify_retries", 10))
    delay = int(runtime.get("maintenance_stub_verify_delay", 2))
    validate = bool(runtime.get("healthcheck_validate_certs", False))
    context = None if validate else ssl._create_unverified_context()
    base_url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    last_error = ""

    job_log(
        f"RUN maintenance stub HTTP check: {base_url} marker={marker!r} "
        f"(retries={retries}, delay={delay}s)"
    )
    for attempt in range(1, retries + 1):
        url = (
            base_url
            + f"?simple_deploy_maintenance_check={int(time.time())}_{attempt}"
        )
        job_log(f"RUN maintenance stub HTTP check attempt {attempt}/{retries}")
        try:
            html = read_http_text(url, context)
            if marker in html:
                job_log("PASS maintenance stub HTTP check: marker found")
                return
            preview = re.sub(r"\s+", " ", html).strip()[:300]
            last_error = f"marker not found; response preview: {preview}"
        except error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(delay)

    raise RuntimeError(f"maintenance stub HTTP check failed: {last_error}")


def healthcheck(
    env: dict[str, str], runtime: dict, expected_version: str = ""
) -> None:
    """Выполняет HTTP, version check и удаленные healthcheck-команды."""
    retries = int(runtime.get("healthcheck_retries", 30))
    delay = int(runtime.get("healthcheck_delay", 5))
    validate = bool(runtime.get("healthcheck_validate_certs", False))
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    context = None if validate else ssl._create_unverified_context()
    last_error = ""
    job_log(
        f"RUN healthcheck HTTP: {url} (retries={retries}, delay={delay}s)",
    )
    for attempt in range(1, retries + 1):
        job_log(f"RUN healthcheck attempt {attempt}/{retries}")
        try:
            with request.urlopen(
                url, timeout=DEFAULT_TIMEOUT, context=context
            ) as response:
                if response.status in {200, 302, 401, 403}:
                    job_log(f"PASS healthcheck HTTP {response.status}")
                    break
                last_error = f"HTTP {response.status}"
        except error.HTTPError as exc:
            if exc.code in {200, 302, 401, 403}:
                job_log(f"PASS healthcheck HTTP {exc.code}")
                break
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(delay)
    else:
        raise RuntimeError(f"healthcheck failed: {last_error}")

    check_portal_release_version(env, runtime, expected_version)

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    for command in runtime.get("healthcheck_commands", []):
        job_log(f"RUN healthcheck command: {command}")
        run_or_raise(
            f"healthcheck command: {command}",
            ssh_command(env, app_user, app_host, command, "APP", timeout=120),
        )


__all__ = [
    "ScriptSrcParser",
    "read_http_text",
    "script_urls_from_html",
    "version_found_in_text",
    "check_portal_release_version",
    "verify_maintenance_stub_http",
    "healthcheck",
]
