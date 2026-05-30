# Разметка data SQL-скриптов backend repo

Этот документ описывает будущий контракт разметки для SQL-скриптов, которые
попадают в data migration flow (`run_all_insert` / `run_all_update`). Разметка
добавляется в сами SQL-файлы backend repo вручную. `simple-deploy` сейчас не
меняет backend repo и пока не использует эти метаданные при сборке.

Цель разметки - подготовить скрипты к более явному и безопасному runner:

- разделять `insert`, `update`, `set_default` и `delete` без зависимости от
  имени файла;
- задавать порядок выполнения зависимых скриптов;
- явно включать параллельное выполнение только там, где оно безопасно;
- отделять критичные скрипты от необязательных или повторяемых операций.

## Формат заголовка

Метаданные пишутся в начале SQL-файла обычными комментариями:

```sql
-- simple-deploy: kind=insert
-- simple-deploy: order=100
-- simple-deploy: group=reference
-- simple-deploy: parallel=false
-- simple-deploy: critical=true
```

Поддерживаемые поля:

- `kind`: тип скрипта, `insert`, `update`, `set_default` или `delete`.
- `order`: числовая волна выполнения. Меньшее значение выполняется раньше.
- `group`: логическая группа, например домен данных или граница зависимости.
- `parallel`: можно ли запускать скрипт параллельно с другими скриптами той же
  волны.
- `critical`: должен ли весь batch считаться неуспешным при ошибке этого
  скрипта.

## Типы kind

- `insert`: добавление новых строк или upsert справочных/продуктовых данных.
- `update`: изменение существующих строк, backfill, пересчет или перенос
  значений между колонками.
- `set_default`: строки в таблице остаются, но продуктовые колонки приводятся к
  дефолтным значениям. Такой скрипт не должен удалять бизнес-объекты.
- `delete`: удаление объектов по точному условию, если они есть. Условие должно
  быть достаточно узким, чтобы повторный запуск был безопасен и не затронул
  лишние данные.

## Рекомендуемые значения order

- `100`: справочники и независимые reference data.
- `200`: базовые сущности, от которых зависят последующие операции.
- `300`: зависимые обновления, backfill, связи между сущностями.
- `400`: приведение продуктовых колонок к дефолтным значениям.
- `800`: контролируемое удаление объектов по условию.
- `900`: cleanup, повторяемые или некритичные операции.

Значения можно детализировать внутри проекта: например `110`, `120`, `130` для
нескольких волн справочников.

## Правила parallel

`parallel=true` ставится только если скрипт действительно независим:

- не пишет в те же строки и таблицы, что другие скрипты той же волны;
- не читает данные, которые создаются соседним параллельным скриптом;
- не зависит от порядка выполнения внутри своей волны;
- не использует глобальные временные состояния, advisory locks или shared
  sequence assumptions, которые могут конфликтовать.

Если есть сомнение, оставляйте `parallel=false`. Последовательное выполнение
медленнее, но проще для диагностики и безопаснее для зависимых данных.

## Правила critical

`critical=true` используется по умолчанию. Ошибка такого скрипта должна
останавливать batch и требовать разбора причины.

`critical=false` допустим только для операций, которые можно безопасно
пропустить или повторить позже без нарушения бизнес-состояния: например
best-effort cleanup, пересчет необязательных кешей или техническая нормализация,
не влияющая на корректность релиза.

## Идемпотентность

Разметка не делает SQL идемпотентным сама по себе. Идемпотентность должна быть
заложена в скрипт:

- `INSERT ... ON CONFLICT DO NOTHING/UPDATE`;
- `MERGE`, если версия PostgreSQL и проектный стиль это допускают;
- guarded `UPDATE ... WHERE ...`;
- `UPDATE ... SET column = DEFAULT WHERE ...` для `set_default`;
- `DELETE ... WHERE ...` с точным и повторяемым условием для `delete`;
- явный `TRUNCATE + INSERT` только для таблиц, где это безопасно;
- проверки существования объектов или данных до изменения.

## Пример insert

```sql
-- simple-deploy: kind=insert
-- simple-deploy: order=100
-- simple-deploy: group=reference.currency
-- simple-deploy: parallel=true
-- simple-deploy: critical=true

INSERT INTO currency (code, name)
VALUES ('USD', 'US Dollar')
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name;
```

## Пример update с зависимостью

```sql
-- simple-deploy: kind=update
-- simple-deploy: order=300
-- simple-deploy: group=customer.backfill
-- simple-deploy: parallel=false
-- simple-deploy: critical=true

UPDATE customer c
SET normalized_email = lower(trim(c.email))
WHERE c.email IS NOT NULL
  AND c.normalized_email IS DISTINCT FROM lower(trim(c.email));
```

## Пример set_default

```sql
-- simple-deploy: kind=set_default
-- simple-deploy: order=400
-- simple-deploy: group=product.flags
-- simple-deploy: parallel=false
-- simple-deploy: critical=true

UPDATE product_settings
SET promo_enabled = DEFAULT,
    promo_limit = DEFAULT
WHERE product_code = 'CARD_STANDARD';
```

Такой скрипт можно запускать повторно: строки не удаляются, а целевые колонки
снова получают значения по умолчанию.

## Пример delete

```sql
-- simple-deploy: kind=delete
-- simple-deploy: order=800
-- simple-deploy: group=product.cleanup
-- simple-deploy: parallel=false
-- simple-deploy: critical=true

DELETE FROM product_option
WHERE option_code = 'LEGACY_LIMIT'
  AND product_code = 'CARD_STANDARD';
```

Для `delete` условие должно быть частью ревью: скрипт обязан удалять только
ожидаемые объекты и быть безопасным при повторном запуске, когда строк уже нет.

## Значения по умолчанию для будущего runner

Для обратной совместимости будущий runner должен уметь читать старые файлы без
метаданных. Рекомендуемые defaults:

- `parallel=false`;
- `critical=true`;
- `order=1000`;
- `kind` временно определяется по текущему legacy-разделению insert/update.
  `set_default` и `delete` должны задаваться явно, потому что по имени файла их
  безопасно не вывести.

После разметки всех актуальных SQL-файлов `kind` лучше требовать явно.

## Порядок внедрения

1. Разметить очевидно безопасные reference insert-скрипты.
2. Оставить зависимые и спорные update-скрипты последовательными
   (`parallel=false`).
3. Явно выделить `set_default` и `delete`, где семантика скрипта отличается от
   обычного update.
4. Проверить, что `order` отражает реальные зависимости между данными.
5. Постепенно расширять `parallel=true` только после успешных запусков и
   ревью конфликтов по таблицам.
6. Не менять семантику SQL одновременно с разметкой, если это не требуется для
   идемпотентности.
