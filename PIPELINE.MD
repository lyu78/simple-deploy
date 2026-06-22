# Продуктовый пайплайн релиза

## Назначение

Этот документ описывает end-to-end процесс релиза на уровне продукта и операций.
Он не выбирает конкретную реализацию и должен быть пригоден как основа для BPMN
схемы: кто участвует в процессе, какие события его запускают, какие артефакты
переходят между этапами и где фиксируется результат.

Технические реализации описаны отдельно:

- `tools-ci/PIPELINE.MD` - основной Windows/Python процесс через локальные tools.
- `legacy/ansible-ci/PIPELINE.MD` - legacy-процесс через Ansible/WSL control node.

## Участники

- Оператор релиза - запускает проверки, сборку, деплой и фиксирует результат.
- Рабочая машина - хранит локальные рабочие копии, состояние контуров и релизные
  артефакты.
- Внешние Git-репозитории - источник изменений backend и frontend.
- Внутренние Git-репозитории - целевой GitLab для синхронизированного кода и
  аудита изменений.
- Release storage - локальная директория версий релиза с manifest и архивами.
- DB VM - место применения schema SQL, data SQL и технических SQL-команд.
- App VM - место включения maintenance-заглушки, распаковки backend/frontend,
  запуска management-команд, сервисных шагов и healthcheck.

## Основной поток

1. Оператор выбирает контур: `dev` для локального DEV-стенда, `test` для
   тестового контура или `prod` для продуктивного контура. Для выбранного
   контура должен быть известен backend baseline - commit backend-репозитория,
   который уже успешно применен на этом контуре.
2. Рабочая машина выполняет dry-run: проверяет конфигурацию, локальные
   репозитории, доступность VM, PostgreSQL, директорий деплоя, сервисных прав и
   HTTP endpoint.
3. Рабочая машина синхронизирует исходники из внешних backend/frontend
   репозиториев во внутренние рабочие копии.
4. Сборочный этап создает версию релиза в формате
   `<BUILD_VERSION_BASE>.<ddMMyyyy_HHmm>`, например `1.2.3.30052026_1437`.
   В директорию релиза попадают runtime-архивы приложения, schema SQL-архивы,
   data SQL-архивы при включенном data SQL build и `release_manifest.json`.
5. Внутренние рабочие копии получают синхронизационные ветки; код публикуется во
   внутренний GitLab, а runtime-архивы остаются в release storage.
6. Для full deploy DEV app-сервисы останавливаются, а в `FRONTEND_RELEASE_PATH`
   раскладывается универсальная maintenance-заглушка. Пока backend остановлен,
   DB VM применяет schema SQL, `run_all_insert_*.sql`, parallel update runner
   `run_all_update_parallel_*.sh` и DB maintenance.
7. После успешной DB-части App VM получает настоящий backend, выполняет
   `after_unpack`, Django `migrate --fake`, `sync_action_role` и `after_migrate`
   service steps. Настоящий frontend раскладывается последним и заменяет
   заглушку только после успешного старта backend.
8. Рабочая машина выполняет healthcheck стенда и проверку версии портала.
9. Результат релиза фиксируется как успешный или неуспешный. Успех двигает
    baseline выбранного контура на backend commit релиза; ошибка записывает
    попытку без изменения baseline.

## Развилки

- Если dry-run не проходит, процесс завершается до сборки и деплоя.
- Если сборка не создала обязательные архивы или manifest, деплой не начинается.
- Если schema SQL или data SQL не применились, настоящий backend/frontend не
  должны считаться успешно размещенными; maintenance-заглушка остается на DEV.
- Если app deploy или healthcheck завершается ошибкой, baseline не двигается.
- Если deploy успешен, release storage и локальное состояние контуров становятся
  источником для следующего диапазона SQL-миграций.

## Контуры

DEV обычно является автоматизируемым контуром полного цикла: build, schema SQL,
data SQL, maintenance-заглушка, app deploy, healthcheck и фиксация успеха
выполняются одним операторским процессом.

TEST и PROD могут продвигаться внешним или ручным процессом. Для них критично
после успешного применения явно зафиксировать результат, чтобы следующий build
строил SQL-диапазон от фактически примененного backend commit. Неуспешные попытки
фиксируются отдельно и не меняют baseline.

## Состояния и артефакты

- `baseline` - backend commit, который уже успешно применен на контуре.
- `release_manifest.json` - описание версии релиза, backend/frontend commit и
  SQL metadata.
- `backend_r_<release>-bf_<build_flavor>-env_<env>.tar.gz` - runtime-архив
  backend-приложения.
- `frontend_r_<release>-bf_<build_flavor>-env_<env>.tar.gz` - runtime-архив
  frontend-сборки.
- `tools-ci/maintenance_stub/maintenance_stub.tar.gz` - универсальная статическая
  заглушка DEV, не привязанная к версии релиза; используется только на время
  full deploy до успешного старта backend.
- `db_schema_dev_r_<release>-c_<commit>.tar.gz`,
  `db_schema_test_r_<release>-c_<commit>.tar.gz`,
  `db_schema_prod_r_<release>-c_<commit>.tar.gz` - schema SQL-архивы для
  контуров `dev`, `test`, `prod`; внутри лежит `summary_sql_<contour>_*.sql`
  с SQL-представлением schema migrations за диапазон `baseline..release commit`.
- `db_insert_r_<release>-c_<commit>.tar.gz` - data SQL-архив insert-миграций с
  `run_all_insert_<commit>.sql` и SQL-файлами, на которые он ссылается.
- `db_update_sequential_r_<release>-c_<commit>.tar.gz` - аварийный data SQL-архив
  последовательных update-миграций с
  `run_all_update_sequential_<commit>.sql` и SQL-файлами, на которые он ссылается.
- `db_update_parallel_r_<release>-c_<commit>.tar.gz` - data SQL-архив
  параллельных wave update-миграций с
  `run_all_update_parallel_<commit>.sh` и SQL-файлами, которые он запускает.
- `db_set_default_sequential_r_<release>-c_<commit>.tar.gz` - аварийный data
  SQL-архив последовательных set_default-миграций с
  `run_all_set_default_sequential_<commit>.sql`.
- `db_set_default_parallel_r_<release>-c_<commit>.tar.gz` - data SQL-архив
  параллельных wave set_default-миграций с
  `run_all_set_default_parallel_<commit>.sh`.
- `success` - релиз применен и baseline контура можно двигать вперед.
- `failed` - попытка зафиксирована, baseline остается прежним.

## Граница документа

Этот документ намеренно не содержит команд запуска, переменных окружения и
особенностей runtime-инструментов. Эти детали принадлежат технологическим
документам для конкретной реализации.
