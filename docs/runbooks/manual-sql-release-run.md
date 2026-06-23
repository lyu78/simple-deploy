# Manual SQL Release Run

Runbook для ручного применения SQL-артефактов release bundle на DB VM или на
машине с доступом к PostgreSQL. Используется для TEST/PROD, когда SQL
применяется внешним администратором, а `simple-deploy` после этого только
фиксирует результат через `mark-applied` или `mark-failed`.

## Входные артефакты

Schema archive:

```text
db_schema_<contour>_r_<release>-c_<commit>.tar.gz
```

Внутри schema archive должен быть ровно один SQL-файл в корне:

```text
summary_sql_<contour>_*.sql
```

Data SQL artifacts, если они включены в релиз:

```text
db_insert_r_<release>-c_<commit>.tar.gz
db_update_parallel_r_<release>-c_<commit>.tar.gz
db_set_default_parallel_r_<release>-c_<commit>.tar.gz
```

`db_set_default_parallel` применяется только если defaults действительно нужны
для релиза.

## Подготовка

Очистите рабочую директорию от старых artifacts и logs:

```bash
RELEASE=<release>
CONTOUR=test
WORKDIR="/tmp/simple-deploy-sql-${CONTOUR}-${RELEASE}"

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/schema"
mkdir -p "$WORKDIR/data/db_insert"
mkdir -p "$WORKDIR/data/db_update_parallel"
mkdir -p "$WORKDIR/data/db_set_default_parallel"
```

Скопируйте release artifacts в `"$WORKDIR"` или подставьте абсолютные пути к
архивам в командах ниже.

## Проверка schema archive

```bash
SCHEMA_ARCHIVE="db_schema_${CONTOUR}_r_${RELEASE}-c_<commit>.tar.gz"

tar -tzf "$SCHEMA_ARCHIVE"
test "$(tar -tzf "$SCHEMA_ARCHIVE" | grep -E "^summary_sql_${CONTOUR}_.+\\.sql$" | wc -l)" -eq 1
```

Если в архиве нет `summary_sql_<contour>_*.sql` или таких файлов больше одного,
не применяйте архив и верните его оператору релиза.

## Применение schema SQL

```bash
tar -xzf "$SCHEMA_ARCHIVE" -C "$WORKDIR/schema"
cd "$WORKDIR/schema"

schema_sql_file="$(find . -maxdepth 1 -type f -name "summary_sql_${CONTOUR}_*.sql" | sort | tail -n 1)"
test -n "$schema_sql_file"
sed -n '1,40p' "$schema_sql_file"
```

Проверьте в заголовке SQL-файла contour и диапазон backend commit `from..to`.

Запускайте schema SQL атомарно: `--single-transaction` откатит весь файл при
ошибке, а `ON_ERROR_STOP=1` остановит выполнение на первой ошибке.

```bash
PGPASSWORD='<password>' psql \
  --set=ON_ERROR_STOP=1 \
  --single-transaction \
  --host='<db_host>' \
  --port='<db_port>' \
  --username='<db_user>' \
  --dbname='<db_name>' \
  -f "$schema_sql_file"
```

Если политика безопасности запрещает `PGPASSWORD` в командной строке,
используйте настроенный `.pgpass` или ввод пароля через prompt.

## Распаковка data SQL artifacts

```bash
cd "$WORKDIR"

tar -xzf db_insert_r_<release>-c_<commit>.tar.gz \
  -C "$WORKDIR/data/db_insert"

tar -xzf db_update_parallel_r_<release>-c_<commit>.tar.gz \
  -C "$WORKDIR/data/db_update_parallel"

tar -xzf db_set_default_parallel_r_<release>-c_<commit>.tar.gz \
  -C "$WORKDIR/data/db_set_default_parallel"
```

Если release bundle не содержит set-default archive, пропустите распаковку и
запуск `db_set_default_parallel`.

## INSERT

В текущей реализации INSERT запускается не параллельным shell runner-ом, а
строгим `psql` entrypoint:

```bash
cd "$WORKDIR/data/db_insert"
touch "$(pwd)/insert.log"
psql \
  --set=ON_ERROR_STOP=1 \
  --host='<db_host>' \
  --port='<db_port>' \
  --username='<db_user>' \
  --dbname='<db_name>' \
  -f "$(ls -1 run_all_insert_*.sql | tail -n 1)" \
  > "$(pwd)/insert.log" 2>&1
```

Ориентир по ранее разобранным данным: обычные insert-скрипты занимали около
`27 секунд`, то есть меньше минуты. Фактическое время смотрите по timestamps
запуска и завершения команды.

## UPDATE Parallel

`run_all_update_parallel_*.sh` содержит только `kind=update`, поэтому его можно
запускать вручную без риска применить defaults:

```bash
cd "$WORKDIR/data/db_update_parallel"
PGHOST='<db_host>' \
PGPORT='<db_port>' \
PGUSER='<db_user>' \
PGDATABASE='<db_name>' \
PSQL_BIN=psql \
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
$WORKDIR/data/db_update_parallel/logs/update_parallel/<run_id>/summary.log
$WORKDIR/data/db_update_parallel/logs/update_parallel/<run_id>/script_timings.log
```

## SET_DEFAULT Parallel

Defaults запускайте только если они действительно нужны для релиза:

```bash
cd "$WORKDIR/data/db_set_default_parallel"
PGHOST='<db_host>' \
PGPORT='<db_port>' \
PGUSER='<db_user>' \
PGDATABASE='<db_name>' \
PSQL_BIN=psql \
SIMPLE_DEPLOY_UPDATE_MAX_WORKERS=8 \
SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS=30 \
bash "$(ls -1 run_all_set_default_parallel_*.sh | tail -n 1)"
```

Ручной sequential fallback также разделен: `run_all_update_sequential_*.sql`
содержит только update, а `run_all_set_default_sequential_*.sql` содержит
только defaults.

## Логи

После выполнения передайте ответственному за релиз ссылки на лог INSERT и
директории логов UPDATE/SET_DEFAULT:

```bash
cd "$WORKDIR/data"

echo "INSERT log: $(pwd)/db_insert/insert.log"
echo "UPDATE logs: $(pwd)/db_update_parallel/logs/update_parallel/"
echo "SET_DEFAULT logs: $(pwd)/db_set_default_parallel/logs/set_default_parallel/"
```

`insert.log` явно создается командой `touch "$(pwd)/insert.log"` перед запуском
INSERT, а затем перезаписывается редиректом `> "$(pwd)/insert.log" 2>&1`.
Если shell пишет `bash: insert.log: Permission denied`, значит текущий
пользователь не может создать или перезаписать файл лога в рабочей директории.
Запускайте команды из директории, созданной этим же пользователем, или удалите
старую рабочую директорию перед распаковкой.

Директории `logs/update_parallel/<run_id>/`,
`logs/set_default_parallel/<run_id>/`, `scripts/` и `results/` создаются
самими parallel runner-ами; заранее создавать их не нужно.

## После выполнения

При успехе передайте оператору `simple-deploy`:

- contour (`test` или `prod`);
- build version релиза;
- факт успешного применения schema SQL;
- факт успешного применения data SQL artifacts, если они запускались;
- ссылки на логи.

Оператор `simple-deploy` после этого фиксирует baseline:

```powershell
.venv\Scripts\simple-deploy.exe mark-applied --contour test --build-version <release>
```

При ошибке не выполняйте `mark-applied`. Сохраните stdout/stderr `psql`, логи
parallel runner-а и передайте их оператору релиза. Оператор фиксирует ошибку:

```powershell
.venv\Scripts\simple-deploy.exe mark-failed --contour test --build-version <release> --error "<error summary>"
```

Из-за `--single-transaction` частичное применение одного schema SQL-файла должно
быть откатано PostgreSQL. Data SQL artifacts могут иметь собственное состояние
частичного выполнения, поэтому повторный запуск согласуйте с владельцем релиза.
