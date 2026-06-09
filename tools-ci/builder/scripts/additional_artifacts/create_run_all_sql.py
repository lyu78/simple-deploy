#!/usr/bin/env python3
"""
Генератор run_all_insert.sql и metadata-based update runner-ов для миграций БД.

================================================================================
ЗАПУСК:
    cd /path/to/project/root
    python build_scripts/create_run_all_sql.py

    Где build_scripts/create_run_all_sql.py - путь к этому скрипту.
    Скрипт должен лежать во временной поддиректории build_scripts/ относительно корня проекта.

================================================================================
НАЗНАЧЕНИЕ:
    Автоматически собирает SQL скрипты из директорий миграций в итоговые
    файлы run_all_insert.sql, run_all_update_sequential.sql
    и run_all_update_parallel.sh с хэшем коммита в имени.
    INSERT скрипты проверяются на идемпотентность.

================================================================================
СТРУКТУРА ДИРЕКТОРИЙ:
    project_root/ (корень проекта, откуда запускается скрипт)
    ├── build_scripts/
    │   └── create_run_all_sql.py          # этот скрипт
    ├── docs/database/scripts/
    │   ├── app_ip_subcompany_catalogs/     # только INSERT (каталоги)
    │   ├── app_ip_subcompany/              # insert_* -> INSERT, остальное -> UPDATE
    │   ├── app_ip_subcompany_cc/           # insert_* -> INSERT, остальное -> UPDATE
    │   ├── app_ip_subcompany_onna/         # insert_* -> INSERT, остальное -> UPDATE
    │   ├── app_ip_subcompany_prw/          # insert_* -> INSERT, остальное -> UPDATE
    │   ├── app_ip_subcompany_lti/          # всё -> UPDATE
    │   └── app_ip_subcompany_pnca/         # всё -> UPDATE
    │   ├── run_all_insert_<hash>.sql       # генерируется
    │   ├── run_all_update_sequential_<hash>.sql # генерируется
    │   └── run_all_update_parallel_<hash>.sh    # генерируется

================================================================================
ПРАВИЛА РАСПРЕДЕЛЕНИЯ СКРИПТОВ:
    - INSERT: скрипты из insert_* директорий + все скрипты из INSERT_DIRS
    - UPDATE: только kind=update и kind=set_default по simple-deploy metadata

================================================================================
ПРОВЕРКА ИДЕМПОТЕНТНОСТИ (только для INSERT):
    Скрипт проверяет наличие в INSERT скриптах одной из конструкций:
        - ON CONFLICT (id) DO UPDATE SET
        - TRUNCATE TABLE ... RESTART IDENTITY
        - MERGE (PostgreSQL 15+)
        - DROP ... (script explicitly resets an owned object before INSERT)
    
    Если конструкция не найдена, выводится ERROR, но выполнение продолжается.
    В конце выводится список всех проблемных файлов, чтобы поправить их все сразу.
    
    Идемпотентность означает, что скрипт можно запускать многократно без ошибок
    и дублирования данных.

================================================================================
РЕЗУЛЬТИРУЮЩИЕ ФАЙЛЫ:
    run_all_insert_<hash>.sql:
        - ON_ERROR_STOP = 1  (при ошибке -> останов и откат)
        - Только INSERT скрипты, проверенные на идемпотентность
        
    run_all_update_sequential_<hash>.sql:
        - ON_ERROR_STOP = 1  (аварийный строгий fallback)
        - Только kind=update и kind=set_default по simple-deploy metadata

    run_all_update_parallel_<hash>.sh:
        - Волновый runner для kind=update и kind=set_default
        - Печатает live-status и timing в терминал, psql output пишет в logs/

================================================================================
ВЫПОЛНЕНИЕ МИГРАЦИЙ:
    # 1. Сначала INSERT миграции (критично, падать при ошибке)
    psql -U username -d database_name -1 -c "SET synchronous_commit = OFF;" -f run_all_insert_<hash>.sql -c "SET synchronous_commit = ON;"

    # Аварийный fallback для одной DB-сессии/одного ядра
    psql -U username -d database_name -1 -c "SET synchronous_commit = OFF;" -f run_all_update_sequential_<hash>.sql -c "SET synchronous_commit = ON;"

    # Целевой параллельный runner для update/set_default
    PGHOST=host PGPORT=5432 PGUSER=username PGDATABASE=database_name PGPASSWORD=password ./run_all_update_parallel_<hash>.sh

================================================================================
ПРИМЕР ИДЕМПОТЕНТНОГО INSERT:
    -- Правильно (с ON CONFLICT)
    INSERT INTO table (id, name) VALUES (1, 'test')
    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;
    
    -- Правильно (с TRUNCATE для небольших справочников)
    TRUNCATE TABLE table RESTART IDENTITY;
    INSERT INTO table (id, name) VALUES (1, 'test');
    
    -- Неправильно (вызовет ошибку при повторном запуске)
    INSERT INTO table (id, name) VALUES (1, 'test');

================================================================================
ПРИМЕР ВЫВОДА:
    🔍 Checking INSERT scripts for idempotency...
    
    ✅ Generated: run_all_insert_a1b2c3d.sql (ON_ERROR_STOP=1)
    ✅ Generated: run_all_update_sequential_a1b2c3d.sql (ON_ERROR_STOP=1)
    ✅ Generated: run_all_update_parallel_a1b2c3d.sh (wave runner, max_workers=8)
    
    ✅ All INSERT scripts are idempotent. Ready to run.

================================================================================
АВТОР: Generated for database migration automation
ДАТА: 2026
"""

import os
import sys
import subprocess
import re
import shlex

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

# Скрипт лежит во временной build_scripts/, поднимаемся на уровень выше до корня проекта.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
SCRIPTS_DIR = os.path.join(BASE_DIR, "docs", "database", "scripts")

# Получаем хэш коммита
def get_commit_hash():
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"

COMMIT_HASH = get_commit_hash()

OUTPUT_INSERT = os.path.join(SCRIPT_DIR, f"run_all_insert_{COMMIT_HASH}.sql")
OUTPUT_UPDATE_SEQUENTIAL = os.path.join(SCRIPT_DIR, f"run_all_update_sequential_{COMMIT_HASH}.sql")
OUTPUT_UPDATE_PARALLEL = os.path.join(SCRIPT_DIR, f"run_all_update_parallel_{COMMIT_HASH}.sh")

PSQL_SESSION_SETTINGS = [
    "SET synchronous_commit = OFF;",
    "SET max_parallel_workers_per_gather = 16;",
    "SET work_mem = '256MB';",
    "SET maintenance_work_mem = '3GB';",
    "SET parallel_setup_cost = 0;",
    "SET parallel_tuple_cost = 0;",
    "SET min_parallel_table_scan_size = 0;",
    "SET min_parallel_index_scan_size = 0;",
    "SET parallel_leader_participation = off;",
    "SET enable_parallel_hash = on;",
    "SET enable_partitionwise_aggregate = on;",
    "SET enable_partitionwise_join = on;",
    "SET temp_buffers = '512MB';",
    "SET max_parallel_workers = 16;",
]

PSQL_SEQUENTIAL_SESSION_SETTINGS = [
    "SET synchronous_commit = OFF;",
    "SET work_mem = '256MB';",
    "SET maintenance_work_mem = '3GB';",
    "SET temp_buffers = '512MB';",
]

SIMPLE_DEPLOY_METADATA_RE = re.compile(r"^\s*--\s*simple-deploy:\s*([^=]+?)\s*=\s*(.*?)\s*$")
UPDATE_SEQUENTIAL_KINDS = {"update", "set_default"}

# Директории, где ВСЕ скрипты идут в INSERT
INSERT_DIRS = ["app_ip_subcompany_catalogs"]

# Директории, где есть поддиректории insert_* (их содержимое в INSERT, остальное в UPDATE)
MIXED_DIRS = [
    "app_ip_subcompany",
    "app_ip_subcompany_cc",
    "app_ip_subcompany_onna",
    "app_ip_subcompany_prw",
]

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def check_idempotent(filepath):
    """
    Проверяет, является ли SQL скрипт идемпотентным.
    
    Ищет в содержимом файла ключевые слова:
        - ON CONFLICT
        - TRUNCATE
        - MERGE
        - DROP
    
    Args:
        filepath (str): Путь к SQL файлу
        
    Returns:
        bool: True если скрипт идемпотентен или не является INSERT, иначе False
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read().upper()
    
    has_on_conflict = 'ON CONFLICT' in content
    has_truncate = 'TRUNCATE' in content
    has_merge = 'MERGE' in content
    has_drop = bool(re.search(r'\bDROP\b', content))
    is_insert = 'INSERT INTO' in content
    
    if not is_insert:
        return True
    
    return has_on_conflict or has_truncate or has_merge or has_drop

def find_sql_files(path, include_insert_only=False, check_inserts=False, errors_list=None):
    """
    Рекурсивно находит все .sql файлы в директории.
    
    Args:
        path (str): Путь к директории для поиска
        include_insert_only (bool): Если True, включает только файлы из insert_* директорий
        check_inserts (bool): Если True, проверяет INSERT скрипты на идемпотентность
        errors_list (list): Список для сбора ошибок
        
    Returns:
        list: Список относительных путей к SQL файлам
    """
    files = []
    for root, dirs, files_in_dir in os.walk(path):
        if "set_default" in root:
            continue

        if include_insert_only and "insert" not in root.lower():
            continue

        for f in files_in_dir:
            if f.endswith(".sql"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, BASE_DIR)

                if check_inserts and not check_idempotent(full):
                    msg = f"{rel}"
                    print(f"❌ ERROR: {msg} - NOT IDEMPOTENT")
                    if errors_list is not None:
                        errors_list.append(msg)

                files.append(rel)
    files.sort()
    return files

def parse_simple_deploy_metadata(filepath):
    metadata = {}
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            match = SIMPLE_DEPLOY_METADATA_RE.match(line)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            metadata[key] = value
    return metadata

def is_insert_new_objects_path(filepath):
    try:
        relative_path = os.path.relpath(filepath, SCRIPTS_DIR)
    except ValueError:
        relative_path = filepath
    return "insert_new_objects" in relative_path.replace("\\", "/").split("/")

def _metadata_order(metadata, rel):
    order_text = metadata.get("order")
    if order_text is None:
        raise RuntimeError(f"Missing simple-deploy order in {rel}")
    try:
        return int(order_text)
    except ValueError as exc:
        raise RuntimeError(f"Invalid simple-deploy order in {rel}: {order_text}") from exc

def _metadata_parallel(metadata, rel):
    parallel = metadata.get("parallel", "").lower()
    if parallel not in {"true", "false"}:
        raise RuntimeError(f"Missing or invalid simple-deploy parallel in {rel}: {metadata.get('parallel')}")
    return parallel

def to_archive_path(path):
    return path.replace("\\", "/")

def find_metadata_sql_entries(kinds):
    expected_kinds = {kind.lower() for kind in kinds}
    entries = []

    for root, dirs, files_in_dir in os.walk(SCRIPTS_DIR):
        dirs[:] = [d for d in dirs if d != "insert_new_objects"]

        for f in files_in_dir:
            if not f.endswith(".sql"):
                continue

            full = os.path.join(root, f)
            if is_insert_new_objects_path(full):
                continue

            metadata = parse_simple_deploy_metadata(full)
            kind = metadata.get("kind", "").lower()
            if kind not in expected_kinds:
                continue

            rel = os.path.relpath(full, BASE_DIR)
            group = metadata.get("group")
            if not group:
                raise RuntimeError(f"Missing simple-deploy group in {rel}")

            archive_path = to_archive_path(rel)
            entries.append(
                {
                    "order": _metadata_order(metadata, rel),
                    "group": group,
                    "parallel": _metadata_parallel(metadata, rel),
                    "path": rel,
                    "archive_path": archive_path,
                }
            )

    return sorted(entries, key=lambda entry: (entry["order"], entry["group"], entry["archive_path"]))

def find_metadata_sql_files(kinds):
    return [entry["path"] for entry in find_metadata_sql_entries(kinds)]

def write_run_all_preamble(out, on_error_stop, session_settings=None):
    out.write(f"-- Commit: {COMMIT_HASH}\n")
    out.write(f"\\set ON_ERROR_STOP {on_error_stop}\n")
    out.write("\\set ECHO all\n")
    out.write("\\timing on\n")
    for setting in session_settings or PSQL_SESSION_SETTINGS:
        out.write(f"{setting}\n")
    out.write("\n")

def write_run_all_epilogue(out):
    out.write("SET synchronous_commit = ON;\n")

UPDATE_PARALLEL_RUNNER_TEMPLATE = r'''#!/usr/bin/env bash
set -uo pipefail

COMMIT_HASH=__COMMIT_HASH__
DEFAULT_MAX_WORKERS=8
DEFAULT_STATUS_INTERVAL_SECONDS=30

__INCLUDE_COMMENTS__
__TASK_ARRAYS__
__PSQL_SESSION_ARGS__

PSQL_BIN="${PSQL_BIN:-psql}"
MAX_WORKERS="${SIMPLE_DEPLOY_UPDATE_MAX_WORKERS:-$DEFAULT_MAX_WORKERS}"
STATUS_INTERVAL="${SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS:-$DEFAULT_STATUS_INTERVAL_SECONDS}"
VERBOSE="${SIMPLE_DEPLOY_UPDATE_VERBOSE:-0}"

RUNNING_PIDS=()
RUNNING_TASK_IDS=()
declare -A TASK_LOG_PATHS
OK_COUNT=0
FAILED_COUNT=0
FAILURE=0
CURRENT_WAVE=""
CURRENT_WAVE_START=0
CURRENT_WAVE_TOTAL=0
CURRENT_WAVE_LAUNCHED=0
WAVE_OK_START=0
WAVE_FAILED_START=0
LAST_STATUS_TS=0

is_positive_int() {
  [[ "${1:-}" =~ ^[1-9][0-9]*$ ]]
}

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

now_epoch() {
  date +%s
}

die() {
  echo "[ERROR] $*" >&2
  exit 2
}

log_msg() {
  local message="[$(timestamp)] $*"
  echo "$message"
  if [[ -n "${SUMMARY_LOG:-}" ]]; then
    echo "$message" >> "$SUMMARY_LOG"
  fi
}

safe_name() {
  printf '%s' "$1" | sed 's#[/\\]#__#g; s#[^A-Za-z0-9_.-]#_#g'
}

count_wave_scripts() {
  local target_order="$1"
  local count=0
  local order
  for order in "${TASK_ORDERS[@]}"; do
    if [[ "$order" == "$target_order" ]]; then
      count=$((count + 1))
    fi
  done
  echo "$count"
}

count_waves() {
  local count=0
  local previous=""
  local order
  for order in "${TASK_ORDERS[@]}"; do
    if [[ "$order" != "$previous" ]]; then
      count=$((count + 1))
      previous="$order"
    fi
  done
  echo "$count"
}

print_running_status() {
  local force="${1:-0}"
  local active="${#RUNNING_PIDS[@]}"
  if [[ "$active" -eq 0 ]]; then
    return
  fi

  local now
  now="$(now_epoch)"
  if [[ "$force" != "1" && "$((now - LAST_STATUS_TS))" -lt "$STATUS_INTERVAL" ]]; then
    return
  fi
  LAST_STATUS_TS="$now"

  local scripts=""
  local idx
  local script
  for idx in "${RUNNING_TASK_IDS[@]}"; do
    script="${TASK_PATHS[$idx]}"
    if [[ -z "$scripts" ]]; then
      scripts="$script"
    else
      scripts="$scripts; $script"
    fi
  done

  local elapsed=0
  if [[ "$CURRENT_WAVE_START" -gt 0 ]]; then
    elapsed=$((now - CURRENT_WAVE_START))
  fi
  log_msg "[RUNNING] wave=$CURRENT_WAVE active=$active elapsed=${elapsed}s scripts=$scripts"
}

handle_task_result() {
  local idx="$1"
  local rc="$2"
  local start_ts="$3"
  local finish_ts="$4"
  local duration="$5"
  local log_path="$6"
  local order="${TASK_ORDERS[$idx]}"
  local group="${TASK_GROUPS[$idx]}"
  local parallel="${TASK_PARALLEL[$idx]}"
  local script="${TASK_PATHS[$idx]}"
  local status="OK"

  if [[ "$rc" -eq 0 ]]; then
    OK_COUNT=$((OK_COUNT + 1))
  else
    status="FAIL"
    FAILED_COUNT=$((FAILED_COUNT + 1))
    FAILURE=1
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$duration" "$status" "$order" "$group" "$parallel" "$script" >> "$TIMING_LOG"
  log_msg "[$status] order=$order parallel=$parallel group=$group duration=${duration}s exit=$rc script=$script log=$log_path"

  if [[ "$VERBOSE" == "1" ]]; then
    sed 's/^/[PSQL] /' "$log_path" | tee -a "$SUMMARY_LOG"
  elif [[ "$rc" -ne 0 ]]; then
    log_msg "[FAIL-LOG] last 40 lines from $log_path"
    tail -n 40 "$log_path" | sed 's/^/[PSQL] /' | tee -a "$SUMMARY_LOG"
  fi
}

process_finished_jobs() {
  local next_pids=()
  local next_ids=()
  local i
  for i in "${!RUNNING_PIDS[@]}"; do
    local pid="${RUNNING_PIDS[$i]}"
    local idx="${RUNNING_TASK_IDS[$i]}"
    local result_file="$RESULT_DIR/${idx}.result"

    if [[ -f "$result_file" ]]; then
      wait "$pid" >/dev/null 2>&1 || true
      local result_idx rc start_ts finish_ts duration log_path
      IFS='|' read -r result_idx rc start_ts finish_ts duration log_path < "$result_file"
      handle_task_result "$result_idx" "$rc" "$start_ts" "$finish_ts" "$duration" "$log_path"
    else
      next_pids+=("$pid")
      next_ids+=("$idx")
    fi
  done
  RUNNING_PIDS=("${next_pids[@]}")
  RUNNING_TASK_IDS=("${next_ids[@]}")
}

wait_for_slot() {
  process_finished_jobs
  if [[ "$FAILURE" -ne 0 ]]; then
    return 1
  fi

  while [[ "${#RUNNING_PIDS[@]}" -ge "$MAX_WORKERS" ]]; do
    process_finished_jobs
    print_running_status 0
    if [[ "$FAILURE" -ne 0 ]]; then
      return 1
    fi
    if [[ "${#RUNNING_PIDS[@]}" -ge "$MAX_WORKERS" ]]; then
      sleep 1
    fi
  done
  return 0
}

wait_for_all() {
  while [[ "${#RUNNING_PIDS[@]}" -gt 0 ]]; do
    process_finished_jobs
    print_running_status 0
    if [[ "${#RUNNING_PIDS[@]}" -gt 0 ]]; then
      sleep 1
    fi
  done
}

start_task() {
  local idx="$1"
  local order="${TASK_ORDERS[$idx]}"
  local group="${TASK_GROUPS[$idx]}"
  local parallel="${TASK_PARALLEL[$idx]}"
  local script="${TASK_PATHS[$idx]}"
  local safe
  safe="$(safe_name "$script")"
  local log_path="$SCRIPT_LOG_DIR/${idx}_${safe}.log"
  local result_file="$RESULT_DIR/${idx}.result"
  local start_ts
  start_ts="$(now_epoch)"
  TASK_LOG_PATHS["$idx"]="$log_path"

  (
    "$PSQL_BIN" "${PSQL_SESSION_ARGS[@]}" -f "$script" > "$log_path" 2>&1
    rc=$?
    finish_ts="$(now_epoch)"
    duration=$((finish_ts - start_ts))
    printf '%s|%s|%s|%s|%s|%s\n' "$idx" "$rc" "$start_ts" "$finish_ts" "$duration" "$log_path" > "${result_file}.tmp"
    mv "${result_file}.tmp" "$result_file"
    exit "$rc"
  ) &

  local pid="$!"
  RUNNING_PIDS+=("$pid")
  RUNNING_TASK_IDS+=("$idx")
  CURRENT_WAVE_LAUNCHED=$((CURRENT_WAVE_LAUNCHED + 1))
  log_msg "[START] pid=$pid order=$order parallel=$parallel group=$group script=$script log=$log_path"
}

start_wave() {
  CURRENT_WAVE="$1"
  CURRENT_WAVE_START="$(now_epoch)"
  CURRENT_WAVE_TOTAL="$(count_wave_scripts "$CURRENT_WAVE")"
  CURRENT_WAVE_LAUNCHED=0
  WAVE_OK_START="$OK_COUNT"
  WAVE_FAILED_START="$FAILED_COUNT"
  LAST_STATUS_TS="$CURRENT_WAVE_START"
  log_msg "=== WAVE $CURRENT_WAVE start: $CURRENT_WAVE_TOTAL scripts ==="
}

finish_wave() {
  local finish_ts
  finish_ts="$(now_epoch)"
  local duration=$((finish_ts - CURRENT_WAVE_START))
  local wave_ok=$((OK_COUNT - WAVE_OK_START))
  local wave_failed=$((FAILED_COUNT - WAVE_FAILED_START))
  log_msg "=== WAVE $CURRENT_WAVE done: launched=$CURRENT_WAVE_LAUNCHED total=$CURRENT_WAVE_TOTAL ok=$wave_ok failed=$wave_failed duration=${duration}s ==="
}

main() {
  is_positive_int "$MAX_WORKERS" || die "SIMPLE_DEPLOY_UPDATE_MAX_WORKERS must be a positive integer, got: $MAX_WORKERS"
  is_positive_int "$STATUS_INTERVAL" || die "SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS must be a positive integer, got: $STATUS_INTERVAL"
  command -v "$PSQL_BIN" >/dev/null 2>&1 || die "psql executable not found: $PSQL_BIN"

  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$script_dir" || exit 2

  local total_scripts="${#TASK_PATHS[@]}"
  if [[ "$total_scripts" -eq 0 ]]; then
    die "No update scripts were generated for this runner"
  fi

  local script
  for script in "${TASK_PATHS[@]}"; do
    [[ -f "$script" ]] || die "Missing SQL file: $script"
  done

  local run_id
  run_id="$(date '+%Y%m%d_%H%M%S')"
  LOG_ROOT="${SIMPLE_DEPLOY_UPDATE_LOG_DIR:-logs/update_parallel/$run_id}"
  SCRIPT_LOG_DIR="$LOG_ROOT/scripts"
  RESULT_DIR="$LOG_ROOT/results"
  SUMMARY_LOG="$LOG_ROOT/summary.log"
  TIMING_LOG="$LOG_ROOT/script_timings.log"
  mkdir -p "$SCRIPT_LOG_DIR" "$RESULT_DIR"
  : > "$SUMMARY_LOG"
  : > "$TIMING_LOG"

  local wave_count
  wave_count="$(count_waves)"
  local run_start
  run_start="$(now_epoch)"
  log_msg "run_all_update_parallel commit=$COMMIT_HASH max_workers=$MAX_WORKERS status_interval=${STATUS_INTERVAL}s scripts=$total_scripts waves=$wave_count log_root=$LOG_ROOT"

  local idx
  local order
  for idx in "${!TASK_PATHS[@]}"; do
    order="${TASK_ORDERS[$idx]}"
    if [[ "$order" != "$CURRENT_WAVE" ]]; then
      if [[ -n "$CURRENT_WAVE" ]]; then
        wait_for_all
        finish_wave
        if [[ "$FAILURE" -ne 0 ]]; then
          break
        fi
      fi
      start_wave "$order"
    fi

    if [[ "$FAILURE" -ne 0 ]]; then
      break
    fi

    if [[ "${TASK_PARALLEL[$idx]}" == "false" ]]; then
      wait_for_all
      if [[ "$FAILURE" -ne 0 ]]; then
        break
      fi
      start_task "$idx"
      wait_for_all
    else
      wait_for_slot || break
      start_task "$idx"
    fi
  done

  if [[ -n "$CURRENT_WAVE" ]]; then
    wait_for_all
    finish_wave
  fi

  local run_finish
  run_finish="$(now_epoch)"
  local total_duration=$((run_finish - run_start))
  log_msg "Top slow scripts:"
  if [[ -s "$TIMING_LOG" ]]; then
    sort -rn "$TIMING_LOG" | head -10 | while IFS=$'\t' read -r duration status order group parallel script; do
      log_msg "  ${duration}s status=$status order=$order parallel=$parallel group=$group script=$script"
    done
  else
    log_msg "  no completed scripts"
  fi

  if [[ "$FAILED_COUNT" -ne 0 ]]; then
    log_msg "=== UPDATE PARALLEL FAILED: scripts=$total_scripts ok=$OK_COUNT failed=$FAILED_COUNT total_duration=${total_duration}s ==="
    return 1
  fi

  log_msg "=== UPDATE PARALLEL DONE: scripts=$total_scripts ok=$OK_COUNT failed=$FAILED_COUNT total_duration=${total_duration}s ==="
  return 0
}

main "$@"
'''

def _shell_array(name, values):
    lines = [f"{name}=("]
    for value in values:
        lines.append(f"  {shlex.quote(str(value))}")
    lines.append(")")
    return "\n".join(lines)

def _psql_session_args(settings):
    args = ["-v", "ON_ERROR_STOP=1", "-c", "\\timing on"]
    for setting in settings:
        args.extend(["-c", setting])
    return _shell_array("PSQL_SESSION_ARGS", args)

def write_update_parallel_runner(out, entries):
    include_comments = "\n".join(
        f"# simple-deploy-include: {entry['archive_path']}" for entry in entries
    )
    task_arrays = "\n".join(
        [
            _shell_array("TASK_ORDERS", [entry["order"] for entry in entries]),
            _shell_array("TASK_GROUPS", [entry["group"] for entry in entries]),
            _shell_array("TASK_PARALLEL", [entry["parallel"] for entry in entries]),
            _shell_array("TASK_PATHS", [entry["archive_path"] for entry in entries]),
        ]
    )
    runner = (
        UPDATE_PARALLEL_RUNNER_TEMPLATE
        .replace("__COMMIT_HASH__", shlex.quote(COMMIT_HASH))
        .replace("__INCLUDE_COMMENTS__", include_comments)
        .replace("__TASK_ARRAYS__", task_arrays)
        .replace("__PSQL_SESSION_ARGS__", _psql_session_args(PSQL_SEQUENTIAL_SESSION_SETTINGS))
    )
    out.write(runner)

# ============================================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================================

def main():
    print(f"🔍 Commit hash: {COMMIT_HASH}")
    print("🔍 Checking INSERT scripts for idempotency...\n")

    errors = []

    # Генерация INSERT скрипта
    with open(OUTPUT_INSERT, "w") as out:
        write_run_all_preamble(out, 1)
        out.write("-- ============================================\n")
        out.write("-- IDEMPOTENT INSERTS (can be run multiple times)\n")
        out.write("-- ============================================\n\n")

        for d in INSERT_DIRS:
            path = os.path.join(SCRIPTS_DIR, d)
            if not os.path.exists(path):
                continue
            out.write(f"-- {d}\n")
            for sql in find_sql_files(path, check_inserts=True, errors_list=errors):
                out.write(f"\\i '{sql}'\n")
            out.write("\n")

        for d in MIXED_DIRS:
            path = os.path.join(SCRIPTS_DIR, d)
            if not os.path.exists(path):
                continue
            out.write(f"-- {d} (insert only)\n")
            for sql in find_sql_files(path, include_insert_only=True, check_inserts=True, errors_list=errors):
                out.write(f"\\i '{sql}'\n")
            out.write("\n")

        write_run_all_epilogue(out)

    print(f"\n✅ Generated: {os.path.basename(OUTPUT_INSERT)} (ON_ERROR_STOP=1)")

    # Генерация аварийного последовательного UPDATE скрипта
    with open(OUTPUT_UPDATE_SEQUENTIAL, "w") as out:
        write_run_all_preamble(out, 1, PSQL_SEQUENTIAL_SESSION_SETTINGS)
        out.write("-- ============================================\n")
        out.write("-- STRICT SEQUENTIAL UPDATES (emergency fallback, one DB session)\n")
        out.write("-- ============================================\n\n")
        out.write("-- Ordered by simple-deploy metadata: order, group, path\n")
        out.write("-- Includes kind=update and kind=set_default. Excludes inserts and insert_new_objects.\n\n")

        for sql in find_metadata_sql_files(UPDATE_SEQUENTIAL_KINDS):
            out.write(f"\\i '{sql}'\n")

        out.write("\n")
        write_run_all_epilogue(out)

    print(f"✅ Generated: {os.path.basename(OUTPUT_UPDATE_SEQUENTIAL)} (ON_ERROR_STOP=1)")

    # Генерация целевого параллельного UPDATE runner-а с барьерными волнами
    with open(OUTPUT_UPDATE_PARALLEL, "w", newline="\n") as out:
        write_update_parallel_runner(out, find_metadata_sql_entries(UPDATE_SEQUENTIAL_KINDS))
    try:
        os.chmod(OUTPUT_UPDATE_PARALLEL, 0o755)
    except OSError:
        pass

    print(f"✅ Generated: {os.path.basename(OUTPUT_UPDATE_PARALLEL)} (wave runner, max_workers=8)")

    # Вывод результата проверки идемпотентности
    if errors:
        print(f"\n❌ Found {len(errors)} non-idempotent INSERT script(s). Please fix them before running.")
        print("   " + "\n    ".join(errors))
        sys.exit(1)
    else:
        print("\n✅ All INSERT scripts are idempotent. Ready to run.")

if __name__ == "__main__":
    main()
