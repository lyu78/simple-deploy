#!/usr/bin/env python3
"""
Генератор run_all_insert.sql и run_all_update.sql для миграций БД.

================================================================================
ЗАПУСК:
    cd /path/to/project/root
    python build_scripts/create_run_all_sql.py

    Где build_scripts/create_run_all_sql.py - путь к этому скрипту.
    Скрипт должен лежать во временной поддиректории build_scripts/ относительно корня проекта.

================================================================================
НАЗНАЧЕНИЕ:
    Автоматически собирает все SQL скрипты из директорий миграций в два итоговых
    файла: run_all_insert.sql и run_all_update.sql с хэшем коммита в имени.
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
    │   └── run_all_update_<hash>.sql       # генерируется

================================================================================
ПРАВИЛА РАСПРЕДЕЛЕНИЯ СКРИПТОВ:
    - INSERT: скрипты из insert_* директорий + все скрипты из INSERT_DIRS
    - UPDATE: все остальные скрипты (update/, set_default/, прочие)

================================================================================
ПРОВЕРКА ИДЕМПОТЕНТНОСТИ (только для INSERT):
    Скрипт проверяет наличие в INSERT скриптах одной из конструкций:
        - ON CONFLICT (id) DO UPDATE SET
        - TRUNCATE TABLE ... RESTART IDENTITY
        - MERGE (PostgreSQL 15+)
    
    Если конструкция не найдена, выводится ERROR, но выполнение продолжается.
    В конце выводится список всех проблемных файлов, чтобы поправить их все сразу.
    
    Идемпотентность означает, что скрипт можно запускать многократно без ошибок
    и дублирования данных.

================================================================================
РЕЗУЛЬТИРУЮЩИЕ ФАЙЛЫ:
    run_all_insert_<hash>.sql:
        - ON_ERROR_STOP = 1  (при ошибке -> останов и откат)
        - Только INSERT скрипты, проверенные на идемпотентность
        
    run_all_update_<hash>.sql:
        - ON_ERROR_STOP = 0  (ошибки логируются, выполнение продолжается)
        - Все UPDATE/DELETE/прочие скрипты

================================================================================
ВЫПОЛНЕНИЕ МИГРАЦИЙ:
    # 1. Сначала INSERT миграции (критично, падать при ошибке)
    psql -U username -d database_name -1 -c "SET synchronous_commit = OFF;" -f run_all_insert_<hash>.sql -c "SET synchronous_commit = ON;"

    # 2. Потом UPDATE миграции (некритично, продолжать при ошибках)
    psql -U username -d database_name -1 -c "SET synchronous_commit = OFF;" -f run_all_update_<hash>.sql -c "SET synchronous_commit = ON;"

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
    ✅ Generated: run_all_update_a1b2c3d.sql (ON_ERROR_STOP=0)
    
    ✅ All INSERT scripts are idempotent. Ready to run.

================================================================================
АВТОР: Generated for database migration automation
ДАТА: 2026
"""

import os
import sys
import subprocess

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
OUTPUT_UPDATE = os.path.join(SCRIPT_DIR, f"run_all_update_{COMMIT_HASH}.sql")

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

# Директории, где ВСЕ скрипты идут в INSERT
INSERT_DIRS = ["app_ip_subcompany_catalogs"]

# Директории, где есть поддиректории insert_* (их содержимое в INSERT, остальное в UPDATE)
MIXED_DIRS = [
    "app_ip_subcompany",
    "app_ip_subcompany_cc",
    "app_ip_subcompany_onna",
    "app_ip_subcompany_prw",
]

# Директории, где ВСЕ скрипты идут в UPDATE
UPDATE_DIRS = [
    "app_ip_subcompany_lti",
    "app_ip_subcompany_pnca",
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
    is_insert = 'INSERT INTO' in content
    
    if not is_insert:
        return True
    
    return has_on_conflict or has_truncate or has_merge

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

def write_run_all_preamble(out, on_error_stop):
    out.write(f"-- Commit: {COMMIT_HASH}\n")
    out.write(f"\\set ON_ERROR_STOP {on_error_stop}\n")
    out.write("\\set ECHO all\n")
    out.write("\\timing on\n")
    for setting in PSQL_SESSION_SETTINGS:
        out.write(f"{setting}\n")
    out.write("\n")

def write_run_all_epilogue(out):
    out.write("SET synchronous_commit = ON;\n")

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

    # Генерация UPDATE скрипта
    with open(OUTPUT_UPDATE, "w") as out:
        write_run_all_preamble(out, 0)
        out.write("-- ============================================\n")
        out.write("-- NON-CRITICAL UPDATES (errors logged, continue)\n")
        out.write("-- ============================================\n\n")

        for d in MIXED_DIRS:
            path = os.path.join(SCRIPTS_DIR, d)
            if not os.path.exists(path):
                continue
            out.write(f"-- {d} (update only)\n")
            for root, dirs, files in os.walk(path):
                if "set_default" in root:
                    continue
                if "insert" in root.lower():
                    continue
                for f in files:
                    if f.endswith(".sql"):
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, BASE_DIR)
                        out.write(f"\\i '{rel}'\n")
            out.write("\n")

        for d in UPDATE_DIRS:
            path = os.path.join(SCRIPTS_DIR, d)
            if not os.path.exists(path):
                continue
            out.write(f"-- {d}\n")
            for sql in find_sql_files(path, errors_list=errors):
                out.write(f"\\i '{sql}'\n")
            out.write("\n")

        write_run_all_epilogue(out)

    print(f"✅ Generated: {os.path.basename(OUTPUT_UPDATE)} (ON_ERROR_STOP=0)")

    # Вывод результата проверки идемпотентности
    if errors:
        print(f"\n❌ Found {len(errors)} non-idempotent INSERT script(s). Please fix them before running.")
        print("   " + "\n    ".join(errors))
        sys.exit(1)
    else:
        print("\n✅ All INSERT scripts are idempotent. Ready to run.")

if __name__ == "__main__":
    main()
