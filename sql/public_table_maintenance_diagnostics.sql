/*
Назначение:
  Read-only диагностика таблиц и индексов схемы public после DB-части деплоя.

Когда выполнять:
  На машине БД после информационного отчета public_table_size_report.sql:
  после применения скриптов схемы и миграций данных, но до финального
  завершения деплоя.

Что показывает:
  - таблицы с признаками устаревшей статистики;
  - таблицы с заметным количеством dead tuples;
  - крупные таблицы, для которых нужна ручная проверка bloat;
  - крупные или невалидные индексы, для которых нужна ручная проверка.

Важно:
  Скрипт ничего не меняет в БД. Он не выполняет VACUUM, VACUUM FULL, REINDEX,
  CLUSTER и CREATE EXTENSION. Рекомендации являются сигналом для оператора или
  отдельного явно включенного maintenance-шага.
*/

\pset pager off
\timing on

\echo 'Public schema table maintenance diagnostics'
\echo 'Read-only report. No VACUUM, REINDEX, CLUSTER or CREATE EXTENSION is executed.'
\echo 'Thresholds: 50000 changed/dead rows, 10% changed/dead tuple ratio, 1 GB large table.'

WITH table_stats AS (
    SELECT
        n.nspname,
        c.relname,
        c.oid,
        pg_total_relation_size(c.oid) AS total_bytes,
        greatest(c.reltuples::bigint, 0) AS estimated_rows,
        COALESCE(s.n_live_tup, 0) AS n_live_tup,
        COALESCE(s.n_dead_tup, 0) AS n_dead_tup,
        COALESCE(s.n_mod_since_analyze, 0) AS n_mod_since_analyze,
        s.last_vacuum,
        s.last_autovacuum,
        s.last_analyze,
        s.last_autoanalyze,
        s.vacuum_count,
        s.autovacuum_count,
        s.analyze_count,
        s.autoanalyze_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
),
table_metrics AS (
    SELECT
        *,
        round(total_bytes::numeric / 1024 / 1024 / 1024, 3) AS total_size_gb,
        round(
            100 * n_dead_tup::numeric / NULLIF(n_live_tup + n_dead_tup, 0),
            2
        ) AS dead_tuple_percent,
        round(
            100 * n_mod_since_analyze::numeric / NULLIF(n_live_tup, 0),
            2
        ) AS modified_since_analyze_percent
    FROM table_stats
)
SELECT
    format('%I.%I', nspname, relname) AS table_name,
    total_size_gb,
    estimated_rows,
    n_live_tup,
    n_dead_tup,
    COALESCE(dead_tuple_percent, 0) AS dead_tuple_percent,
    n_mod_since_analyze,
    COALESCE(modified_since_analyze_percent, 0) AS modified_since_analyze_percent,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    CASE
        WHEN n_dead_tup >= 50000
             AND COALESCE(dead_tuple_percent, 0) >= 10
            THEN 'VACUUM_ANALYZE_RECOMMENDED'
        WHEN total_bytes > 0
             AND last_analyze IS NULL
             AND last_autoanalyze IS NULL
            THEN 'ANALYZE_RECOMMENDED'
        WHEN n_mod_since_analyze >= GREATEST(50000, (n_live_tup * 0.10)::bigint)
             AND n_mod_since_analyze > 0
            THEN 'ANALYZE_RECOMMENDED'
        WHEN total_bytes >= 1024::bigint * 1024 * 1024 * 1024
             AND n_dead_tup > 0
            THEN 'MANUAL_BLOAT_REVIEW'
        ELSE 'OK'
    END AS maintenance_recommendation
FROM table_metrics
ORDER BY
    CASE
        WHEN n_dead_tup >= 50000
             AND COALESCE(dead_tuple_percent, 0) >= 10
            THEN 1
        WHEN total_bytes > 0
             AND last_analyze IS NULL
             AND last_autoanalyze IS NULL
            THEN 2
        WHEN n_mod_since_analyze >= GREATEST(50000, (n_live_tup * 0.10)::bigint)
             AND n_mod_since_analyze > 0
            THEN 3
        WHEN total_bytes >= 1024::bigint * 1024 * 1024 * 1024
             AND n_dead_tup > 0
            THEN 4
        ELSE 5
    END,
    total_bytes DESC,
    relname;

\echo 'Public schema index diagnostics'

SELECT
    format('%I.%I', s.schemaname, s.relname) AS table_name,
    format('%I.%I', s.schemaname, s.indexrelname) AS index_name,
    round(pg_relation_size(s.indexrelid)::numeric / 1024 / 1024 / 1024, 3) AS index_size_gb,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    i.indisvalid,
    i.indisready,
    CASE
        WHEN NOT i.indisvalid OR NOT i.indisready
            THEN 'REINDEX_REVIEW'
        WHEN pg_relation_size(s.indexrelid) >= 1024::bigint * 1024 * 1024 * 1024
             AND s.idx_scan = 0
            THEN 'UNUSED_LARGE_INDEX_REVIEW'
        ELSE 'OK'
    END AS index_recommendation
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.schemaname = 'public'
ORDER BY
    CASE
        WHEN NOT i.indisvalid OR NOT i.indisready THEN 1
        WHEN pg_relation_size(s.indexrelid) >= 1024::bigint * 1024 * 1024 * 1024
             AND s.idx_scan = 0 THEN 2
        ELSE 3
    END,
    pg_relation_size(s.indexrelid) DESC,
    s.indexrelname;

\echo 'Optional bloat diagnostics with pgstattuple_approx'

SELECT CASE
    WHEN to_regprocedure('pgstattuple_approx(regclass)') IS NOT NULL
        THEN 'true'
    ELSE 'false'
END AS has_pgstattuple_approx
\gset

\if :has_pgstattuple_approx
WITH largest_tables AS (
    SELECT
        c.oid,
        format('%I.%I', n.nspname, c.relname) AS table_name,
        pg_total_relation_size(c.oid) AS total_bytes
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
    ORDER BY pg_total_relation_size(c.oid) DESC
    LIMIT 20
)
SELECT
    t.table_name,
    round(t.total_bytes::numeric / 1024 / 1024 / 1024, 3) AS total_size_gb,
    round(st.scanned_percent::numeric, 2) AS scanned_percent,
    round(st.dead_tuple_percent::numeric, 2) AS dead_tuple_percent,
    round(st.approx_free_percent::numeric, 2) AS approx_free_percent,
    round(
        (st.dead_tuple_len + st.approx_free_space)::numeric / 1024 / 1024 / 1024,
        3
    ) AS approx_reclaimable_gb,
    CASE
        WHEN (st.dead_tuple_len + st.approx_free_space) >= 5::bigint * 1024 * 1024 * 1024
             AND (st.dead_tuple_percent + st.approx_free_percent) >= 30
            THEN 'MANUAL_VACUUM_FULL_REVIEW'
        WHEN (st.dead_tuple_len + st.approx_free_space) >= 1024::bigint * 1024 * 1024 * 1024
             AND (st.dead_tuple_percent + st.approx_free_percent) >= 20
            THEN 'MANUAL_BLOAT_REVIEW'
        ELSE 'OK'
    END AS bloat_recommendation
FROM largest_tables t
CROSS JOIN LATERAL pgstattuple_approx(t.oid::regclass) st
ORDER BY
    (st.dead_tuple_len + st.approx_free_space) DESC,
    t.total_bytes DESC,
    t.table_name;
\else
\echo 'pgstattuple_approx is not available; skipping optional bloat diagnostics.'
\endif
