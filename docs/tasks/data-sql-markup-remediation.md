# План исправления разметки SQL-скриптов data migration

Дата ревью: 2026-06-08.

Каталог скриптов backend repo:

```text
C:\cps-repo\app-backend-v\app-backend\docs\database\scripts
```

Базовая инструкция по формату разметки:

```text
C:\vibe-repo\simple-deploy\docs\sql\data-script-markup.md
```

## Цель

Привести `simple-deploy`-разметку SQL-файлов к рабочему состоянию для data migration runner:

- разметка должна быть только на data-changing SQL-скриптах;
- DDL/index/VACUUM и другие технические операции не должны попадать в data migration markup;
- все важные `INSERT`, `UPDATE`, `DELETE`, `set_default` data scripts должны быть размечены, кроме legacy `fix_migrations/**`;
- `group` должен соответствовать домену и целевой таблице;
- `critical` должен отражать риск для бизнес-состояния;
- `parallel/order` должны быть пригодны для фактического параллельного запуска в нескольких сессиях.

Текущее состояние после исправления разметки:

- всего SQL-файлов: `105`;
- размечено: `88`;
- без разметки: `17`;
- `create_index/**` не имеют `simple-deploy`-разметки;
- `fix_migrations/**` не имеют `simple-deploy`-разметки;
- все размеченные data-changing scripts имеют полный набор полей
  `kind/order/group/parallel/critical`;
- `critical=false` не используется.

Ожидаемое состояние для поддержки:

- `create_index/**.sql` не имеют `simple-deploy`-разметки;
- `fix_migrations/**.sql` не имеют `simple-deploy`-разметки;
- важные data-changing scripts имеют полный набор полей `kind/order/group/parallel/critical`;
- ориентировочно остается `88` размеченных SQL-файлов;
- `script_docs.md` не содержит `create_index` и `fix_migrations`.

## Что удалить из разметки

Удалить только заголовки `-- simple-deploy: ...`, не меняя SQL-семантику.

Разметку нужно убрать из всех SQL-файлов в:

```text
create_index\gasprojectdata\*.sql
create_index\public\*.sql
fix_migrations\*.sql
fix_migrations\**\*.sql
```

Файлы `create_index\public\*.sql` сейчас не размечены, их нужно оставить без разметки.

Файлы `create_index\gasprojectdata\*.sql`, из которых нужно удалить текущую ошибочную разметку:

```text
create_index\gasprojectdata\idx_tblk20_exex_codidnew_ver.sql
create_index\gasprojectdata\idx_tblk20_limit_5g_pred_ik.sql
create_index\gasprojectdata\idx_tblk20_pred_do.sql
create_index\gasprojectdata\idx_tblonm.sql
create_index\gasprojectdata\idx_tblp20_exex_piridnew_ver.sql
create_index\gasprojectdata\idx_tblp20_limit_5g_pred.sql
create_index\gasprojectdata\idx_tblp20_pred_do.sql
create_index\gasprojectdata\tblp20_notes.sql
```

Причина: `CREATE INDEX`/`VACUUM ANALYZE` не являются data migration scripts. Они не должны иметь `kind=insert` и не должны попадать в `script_docs.md` data runner-а.

Файлы `fix_migrations/**.sql` являются legacy-мусором. Их не нужно размечать и не нужно включать в data migration runner, даже если внутри есть `UPDATE` или `DELETE`.

## Что добавить в разметку

Добавить полный заголовок `simple-deploy` только в важные data-changing SQL-файлы без меток, которые не относятся к legacy `fix_migrations`.

### Update scripts

```text
app_ip_subcompany_prw\update\update_app_ip_subcompany_stagecost.sql
```

Рекомендуемые параметры:

```sql
-- simple-deploy: kind=update
-- simple-deploy: order=<назначить после пересборки параллельных слотов>
-- simple-deploy: group=<домен>_<целевая_таблица>
-- simple-deploy: parallel=<true только если безопасно>
-- simple-deploy: critical=true
```

Ориентиры для `group`:

- `app_ip_subcompany_prw\update\update_app_ip_subcompany_stagecost.sql`: `prw_app_ip_subcompany_stagecost`;
- если при ревью найдутся другие неразмеченные data-changing scripts вне `fix_migrations/**`, их нужно отдельно согласовать и разметить по базовой инструкции.

## Что исправить в существующей разметке

### Ошибки `group`

Исправить явные несоответствия между путем файла, смыслом скрипта и `group`.

```text
app_ip_subcompany_lti\update\update_stagecomment_for_lti_objects_first_stage.sql
```

Было:

```sql
-- simple-deploy: group=cc_app_ip_subcompany_stagecomment
```

Должно быть:

```sql
-- simple-deploy: group=lti_app_ip_subcompany_stagecomment
```

```text
app_ip_subcompany_lti\update\update_stagecomment_for_lti_objects_other_stages.sql
```

Было:

```sql
-- simple-deploy: group=cc_app_ip_subcompany_stagecomment
```

Должно быть:

```sql
-- simple-deploy: group=lti_app_ip_subcompany_stagecomment
```

```text
app_ip_subcompany_pnca\update\update_stagecomment_for_pnca_objects_other_stages.sql
```

Было:

```sql
-- simple-deploy: group=pnca_app_ip_subcompany_stagecost
```

Должно быть:

```sql
-- simple-deploy: group=pnca_app_ip_subcompany_stagecomment
```

После этих исправлений дополнительно пройти все размеченные файлы и проверить:

- путь `lti` не должен иметь `group` с префиксом `cc_`;
- путь `pnca` не должен иметь `group` с другим доменом;
- `stagecomment`-скрипты не должны быть размечены как `stagecost`, если целевая таблица действительно comments;
- `stagecost`-скрипты не должны быть размечены как `stagecomment`.

### `critical`

Текущая разметка слишком часто использует `critical=false`.

Правило исправления:

- для `insert`, `update`, `set_default`, `delete` по умолчанию ставить `critical=true`;
- `critical=false` допустим только при письменном обосновании в задаче или рядом с ревью, что сбой можно безопасно пропустить без нарушения бизнес-состояния;
- тяжёлые backfill/update scripts, переносы данных, зануления и удаления должны быть `critical=true`;
- legacy `fix_migrations/**` не размечаются вообще, поэтому для них `critical` не задается.

Особенно проверить все текущие группы:

```text
set_default, parallel=true, critical=false
update, parallel=true, critical=false
```

Они не должны оставаться в таком виде автоматически.

### `parallel` и `order`

Текущая разметка использует линейную нумерацию `order=1,2,3,...650`. Это не дает реального ускорения и плохо отражает фактическую модель runner-а.

Правила пересборки:

- `parallel=true` ставить только для скриптов, которые можно запускать в разных сессиях без конфликтов;
- не параллелить скрипты, которые пишут в одну и ту же таблицу или в одни и те же строки;
- не параллелить скрипты, если один читает данные, созданные или измененные другим скриптом из того же параллельного набора;
- для сомнительных случаев использовать `parallel=false`;
- значения `order` пересобрать под фактическую семантику runner-а: они должны позволять поднять нужное число сессий для независимых скриптов, а не быть просто уникальными порядковыми номерами.

Особенно осторожно работать с группами, где много скриптов пишут в одну таблицу:

```text
cc_app_ip_subcompany_stagecost
prw_app_ip_subcompany_stagecost
lti_app_ip_subcompany_stagecost
pnca_app_ip_subcompany_stagecost
cc_app_ip_subcompany_stagecomment
prw_app_ip_subcompany_stagecomment
```

Для таких групп одинаковый `group` не является автоматическим запретом на
`parallel=true`, если фильтры разводят ячейки данных. Практическое правило:
параллельные скрипты не должны писать в одну и ту же ячейку - одну строку и один
столбец. Для stagecost/stagecomment это проверяется по доменному фильтру
`partition_item_id`, полному ключу строки (`object_planning_id`, `stage_id`,
`year_type`, `planning_item`, `scenario_planning`, `cost_item`) и обновляемому
столбцу. Если после запуска появятся lock waits или deadlock-и, детализацию
`group` и распределение по `order` нужно пересмотреть отдельно.

## Baseline по времени выполнения

Пересчет по текущим комментариям `Query returned successfully in ...`:

- `insert` без `insert_new_objects/**`: `18` файлов, все с распознанным
  временем, сумма `26.724 сек`;
- `insert` вместе с `insert_new_objects/**`: `23` файла, время есть у `19`,
  сумма распознанного времени `27.035 сек`; новые объекты не входят в текущую
  задачу и остаются отдельным backlog-пунктом;
- `set_default`: `8` файлов, время распознано у `5`, минимум `1 мин 12 сек`;
- `update`: `57` файлов, время распознано у всех `57`, последовательная сумма
  `4 ч 34 мин 20 сек`.

Решение по insert-фазе: обычные insert-скрипты оставляем на существующем
последовательном `run_all_insert` с `ON_ERROR_STOP=1` и проверкой
идемпотентности. Отдельный insert-parallel runner не нужен, потому что обычные
insert-скрипты занимают меньше минуты на фоне update-фазы. `insert_new_objects/**`
не входит в текущую оптимизацию и остается backlog-темой для ручного
одноразового применения.

Аварийный последовательный update-сценарий выделяется в отдельный
`run_all_update_sequential_<commit>.sql` и отдельный архив
`db_update_sequential_r_<release>-c_<commit>.tar.gz`. Он включает только
`kind=update` и `kind=set_default`, исключает `kind=insert` и
`insert_new_objects/**`, сортирует файлы по `order`, `group`, path и запускается
с `ON_ERROR_STOP=1`. Это fallback для одного ядра/одной DB-сессии; основной
сценарий параллельного update-runner-а должен развиваться отдельно.

Основной параллельный update-сценарий выделяется в
`run_all_update_parallel_<commit>.sh` и архив
`db_update_parallel_r_<release>-c_<commit>.tar.gz`. Runner проходит `order` как
барьерные wave, запускает `parallel=true` с лимитом
`SIMPLE_DEPLOY_UPDATE_MAX_WORKERS=8` по умолчанию, выполняет `parallel=false`
эксклюзивно и использует fail-fast. `kind=set_default` в штатном deploy
пропускается по умолчанию и включается только вместе с data migration SQL:
`--include-data-migration-sql --include-set-default-sql`. В терминале видны `[START]`, периодический
`[RUNNING]` со списком активных скриптов, `[OK]`/`[FAIL]`, длительность каждого
скрипта, wave и общий итог; полный psql output лежит в
`logs/update_parallel/<timestamp>/scripts/*.log`.

Файлы с неизвестным временем:

```text
app_ip_subcompany\set_default\update_set_null_for_stagecomment.sql
app_ip_subcompany_cc\set_default\update_set_null_for_stagecomment.sql
app_ip_subcompany_prw\set_default\update_set_null_for_stagecomment.sql
```

Сумма `update` по текущим order-волнам:

```text
500: 1.335 сек
501: 1.335 сек
503: 3.635 сек
504: 1.635 сек
600: 2 ч 29 мин 17 сек
601: 51 мин 5 сек
602: 11 мин 28 сек
603: 2 мин 22 сек
```

## Топ-10 самых медленных скриптов

Эти скрипты вынести в отдельную задачу на оптимизацию. Текущее время использовать как baseline.

| # | Скрипт | Текущее время |
|---|---|---:|
| 1 | `app_ip_subcompany_prw\update\update_app_ip_subcompany_stagecostprw_first_stage.sql` | 40 мин |
| 2 | `app_ip_subcompany\update\cc\update_stagecost_for_cc_objects_subcompany_cost_cost_item_limit.sql` | 21 мин 1 сек |
| 3 | `app_ip_subcompany\update\prw\update_stagecost_for_prw_objects_subcompany_cost_five_years_first_stage.sql` | 18 мин 16 сек |
| 4 | `app_ip_subcompany\update\cc\update_stagecost_for_cc_objects_subcompany_cost_plannings_first_stage.sql` | 13 мин 28 сек |
| 5 | `app_ip_subcompany\update\prw\update_stagecost_for_prw_objects_investment_commission_cost_plannings_first_stage.sql` | 13 мин 25 сек |
| 6 | `app_ip_subcompany\update\cc\update_stagecost_for_cc_objects_ic_cost_item_limit.sql` | 13 мин 23 сек |
| 7 | `app_ip_subcompany_onna\update\update_stagecostonna.sql` | 11 мин 42 сек |
| 8 | `app_ip_subcompany_onna\update\update_stagecomment.sql` | 11 мин 32 сек |
| 9 | `app_ip_subcompany\update\cc\update_stagecost_for_cc_objects_investment_commission_cost_plannings_first_stage.sql` | 9 мин 7 сек |
| 10 | `app_ip_subcompany\update\cc\update_stagecost_for_cc_objects_investment_commission_cost_estimate_cost_cost_item_limit.sql` | 8 мин 52 сек |

Что проверить в задаче на оптимизацию:

- `EXPLAIN (ANALYZE, BUFFERS)` для каждого скрипта на тестовом контуре с сопоставимыми объемами;
- наличие индексов на полях `JOIN`, `WHERE`, `object_planning_id`, `stage_id`, `year_type`, `planning_item`, `scenario_planning`, `cost_item`, кодах объектов и версиях источников;
- row-by-row `DO`/loop-логику заменить на set-based `UPDATE`, если возможно;
- не обновлять строки, где значение уже равно целевому: использовать `IS DISTINCT FROM`;
- проверить, не обновляют ли разные скрипты одни и те же строки повторно;
- рассмотреть батчинг для самых больших update, если блокировки или WAL становятся проблемой;
- после оптимизации повторно зафиксировать время выполнения и сравнить с baseline.
