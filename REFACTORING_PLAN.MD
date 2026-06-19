# План рефакторинга simple-deploy

Дата фиксации плана: 2026-06-09.

## Зачем это делаем

Репозиторий начинался как практический контур для Ansible и локального деплоя, но фактически вырос в release/deploy toolkit:

- собирает продуктовый release artifact;
- хранит baseline по контурам `dev`, `test`, `prod`;
- генерирует schema/data SQL артефакты;
- умеет раскладывать maintenance stub;
- управляет порядком остановки backend/frontend/nginx;
- проверяет и применяет долгие data update скрипты;
- фиксирует успешные и неуспешные build/deploy attempts в SQLite.

Из-за этого основной риск теперь не в отдельных функциях, а в форме проекта. Один файл `tools-ci/tools/windows_pipeline.py` содержит конфиг, валидацию, SSH, SQL, deploy, dry-run, состояние релизов, уведомления и CLI. Такой файл сложно расширять под тестовые пайплайны, стресс-тесты, альтернативные команды, заявки на TEST/PROD и простую web-морду.

Цель рефакторинга - сохранить текущий рабочий CLI, но разложить систему вокруг процессов и контуров.

## Как пришли к решению

1. Текущий основной путь - Windows/Python runner без обязательного WSL/Docker. Ansible остался как legacy-вариант и больше не является центром развития.
2. Ключевой объект системы - релиз как продуктовый артефакт, а не отдельный deploy-скрипт.
3. DEV, TEST и PROD должны быть явными контурами с разными правилами:
   - DEV может выполнять deploy напрямую на VM;
   - TEST/PROD могут требовать пакеты, заявки, ручную фиксацию статусов и другие уведомления;
   - build пока может собирать frontend сразу для всех контуров, но архитектура не должна на это завязываться.
4. Все текущие команды должны остаться доступными из терминала.
5. Web/API нужен как дополнительный интерфейс поверх тех же команд и той же SQLite-базы, без авторизации и ролевой модели на первом этапе.
6. Долгие операции из web-интерфейса нельзя выполнять синхронно внутри HTTP-запроса. Нужна модель локальных jobs.
7. Репозиторий стоит развивать как deploy/release toolkit, а не как набор разрозненных скриптов качества кода.

## Целевая модель

Два интерфейса вызывают одну и ту же прикладную логику:

- CLI: совместимый вход через `tools-ci/tools/windows_pipeline.py`;
- Web/API: простая локальная панель и REST API для просмотра релизов, запусков и статусов.

Общее ядро отвечает за:

- конфигурацию и runtime validation;
- состояние релизов и контуров в SQLite;
- build, deploy, dry-run и mark-applied/mark-failed процессы;
- jobs для долгих операций;
- логи и итоговые статусы.

## Целевая структура

Промежуточная целевая структура внутри `tools-ci`:

```text
tools-ci/
  simple_deploy/
    cli/
      windows_pipeline.py
    config/
      runtime.py
      validation.py
    core/
      commands.py
      logging.py
      paths.py
      ssh.py
    release/
      artifacts.py
      state.py
      manifest.py
    contours/
      model.py
      dev.py
      test.py
      prod.py
    processes/
      dry_run.py
      build.py
      deploy.py
      mark.py
      data_sql.py
    jobs/
      model.py
      runner.py
      repository.py
    web/
      api.py
      app.py
      templates/
      static/
  tools/
    windows_pipeline.py
```

`tools-ci/tools/windows_pipeline.py` остается совместимым wrapper-ом. Он должен импортировать новый CLI entrypoint и не менять публичные команды.

Ansible переносится в legacy-зону:

```text
legacy/
  legacy/ansible-ci/
```

Документация, которая ссылается на Ansible, должна явно называть его legacy-вариантом.

## Контуры и пайплайны

Общая модель:

- `dev` - полный локально управляемый deploy на VM;
- `test` - подготовка пакета, заявка/трек статуса, ручная фиксация результата;
- `prod` - подготовка production-пакета, более строгие проверки, ручная фиксация результата.

Минимальные сущности:

- release;
- contour;
- build attempt;
- deployment attempt;
- external request;
- local job.

CLI-команды остаются первичным контрактом:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run --contour dev
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --latest
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-applied --contour test --build-version <version>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-failed --contour test --build-version <version> --error "<reason>"
```

Новые пайплайны должны добавляться как процессы, а не как новые ветки большого файла:

- test pipeline;
- alternative deploy commands;
- stress tests;
- package for test;
- package for prod;
- request tracking for test/prod.

## Web/API v1

Первый web/API слой должен быть простым:

- FastAPI;
- без авторизации и ролей;
- та же SQLite-база, что у CLI;
- запуск долгих операций через local jobs;
- просмотр релизов, build attempts, deployment attempts и jobs;
- запуск существующих CLI-процессов через resource-oriented API без RPC-style
  endpoints;
- ручная пометка `applied`/`failed` для TEST/PROD.

Web не должен становиться отдельной реализацией деплоя. Он только интерфейс к тому же toolkit.

REST-контракт для будущих write endpoints должен быть строгим:

- `POST` к коллекции создает новый дочерний ресурс, например
  `POST /releases/{release_version}/build-attempts`;
- если релиз уже успешно собран или сборка уже активна, API возвращает
  `409 Conflict`, а не существующий релиз как успешный результат `POST`;
- `403 Forbidden` остается ошибкой доступа, а не способом сообщить о конфликте
  состояния;
- RPC-style действия вроде `runBuild`/`buildRelease` не являются целевой формой
  публичного API.

Модель хранения для будущих schema changes должна держаться 3НФ:

- SQLite registry хранит сущности, связи и факты без дублирования свойств
  другого ресурса;
- `ContourState` ссылается на release/placement, а не становится владельцем
  commit-ов или bundle metadata;
- backend/frontend commits принадлежат source snapshot/release bundle;
- удобные поля для dashboard/API собираются в read models/DTO как производная
  проекция, а не записываются в БД как второй источник истины.
- до миграции storage API может сохранять legacy-поля контура, но рядом должен
  отдавать ссылку на ресурс релиза как источник производных commit/status полей.

## Порядок реализации

1. Зафиксировать этот план в корне репозитория.
2. Создать пакет `tools-ci/simple_deploy/`.
3. Оставить `tools-ci/tools/windows_pipeline.py` как совместимый wrapper.
4. Вынести release/state/artifact primitives из builder и pipeline в общие модули.
   Перед шагом 5 допускаются стабилизационные подшаги `4.x`, если они
   уменьшают риск переноса монолитного pipeline без изменения поведения.
5. Разложить текущие процессы по модулям `dry_run`, `build`, `deploy`, `mark`, `data_sql`.
6. Перенести `legacy/ansible-ci/` в `legacy/legacy/ansible-ci/` и обновить ссылки в документации.
7. Расширить SQLite-модель под jobs и external requests.
8. Добавить FastAPI API поверх release/job/process слоев.
9. Добавить простую web-страницу для v1 dashboard.
10. Обновить документацию и тесты.

## Инварианты совместимости

Во время рефакторинга нельзя ломать:

- текущие команды `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`, `mark-applied`, `mark-failed`;
- формат локального `windows_pipeline.local.json`, если нет отдельной миграции;
- хранение state в `local_state/simple_deploy.sqlite3`;
- генерацию build artifacts;
- порядок full deploy для DEV;
- проверку maintenance stub перед DB deploy;
- preflight cleanup долгих data update скриптов;
- поведение `data_sql_enabled` и `--include-set-default-sql`;
- логи в терминал и `logs/<timestamp>-<command>.log`.

## Проверки на каждом этапе

Минимальный набор:

```bash
.venv/Scripts/python.exe -m pytest tests/test_windows_pipeline_permissions.py
.venv/Scripts/python.exe -m pytest
git diff --check
```

Для этапов, которые трогают build/deploy:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run --contour dev
```

Для web/API этапов дополнительно:

```bash
.venv/Scripts/python.exe -m pytest tests
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci
```

## Ближайший безопасный срез

Первый кодовый срез после этого документа:

1. создать пустой пакет `tools-ci/simple_deploy/`;
2. добавить новый CLI entrypoint;
3. сделать `tools-ci/tools/windows_pipeline.py` тонким wrapper-ом без изменения поведения;
4. покрыть wrapper smoke-тестом;
5. только после этого переносить реальные процессы по одному.

Такой порядок позволяет начать рефакторинг без одновременного изменения deploy-логики.

## Статус первого среза

Выполнено в первом безопасном срезе:

- создан этот план;
- создан пакет `tools-ci/simple_deploy/` и начальный каркас подпакетов;
- `tools-ci/tools/windows_pipeline.py` оставлен как compatibility wrapper;
- текущая реализация runner перенесена в `tools-ci/simple_deploy/windows_pipeline.py` без изменения CLI-контракта;
- добавлен facade `simple_deploy.release.state`;
- SQLite state расширен таблицами `local_jobs` и `external_requests`;
- добавлен read-only FastAPI dashboard/API v1;
- `ansible-ci/` перенесен в `legacy/ansible-ci/` с исправлением ссылок и default path вычислений;
- тесты обновлены под новую структуру.

## Статус шага 4

Шаг 4 завершен отдельным срезом:

- SQLite state implementation перенесена в `tools-ci/simple_deploy/release/state.py`;
- `tools-ci/builder/src/release_state.py` оставлен compatibility shim-ом для старых импортов `src.release_state`;
- release artifact primitives вынесены в `tools-ci/simple_deploy/release/artifacts.py`;
- release manifest primitives вынесены в `tools-ci/simple_deploy/release/manifest.py`;
- builder и Windows runner используют общие `simple_deploy.release.*` модули вместо собственной реализации state/artifact/manifest primitives;
- совместимость текущего CLI wrapper-а сохранена.

## Промежуточные шаги перед шагом 5

После завершения шага 4 стало видно, что шаг 5 затрагивает не только
расположение кода, но и публичные процессные контракты текущего runner-а:
CLI-команды, ручные mark-команды, build orchestration, deploy ordering и режимы
data SQL/maintenance stub. Поэтому между шагами 4 и 5 добавлены три
промежуточных шага. Они не меняют целевой шаг 5, а снижают риск переноса
монолитного pipeline без достаточной страховки.

Итого добавлено 3 промежуточных шага:

- `4.5` - зафиксировать тестовые контракты и нейтрализовать тестовые данные;
- `4.6` - добавить characterization tests для CLI/process entrypoints;
- `4.7` - сделать обязательную архитектурную паузу перед началом шага 5.

### Шаг 4.5 - тестовые контракты

Статус: выполнен.

Что сделано:

- тестовые модули получили русскоязычные module/class/function docstring;
- повторяющиеся build versions, commits, remote paths, SQL paths и config paths
  вынесены в константы на уровне тестовых модулей;
- из тела тестов убраны локальные и проектно-специфичные хардкодные пути;
- product-код и поведение CLI не менялись.

Зачем:

- тесты перед шагом 5 стали ближе к исполняемой спецификации текущего поведения;
- стало проще увидеть, какой контракт защищает конкретный тест;
- последующее разбиение тестов по директориям можно делать механически, не
  распутывая одновременно тестовые данные и структуру файлов;
- архитектура закрытого репозитория-источника больше не размазана по телам
  тестов.

### Шаг 4.6 - characterization tests CLI/process entrypoints

Статус: выполнен.

Добавлен узкий набор тестов, которые фиксируют текущее внешнее поведение
перед переносом процессов:

- `parse_args()` и `main()` для команд `dry-run`, `build`, `deploy`,
  `pipeline`, `set-baseline`, `mark-applied`, `mark-failed`;
- `set_baseline`, `mark_applied`, `mark_failed` как отдельные ручные процессы,
  включая явное правило, когда baseline двигается, а когда нет;
- `build()` как orchestration wrapper: загрузка env, подготовка frontend env
  files, запуск `create_release.py`, `cwd`, timeout и переменные data SQL;
- точечные deploy-сценарии, которые сейчас важны перед выносом:
  `data_sql_enabled=false`, `maintenance_stub_enabled=false`, успешная фиксация
  state после healthcheck.

Цель шага 4.6 - не расширить функциональность, а зафиксировать текущее
поведение process entrypoints до физического переноса кода по модулям.

Что сделано:

- зафиксирован `parse_args()` contract для всех публичных CLI-команд;
- зафиксирован `main()` dispatch через `tee_output`;
- добавлены тесты `set-baseline`, `mark-applied`, `mark-failed` на временной
  SQLite-базе и переносимом `release_manifest.json`;
- расширено покрытие `build()` как orchestration wrapper-а вокруг
  `builder/create_release.py`;
- добавлены deploy characterization tests для отключенного data SQL, отключенного
  maintenance stub и порядка успешных side effects `healthcheck -> mark -> email`.

### Шаг 4.7 - архитектурная пауза перед шагом 5

Статус: выполнен.

После 4.6 нельзя автоматически начинать шаг 5. Нужно отдельно остановиться и
оценить, достаточно ли подготовлена база для переноса процессов. На этой паузе
нужно решить:

- нужно ли перед шагом 5 разнести тесты по директориям `release`, `builder`,
  `processes`, `web`;
- нужно ли вынести общие тестовые fixtures/support helpers из модульных
  констант;
- нужно ли сначала описать границы будущих модулей `dry_run`, `build`, `deploy`,
  `mark`, `data_sql` без переноса логики;
- какой процесс переносить первым и каким минимальным diff-ом.

Следующий основной шаг рефакторинга остается шагом 5: разложить текущие
процессы по модулям `dry_run`, `build`, `deploy`, `mark`, `data_sql`. Но
начинать его можно только после завершения 4.6 и отдельного решения по 4.7.

Решение по 4.7:

- тесты пока не разносить по директориям, чтобы не смешивать перенос тестов и
  перенос production-кода;
- общие fixtures/support helpers вынести позже, когда появится второй процессный
  модуль и станет видна повторяемая форма;
- шаг 5 начинать с `data_sql`, потому что этот участок уже хорошо покрыт
  characterization tests и меньше всего зависит от CLI dispatch;
- первый срез шага 5 делать как перенос функций с сохранением старых import и
  patch точек через `tools.windows_pipeline`.

## Статус шага 5

Шаг 5 начат первым безопасным срезом:

- создан модуль `tools-ci/simple_deploy/processes/data_sql.py`;
- из монолитного `tools-ci/simple_deploy/windows_pipeline.py` вынесены функции
  доставки и запуска DB SQL артефактов:
  `cleanup_db_data_update_leftovers`, `remote_db_sql_unpack_command`,
  `remote_db_schema_unpack_command`, `upload_unpack_db_sql_artifact`,
  `run_db_schema_summary`, `run_db_data_insert`, `run_db_data_update_parallel`,
  `run_db_maintenance`;
- `windows_pipeline` реэкспортирует эти имена, поэтому старые imports и patch
  paths через `tools.windows_pipeline` остаются рабочими;
- core/SSH helper-ы пока остаются в монолите и используются из `data_sql`
  лениво, чтобы не смешивать первый process-split с переносом core-слоя.

Вторым безопасным срезом вынесен `mark`:

- создан модуль `tools-ci/simple_deploy/processes/mark.py`;
- из монолитного runner-а вынесены `mark_contour_applied`,
  `mark_contour_failed`, `mark_contour_failed_best_effort`, `set_baseline`,
  `mark_applied`, `mark_failed`;
- ручные команды продолжают работать через старые CLI entrypoints и старые patch
  paths `tools.windows_pipeline.*`;
- baseline по-прежнему двигается только для `set-baseline` и `mark-applied`,
  а `mark-failed` пишет failed attempt без изменения baseline.

Третьим безопасным срезом вынесен `build`:

- создан модуль `tools-ci/simple_deploy/processes/build.py`;
- из монолитного runner-а вынесен процесс `build(args)`;
- запуск `builder/create_release.py`, `cwd`, timeout, frontend env preparation и
  флаг `SIMPLE_DEPLOY_INCLUDE_DATA_SQL` сохранены через compatibility runner;
- старый import/patch path `tools.windows_pipeline.build` остается рабочим.

Четвертым безопасным срезом вынесен `dry_run`:

- создан модуль `tools-ci/simple_deploy/processes/dry_run.py`;
- из монолитного runner-а вынесены `dry_run(args)` и `required_env_keys`;
- preflight helper-ы config/runtime/SSH/HTTP/SQL пока остаются в compatibility
  runner-е и вызываются лениво, чтобы не смешивать process-split с переносом
  core-слоя;
- старые import/patch paths `tools.windows_pipeline.dry_run` и
  `tools.windows_pipeline.required_env_keys` остаются рабочими.

Пятым безопасным срезом вынесен `deploy`:

- создан модуль `tools-ci/simple_deploy/processes/deploy.py`;
- из монолитного runner-а вынесен верхнеуровневый процесс `deploy(args)`;
- порядок full deploy сохранен: resolve release, app/db artifacts, service
  steps, maintenance stub, schema/data SQL, management commands, frontend,
  healthcheck, state update и success email;
- режим `--app-only` сохранен без DB-шагов и без обязательных secrets;
- failed attempt по-прежнему пишется best-effort до успешной фиксации state,
  а после успешного `mark_contour_applied` ошибка логируется без отката state;
- helper-ы config/runtime, SSH, app/db/service, healthcheck и email пока
  остаются в compatibility runner-е и вызываются лениво из process-модуля;
- старый import/patch path `tools.windows_pipeline.deploy` остается рабочим.

Шаг 5 завершен в текущем безопасном объеме: процессы `data_sql`, `mark`,
`build`, `dry_run` и `deploy` разложены по модулям `simple_deploy.processes`.
Оставшийся крупный рефакторинг относится уже к следующим архитектурным слоям:
config/runtime, command execution, SSH/app/db helpers, service steps,
healthcheck/email и более чистым process boundary тестам.

## Следующий этап: шаг 6, DDD/Pydantic границы

После завершения шага 5 не начинаем сразу глубокий распил оставшегося
`tools-ci/simple_deploy/windows_pipeline.py`. В нем все еще лежат технические
helper-слои config/runtime, command execution, SSH, app/db operations, service
steps, healthcheck, email и summary. Механический перенос этих блоков без
согласованных доменных границ даст много churn и мало архитектурной ясности.

Рабочий словарь и целевая модель зафиксированы в `DDD_REFACTORING.MD`.
Реализационные слои для постепенного перехода:

- `types` - enum-ы, справочники и custom primitive types без бизнес-логики;
- `entities` - чистые DDD entities/value objects и доменные инварианты;
- `models` - внутренние application/read/storage-facing модели;
- `dto` - внешние request/response контракты API/CLI/web/integrations;
- `configs` - Pydantic-схемы и загрузчики runtime/env/json конфигурации.

Оценка риска по слоям:

- низкий риск: `types`, read-only `models`, response `dto`;
- средний риск: `configs`, потому что они начнут разгребать env/runtime
  конфигурацию и текущий хардкод;
- высокий риск: `entities` и перенос правил build/deploy, потому что это уже
  влияет на CLI flow, baseline, deploy attempts и SSH/VM операции.

Порядок шага 6:

1. Начать с `types` для контуров, статусов, artifact scope/kind, компонентов,
   deploy entrypoint roles, trigger types и базовых строковых идентификаторов.
2. Добавить read-only `models` поверх текущего SQLite state/API без изменения
   поведения.
3. Добавить `dto` для внешнего read-only API/dashboard и держать response DTO
   отдельно от внутренних models.
4. Добавить `configs` для sources, origins, components, landscapes, machines и
   execution environments, чтобы постепенно убирать конфигурационные свалки.
5. Только после стабилизации read-only границ вводить `entities` с доменными
   инвариантами: один release - один успешный bundle, PROD только после TEST,
   contour-specific artifacts не применяются к чужому контуру, validation
   pipeline не меняет baseline.
6. После этого вернуться к оставшемуся `windows_pipeline.py` и переносить
   helper-слои уже в понятные области: `configs`, `bundles`, `environments`,
   `sources`, `registry`, command/SSH infrastructure и notifications.

### Статус первого среза шага 6

Шаг 6 начат с read-only DTO слоя поверх текущего SQLite state/API:

- создан пакет `tools-ci/simple_deploy/dto/`;
- создан пакет `tools-ci/simple_deploy/types/` с первыми custom primitives:
  `ReleaseVersionString`/`BuildVersionString`, `CommitShaString`, `ContourCode`
  status types, `ComponentId`, `ArtifactKind`/`ArtifactScope`,
  `DeploymentTargetRole`, `JobKind`, `ExternalRequestType`,
  `ReleaseTriggerType`, `SourceOriginKind`, `RepoId`, `MachineId` и
  runtime-справочниками фаз/service actions;
- добавлены Pydantic DTO для state snapshot, releases, build/deploy attempts,
  jobs, external requests и contour state;
- добавлены внутренние read-only `models` для того же state snapshot, чтобы web/API
  шел через `SQLite state -> models -> DTO`;
- DTO-поля `build_version`, commit SHA, `contour` и `status` подключены к custom
  types без изменения SQLite-схемы;
- добавлен первый `configs`-срез: Pydantic `RuntimeConfigModel` для текущего
  `windows_pipeline.local.json`, а `load_runtime_config_model()` оставлен
  отдельной typed-оберткой над старым loader без изменения формата config;
- runtime preflight/policy validation вынесена в
  `tools-ci/simple_deploy/config/validation.py`, при этом
  `tools.windows_pipeline.check_runtime_config` оставлен compatibility wrapper-ом;
- FastAPI endpoints `/api/state`, `/api/releases`, `/api/jobs`, `/api/requests`
  используют `response_model` и возвращают DTO вместо сырых `dict`/`asdict`;
- публичный helper `state_snapshot()` сохраняет прежний JSON-совместимый словарь
  для dashboard-кода;
- тест `tests/test_web_app.py` расширен так, чтобы фиксировать JSON-контракт
  snapshot и отдельных read-only endpoints.

Поведение CLI, builder, deploy-процессов, SQLite-схема и public wrapper paths в
этом срезе не менялись.

Исключение: если отдельный маленький блок монолита мешает внедрению DTO,
models или configs, его можно вынести точечно с сохранением старых import/patch
paths. Но уменьшение `windows_pipeline.py` само по себе не является целью
следующего этапа.

### Статус второго среза шага 6

Второй безопасный срез продолжил config/read границы без изменения runtime
поведения:

- добавлен модуль `tools-ci/simple_deploy/config/topology.py`;
- добавлены immutable Pydantic-модели для `SourceOrigin`,
  `SourceRepository`, `Component`, `VirtualMachine`, `DeploymentTarget`,
  `DeploymentLandscape`, `ExecutionEnvironment` и агрегированного
  `RuntimeTopology`;
- модели используют уже введенные domain types (`RepoId`, `MachineId`,
  `ComponentId`, `ContourCode`, `SourceOriginKind`, `DeploymentTargetRole`);
- текущий `.env`, `windows_pipeline.local.json`, CLI, builder/deploy flow и
  SQLite-схема не менялись;
- topology models пока не являются loader-ом текущей конфигурации, а фиксируют
  целевую typed форму для следующих срезов.

### Статус третьего среза шага 6

Третий безопасный срез ввел первые чистые domain entities без подключения к
runtime flow:

- создан пакет `tools-ci/simple_deploy/entities/`;
- добавлены immutable entities/value objects `SourceSnapshot`,
  `SourceRepositoryRevision`, `ReleaseArtifactRef`, `ReleaseBundle`,
  `ReleasePlacement` и `Release`;
- зафиксированы базовые инварианты: source snapshot непустой и без дублей
  `repo_id`, release принимает только bundle/placement своей версии, один
  release не получает второй отличающийся successful bundle, placement остается
  отдельным от bundle;
- entities не импортируются из CLI/build/deploy, не читают SQLite и не являются
  API DTO или config schema.

### Статус четвертого среза шага 6

Четвертый безопасный срез начал registry boundary без переноса SQLite
implementation:

- создан пакет `tools-ci/simple_deploy/registry/`;
- `simple_deploy.registry.state` пока является compatibility boundary поверх
  текущего `simple_deploy.release.state`;
- старый import path остается источником реализации, новый path нужен для
  постепенного перевода будущих application/query слоев;
- процессы build/deploy/CLI пока не переключались на новый path, чтобы не
  смешивать boundary introduction и behavior changes.

### Статус пятого среза шага 6

Пятый безопасный срез дал практическую роль registry boundary в read/API слое:

- добавлен модуль `tools-ci/simple_deploy/registry/queries.py`;
- сборка read models для releases, contour state, jobs, external requests и
  общего state snapshot перенесена из `web.app` в `registry.queries`;
- `web.app` оставлен HTTP/HTML/DTO adapter-ом и больше не читает
  `simple_deploy.release.state` напрямую;
- старые helper imports из `web.app` сохранены через импорт query-функций, чтобы
  не ломать переходные тесты и возможные локальные imports;
- SQLite-схема, JSON-контракт FastAPI endpoints и CLI/build/deploy поведение не
  менялись.

### Статус шестого среза шага 6

Шестой безопасный срез подчистил web boundary после переноса read queries:

- `web.app` больше не реэкспортирует внутренние query helpers вроде
  `release_read_models`;
- публичными compatibility helper-ами web-слоя остаются только
  `state_snapshot_model()`, `state_snapshot_dto()` и `state_snapshot()`;
- FastAPI endpoints продолжают использовать `registry.queries` через private
  aliases, поэтому HTTP/DTO слой не становится владельцем query API;
- JSON-контракт dashboard/API не менялся.

### Статус седьмого среза шага 6

Седьмой безопасный срез начал write/use-case boundary для registry:

- добавлен модуль `tools-ci/simple_deploy/registry/commands.py`;
- команды `set_contour_baseline`, `record_deployment_applied` и
  `record_deployment_failed` инкапсулируют запись baseline/deployment attempts
  поверх `registry.state`;
- `processes.mark` больше не пишет SQLite напрямую и делегирует state changes в
  `registry.commands`;
- чтение `release_manifest.json` осталось в process layer, поэтому registry не
  зависит от release artifacts или CLI;
- CLI-поведение `set-baseline`, `mark-applied`, `mark-failed` и SQLite-схема не
  менялись.

### Статус восьмого среза шага 6

Восьмой безопасный срез расширил write/use-case boundary на build flow:

- `registry.commands` получил команды `start_build_attempt`,
  `finish_build_attempt` и `record_release_bundle`;
- `tools-ci/builder/create_release.py` больше не импортирует
  `simple_deploy.release.state` напрямую и пишет build attempts/release record
  через `registry.commands`;
- best-effort запись failed build attempt осталась в builder-е и по-прежнему не
  маскирует исходную ошибку сборки;
- `processes.build` продолжает только запускать builder как отдельный процесс;
- CLI/builder поведение, manifest format и SQLite-схема не менялись.

### Статус девятого среза шага 6

Девятый безопасный срез закрыл оставшиеся мелкие write commands registry:

- `registry.commands` получил команды для lifecycle local jobs:
  `create_local_job`, `mark_local_job_started`, `finish_local_job`;
- добавлены команды для external TEST/PROD requests:
  `create_release_external_request`, `update_release_external_request_status`;
- команды возвращают прочитанные `JobRecord`/`ExternalRequest`, а не только id,
  чтобы application/web слои не лезли в storage API после записи;
- низкоуровневые `registry.state` functions оставлены для storage compatibility;
- SQLite-схема и существующие read/query контракты не менялись.

### Статус десятого среза шага 6

Десятый безопасный срез переключил production imports на registry boundary:

- `windows_pipeline`, builder baseline checks, jobs/contours models и release
  artifact validation импортируют `CONTOURS`, `validate_contour` и SQLite state
  helpers из `simple_deploy.registry.state`;
- legacy builder import path `builder/src/release_state.py` также смотрит в
  `registry.state`;
- `simple_deploy.release.state` пока остается compatibility implementation для
  старых imports и тестов;
- поведение CLI, builder, state schema и публичные функции не менялись.

### Статус одиннадцатого среза шага 6

Одиннадцатый безопасный срез физически перенес SQLite implementation в registry:

- реальная implementation локальной SQLite-базы теперь находится в
  `tools-ci/simple_deploy/registry/state.py`;
- `tools-ci/simple_deploy/release/state.py` стал compatibility re-export поверх
  `registry.state`;
- старые imports `simple_deploy.release.state` продолжают работать;
- `release/` больше не считается владельцем baseline, attempts, jobs и external
  requests.

### Статус двенадцатого среза шага 6

Двенадцатый безопасный срез обновил документацию границ после переноса state:

- docstring `release/__init__.py` теперь описывает только manifest/artifacts и
  compatibility path `release.state`;
- docstring `registry/__init__.py` фиксирует registry как владельца SQLite
  implementation, queries и commands;
- docstring-и manifest/artifacts уточняют, что запись operational state идет
  через registry.

### Статус тринадцатого среза шага 6

Тринадцатый безопасный срез добавил read-only adapter от текущего legacy env к typed topology:

- `runtime_topology_from_legacy_env()` строит DEV topology из уже существующих env-ключей
  без изменения `.env`, `local.secrets.env` или `windows_pipeline.local.json`;
- adapter отображает source repo paths, app/db VM, backend/frontend/database targets
  и contour-bound execution environment для `dev`;
- частичный env допускается: source topology может быть доступна до заполнения VM-ключей;
- deploy/build/CLI пока не используют эту topology для принятия решений, поэтому runtime
  поведение не менялось.

### Статус четырнадцатого среза шага 6

Четырнадцатый безопасный срез ввел application service boundary над текущими процессами:

- создан пакет `simple_deploy.application` и модуль `application.services`;
- application services `build`, `deploy`, `set_baseline`, `mark_applied` и
  `mark_failed` делегируют существующим process modules без изменения orchestration;
- совместимый Windows runner импортирует верхнеуровневые команды из application layer,
  но сохраняет старые `tools.windows_pipeline.*` patch/import paths;
- `processes` остаются владельцами текущей CLI-oriented orchestration, а application
  layer становится общей точкой подключения для будущих web/API и local jobs.

### Статус пятнадцатого среза шага 6

Пятнадцатый безопасный срез начал реальный отход process layer от `windows_pipeline`:

- созданы core-модули `simple_deploy.core.paths`, `core.commands`, `core.env`,
  `core.build_env` и `core.release_paths`;
- `windows_pipeline.py` теперь реэкспортирует эти helper-ы через imports, но больше
  не владеет их реализацией;
- `processes.build` напрямую импортирует env/build/command helper-ы из `core` и
  больше не содержит `_runner_module`;
- `processes.mark` напрямую использует `core.env`, `core.release_paths`, release
  manifest и registry commands, без импорта `simple_deploy.windows_pipeline`;
- тестовые patch paths для build/mark переведены на новых владельцев, а старые
  `tools.windows_pipeline.*` compatibility names сохранены для внешних imports.

### Статус шестнадцатого среза шага 6

Шестнадцатый безопасный срез убрал оставшиеся обратные зависимости process layer от `windows_pipeline`:

- загрузка runtime config перенесена в `config.runtime_loader`;
- построение SSH/SCP-команд, DB psql-команд, форматирование email и `run_or_raise` перенесены в `core`;
- dry-run проверки перенесены в `processes.dry_run_checks`, а `processes.dry_run` больше не содержит `_runner_module`;
- process-код DB schema/data SQL импортирует `core` helper-ы напрямую и больше не импортирует compatibility runner;
- helper-ы app deploy, HTTP healthcheck и Outlook-уведомлений перенесены в `processes.app_deploy`,
  `processes.healthcheck` и `processes.notifications`;
- `processes.deploy` импортирует process/core/release/registry зависимости напрямую, без `simple_deploy.windows_pipeline`;
- `simple_deploy.windows_pipeline` остается CLI/logging compatibility-модулем и re-export host-ом для старых
  import paths `tools.windows_pipeline.*`.

Следующий практический срез: дальше уменьшать compatibility-модуль, переводя re-export-only test patch paths
на прямых владельцев и перенося оставшиеся CLI/logging детали в сторону `simple_deploy.cli.windows_pipeline`,
без изменения публичной точки входа `tools-ci/tools/windows_pipeline.py`.

### Статус семнадцатого среза шага 6

Семнадцатый безопасный срез зафиксировал правило для доменных справочников:

- доменный тип справочника представлен только enum-классом: `ArtifactKindEnum`,
  `JobKindEnum`, `ReleaseTriggerTypeEnum` и аналогичными `*Enum`;
- alias-типы без `Enum` вроде `ArtifactKind`, `JobKind` и
  `ReleaseTriggerType` удалены, чтобы в коде не было второго имени для того же
  доменного понятия;
- tuples вроде `RELEASE_TRIGGER_TYPES`, `JOB_STATUSES` и
  `SERVICE_STEP_PHASES` строятся через `Enum.get_values()` и содержат строковые
  значения для CLI choices, ручных storage-проверок и документации допустимых
  значений;
- `Literal[...]` не используется как доменный тип; он допустим только на
  границах примитивного ввода, где модель принимает строку, например
  `JobContourScope` для contour scope local job;
- enum-like значения больше не нормализуются через `strip`/`lower`: вход обязан
  совпадать со значением справочника точно;
- отсутствие технического release trigger фиксируется значением
  `ReleaseTriggerTypeEnum.UNDEFINED`, а не `None`.

### Статус восемнадцатого среза шага 6

Восемнадцатый безопасный срез описал смысловые строковые primitive-поля:

- добавлен модуль `simple_deploy.types.fields` с `Annotated[..., Field(description=...)]`
  для timestamp-ов, JSON payload/artifacts, log path, external id, source refs,
  artifact paths и текстов ошибок/вывода;
- `ReleaseVersionString`, `OptionalBuildVersionString`, `CommitShaString`,
  `OptionalCommitShaString` и `RepoId` получили `Field(description=...)`
  поверх уже существующих `StringConstraints`;
- read/API-модели state, release entities, registry records, command results и
  artifact records используют описанные primitive aliases вместо голых `str`
  там, где поле является частью контракта;
- строковые `*Id` aliases документируют ожидаемый формат и смысл: например,
  `RepoId` - это стабильный slug логического repository (`backend`,
  `frontend-app`), а не числовой database id, URL или filesystem path;
- `ReleaseVersionString` и `BuildVersionString` имеют одинаковый строковый
  формат, но разный смысл: release version идентифицирует release resource, а
  build version является техническим ключом собранного release bundle; сам
  bundle - отдельная структура с artifacts, source snapshot и metadata;
- `DeploymentTargetRoleEnum` документируется как справочник ролей deploy
  entrypoint-ов: это VM/server targets внутри landscape, а не компоненты и не
  CLI entrypoints;
- `JobContourScope` заменяет прежний optional contour: пустая строка означает
  unscoped local job, например build без deploy-контура, а contour-scoped jobs
  вроде deploy/set_baseline/mark_* требуют реальный contour;
- enum-поля не заменялись на `Annotated[str, ...]`: справочники остаются
  `*Enum`, а `Literal[...]` используется только для примитивных boundary-случаев
  вроде contour scope в local job;
- добавлены тесты, которые проверяют, что descriptions реально попадают в
  JSON schema Pydantic-моделей и `TypeAdapter`.

### План девятнадцатого среза шага 6: request boundary application layer

Следующий срез убирает `argparse.Namespace` из application layer без
одновременной переписи всех process modules:

- `argparse.Namespace` остается деталью CLI adapter-а и не проходит за границу
  `simple_deploy.windows_pipeline`;
- для каждой операторской команды появляется request DTO в
  `simple_deploy.application.requests`;
- CLI adapter преобразует разобранные аргументы в те же request DTO, которые
  сможет создавать будущий web/API или local job runner;
- application services принимают request DTO и больше не зависят от `argparse`;
- текущие process modules временно получают namespace-like объект через
  приватный adapter внутри `application.services`, пока их собственный контракт
  не будет переписан на typed input;
- `pipeline` становится application use case: он явно строит `DryRunRequest`,
  `BuildRequest` и `DeployRequest`, а не мутирует CLI args;
- deprecated no-op флаги CLI, например `--include-data-sql`, не становятся
  частью application request contract; adapter сохраняет CLI-совместимость и
  протаскивает только реальные переключатели поведения.

Целевая форма слоя после среза:

```text
CLI argv -> argparse.Namespace -> CLI request adapter
                               -> application request DTO
Web/API payload --------------/
                               -> application service
                               -> temporary process input adapter
                               -> current process module
```

### Статус девятнадцатого среза шага 6

Девятнадцатый безопасный срез применил request boundary для application layer:

- добавлен модуль `simple_deploy.application.requests` с Pydantic request DTO
  для `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`,
  `mark-applied` и `mark-failed`;
- добавлен `simple_deploy.cli.requests`, который преобразует
  `argparse.Namespace` в application request DTO;
- `application.services` больше не импортирует `argparse` и принимает только
  request DTO;
- временное преобразование request DTO в namespace-like input для текущих
  process modules находится внутри приватного `_process_args`;
- `pipeline` перенесен в application service как use case
  `dry-run -> build -> deploy latest` и больше не мутирует CLI args;
- `simple_deploy.windows_pipeline` остался compatibility runner-ом: `main()`
  собирает request DTO перед dispatch, а старые импортируемые функции
  `build`, `deploy`, `pipeline`, `set_baseline`, `mark_applied` и
  `mark_failed` принимают legacy `Namespace` только на этой внешней границе и
  сразу преобразуют его в DTO;
- deprecated no-op `--include-data-sql` не включен в application request
  contract; сохранен только реальный переключатель
  `skip_data_sql_artifacts`.

### Статус двадцатого среза шага 6

Двадцатый безопасный срез уменьшил `simple_deploy.windows_pipeline` до
тонкого compatibility runner-а:

- `tests/test_windows_pipeline_permissions.py` переведен с re-export-only
  imports на прямых владельцев в `core`, `config`, `release` и `processes`;
- через `tools.windows_pipeline` в тестах оставлены только CLI/wrapper
  контракты: `parse_args`, `main`, process wrappers и dispatch patch paths;
- `tests/test_runtime_config_model.py` импортирует typed runtime loader из
  `simple_deploy.config.runtime_loader`, а не через старый runner facade;
- из `simple_deploy.windows_pipeline` удалены re-export imports helper-ов,
  которые больше не нужны для внутренних тестов;
- отдельный `ruff` per-file ignore для `windows_pipeline.py` удален, потому что
  модуль больше не содержит intentional `F401`/`E402` re-export blocks.

### Статус двадцать первого среза шага 6

Двадцать первый безопасный срез перенес оставшийся CLI/logging/dispatch слой в
целевой CLI package:

- `simple_deploy.cli.windows_pipeline` стал владельцем `parse_args`, `main`,
  `tee_output` и legacy wrappers команд поверх application request DTO;
- `tools-ci/tools/windows_pipeline.py` остался публичной точкой запуска, но
  теперь импортирует `simple_deploy.cli.windows_pipeline` напрямую;
- `simple_deploy.windows_pipeline` превращен в deprecated compatibility shim
  для старых Python imports и больше не содержит собственной runner-логики;
- CLI behavior tests переведены на `simple_deploy.cli.windows_pipeline`, а
  `tools.windows_pipeline` покрыт только smoke-проверкой исторического import
  path;
- поведение CLI-команд, формат аргументов, logging contract и application
  dispatch не менялись.

### Отложенное улучшение: data SQL set_default artifacts

Текущая реализация генерирует `kind=set_default` внутри update artifacts:

- `run_all_update_parallel_*.sh` содержит `set_default` задачи, но пропускает
  их по умолчанию и включает только при `SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT=1`;
- `run_all_update_sequential_*.sql` содержит `set_default` без runtime-фильтра,
  поэтому ручной emergency fallback через `psql -f` применит defaults.

Это рабочее, но слишком неявное поведение. Целевое улучшение: разделить
`update` и `set_default` на уровне artifacts и deploy chain:

- update artifacts должны содержать только `kind=update`;
- set_default должен собираться в отдельные artifacts/entrypoints;
- `--include-set-default-sql` должен добавлять отдельный set_default step в
  цепочку выполнения, а не менять поведение update runner-а через env;
- ручной запуск update runner-а должен быть безопасен без знания внутреннего
  фильтра set_default.
