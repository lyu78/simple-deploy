# Manual Data SQL Run

Короткая памятка для ручного запуска data SQL artifacts из собранного release
bundle. Команды выполняются на DB VM после копирования архивов из директории
релиза.

## Подготовка

Очистите рабочую директорию от старых artifacts и logs, затем распакуйте
artifacts в отдельные директории:

```bash
rm -rf /tmp/data-migrations/manual
mkdir -p /tmp/data-migrations/manual/db_insert
mkdir -p /tmp/data-migrations/manual/db_update_parallel

tar -xzf db_insert_r_<release>-c_<commit>.tar.gz \
  -C /tmp/data-migrations/manual/db_insert

tar -xzf db_update_parallel_r_<release>-c_<commit>.tar.gz \
  -C /tmp/data-migrations/manual/db_update_parallel
```

## INSERT

В текущей реализации INSERT запускается не параллельным shell runner-ом, а
строгим `psql` entrypoint:

```bash
cd /tmp/data-migrations/manual/db_insert
touch "$(pwd)/insert.log"
psql -p 10265 -U pgadmin -d application_test \
  -v ON_ERROR_STOP=1 \
  -f "$(ls -1 run_all_insert_*.sql | tail -n 1)" \
  > "$(pwd)/insert.log" 2>&1
```

Ориентир по ранее разобранным данным: обычные insert-скрипты занимали около
`27 секунд`, то есть меньше минуты. Фактическое время смотрите по timestamps
запуска и завершения команды.

## UPDATE Parallel Without Defaults

`run_all_update_parallel_*.sh` можно запускать вручную без применения
`kind=set_default`. Defaults выключены по умолчанию:

```bash
cd /tmp/data-migrations/manual/db_update_parallel
PGPORT=10265 \
PGUSER=pgadmin \
PGDATABASE=application_test \
PSQL_BIN=psql \
SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT=0 \
SIMPLE_DEPLOY_UPDATE_MAX_WORKERS=8 \
SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS=30 \
bash "$(ls -1 run_all_update_parallel_*.sh | tail -n 1)"
```

Ориентир по ранее разобранным данным:

- ручной parallel update с `SIMPLE_DEPLOY_UPDATE_MAX_WORKERS=8` занимал около
  `1 часа`;
- `4 ч 34 мин 20 сек` - это последовательная сумма `57` update-скриптов до
  параллельного запуска, не ожидаемое время parallel runner-а;
- самый долгий отдельный скрипт был около `40 мин`;
- фактическое время зависит от нагрузки DB, блокировок и текущего состава
  SQL-скриптов.

Точное время конкретного ручного запуска смотрите в:

```text
/tmp/data-migrations/manual/db_update_parallel/logs/update_parallel/<run_id>/summary.log
/tmp/data-migrations/manual/db_update_parallel/logs/update_parallel/<run_id>/script_timings.log
```

`PGHOST` и `PGPASSWORD` не указаны намеренно: пример повторяет стиль ручного
админского запуска `pg_dump -p 10265 -U pgadmin -d application_test`, где доступ
настроен на стороне DB VM.

Не задавайте `SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT=1`, если defaults применять не
нужно. В текущей реализации ручной запуск `run_all_update_sequential_*.sql`
через `psql -f` не является безопасной заменой parallel runner-а без defaults:
sequential SQL содержит `set_default` без runtime-фильтра.

## Send Logs

После выполнения передайте ответственному за релиз ссылки на лог INSERT и
директорию логов UPDATE:

```bash
cd /tmp/data-migrations/manual

echo "INSERT log: $(pwd)/db_insert/insert.log"
echo "UPDATE logs: $(pwd)/db_update_parallel/logs/update_parallel/"
```

`insert.log` явно создается командой `touch "$(pwd)/insert.log"` перед запуском
INSERT, а затем перезаписывается редиректом `> "$(pwd)/insert.log" 2>&1`.
Если shell пишет `bash: insert.log: Permission denied`, значит текущий
пользователь не может создать или перезаписать файл лога в рабочей директории.
Запускайте команды из директории, созданной этим же пользователем, или удалите
старую рабочую директорию перед распаковкой.
Директории `logs/update_parallel/<run_id>/`, `scripts/` и `results/` создаются
самим `run_all_update_parallel_*.sh`; заранее создавать их не нужно.

Передайте все содержимое директории UPDATE logs. Внутри каждого запуска лежат
`summary.log`, `script_timings.log` и полные логи отдельных SQL-скриптов в
`scripts/`.
