/*
Назначение:
  Информационный отчет по месту, занятому таблицами схемы public в PostgreSQL.

Когда выполнять:
  На машине БД в конце DB-части пайплайна: после применения скриптов схемы
  и миграций данных, но до финального завершения деплоя.

Что показывает:
  - имя таблицы;
  - полный размер в GB, включая таблицу, индексы и TOAST;
  - размер самой таблицы в GB;
  - размер индексов в GB;
  - оценочное количество строк по статистике PostgreSQL.

Важно:
  Скрипт read-only. Количество строк берется из pg_class.reltuples, поэтому
  это оценка, а не точный COUNT(*). Такой подход не сканирует все таблицы
  целиком и подходит для информационного отчета в конце пайплайна.
*/

\pset pager off
\timing on

\echo 'Public schema table size report'
\echo 'Sizes include table, indexes and TOAST. Row count is PostgreSQL estimate.'

SELECT
    format('%I.%I', n.nspname, c.relname) AS table_name,
    round(pg_total_relation_size(c.oid)::numeric / 1024 / 1024 / 1024, 3) AS total_size_gb,
    round(pg_relation_size(c.oid)::numeric / 1024 / 1024 / 1024, 3) AS table_size_gb,
    round(pg_indexes_size(c.oid)::numeric / 1024 / 1024 / 1024, 3) AS indexes_size_gb,
    greatest(c.reltuples::bigint, 0) AS estimated_rows,
    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size_pretty
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
ORDER BY pg_total_relation_size(c.oid) DESC, c.relname;
