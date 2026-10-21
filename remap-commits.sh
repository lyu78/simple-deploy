#!/usr/bin/env bash
# Перенос baseline из Git Bash: просмотр по умолчанию, запись только с --apply.
set -euo pipefail

remap_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$remap_root"

remap_python="$remap_root/.venv/Scripts/python.exe"
if [[ ! -f "$remap_python" ]]; then
    printf '%s\n' 'Не найден .venv/Scripts/python.exe. Выполните установку из tools-ci/README.MD.' >&2
    exit 1
fi

exec "$remap_python" -B -Xutf8 -m simple_deploy.cli.remap_commits "$@"
