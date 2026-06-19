# Ручное применение schema summary SQL на контуре

Эта инструкция предназначена для администраторов TEST/PROD-контуров. На вход
передается релизный архив вида:

```text
db_schema_<contour>_r_<release>-c_<commit>.tar.gz
```

Внутри архива должен быть один SQL-файл в корне:

```text
summary_sql_<contour>_*.sql
```

`<contour>` обычно равен `test` или `prod`.

## Проверка архива

Скопируйте архив на DB VM или на машину, с которой есть доступ к PostgreSQL, и
проверьте состав:

```bash
CONTOUR=test
ARCHIVE=db_schema_test_r_<release>-c_<commit>.tar.gz

tar -tzf "$ARCHIVE"
test "$(tar -tzf "$ARCHIVE" | grep -E "^summary_sql_${CONTOUR}_.+\\.sql$" | wc -l)" -eq 1
```

Если в архиве нет `summary_sql_<contour>_*.sql` или таких файлов больше одного,
не применяйте архив и верните его оператору релиза.

## Распаковка

```bash
RELEASE=<release>
CONTOUR=test
ARCHIVE=db_schema_test_r_<release>-c_<commit>.tar.gz
WORKDIR="/tmp/simple-deploy-schema-${CONTOUR}-${RELEASE}"

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"
tar -xzf "$ARCHIVE" -C "$WORKDIR"
cd "$WORKDIR"

sql_file="$(find . -maxdepth 1 -type f -name "summary_sql_${CONTOUR}_*.sql" | sort | tail -n 1)"
test -n "$sql_file"
sed -n '1,40p' "$sql_file"
```

Проверьте в заголовке SQL-файла contour и диапазон backend commit `from..to`.

## Применение

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
  -f "$sql_file"
```

Если политика безопасности запрещает `PGPASSWORD` в командной строке, используйте
настроенный `.pgpass` или ввод пароля через prompt.

## После выполнения

При успехе передайте оператору simple-deploy:

- contour (`test` или `prod`);
- build version релиза;
- факт успешного применения schema SQL.

Оператор simple-deploy после этого фиксирует baseline:

```powershell
.venv\Scripts\simple-deploy.exe mark-applied --contour test --build-version <release>
```

При ошибке не выполняйте `mark-applied`. Сохраните stdout/stderr `psql` и
передайте лог оператору релиза. Из-за `--single-transaction` частичное применение
одного schema SQL-файла должно быть откатано PostgreSQL.
