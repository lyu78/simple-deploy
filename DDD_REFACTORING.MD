# DDD-рефакторинг simple-deploy

Дата фиксации черновика: 2026-06-10.

## Зачем нужен этот документ

После шага 5 код уже начал раскладываться по процессам, но язык модели все еще
смешивает несколько разных понятий: релиз как желание обновиться, релиз как
набор архивов, релиз как запись в SQLite и релиз как состояние контуров.

Цель этого документа - зафиксировать общий доменный язык перед переходом к
Pydantic DTO и следующим переносам модулей. Это не финальная схема БД и не
обязательство немедленно переименовать весь код. Документ задает направление,
по которому можно постепенно отделять доменные сущности, DTO, хранилище и
прикладные процессы.

## Главная доменная идея

Система начинается не с архива и не с команды `deploy`, а с внешней потребности
обновиться.

Эту потребность может выразить owner, teamlead, другой ответственный человек
или автоматизация. Иногда инициатор уже знает номер релиза, иногда только
фиксирует желание "пора обновиться". Если номер не передан явно, система
назначает его по собственной политике нумерации.

Релиз может:

- быть собран и размещен на всех контурах;
- быть собран и размещен только на одном контуре;
- быть собран, но не размещен нигде;
- остаться в истории как неуспешная или отложенная попытка;
- требовать ручного подтверждения для отдельных контуров.

Рабочая формулировка:

> Релиз - это управляемая единица поставки, созданная из внешней потребности
> обновления, получившая номер, имеющая один или несколько build bundle-ов и
> историю размещения по контурам.

Важно: release bundle и release registry state не являются самим релизом.
Bundle - материальный результат сборки. Registry state - локальная история и
операционное состояние.

## Согласованный словарь

### ReleaseIntent / ReleaseRequest

Внешнее желание начать обновление.

Содержит:

- инициатора;
- причину или описание;
- необязательный желаемый номер релиза;
- необязательную целевую source selection;
- необязательный список целевых контуров;
- время создания;
- исходный канал: CLI, web/API, automation, manual import;
- trigger type, если intent создан автоматически.

Если номер релиза не передан, application use case должен назначить его через
политику нумерации.

`ReleaseIntent` стоит хранить как отдельную persisted entity, а не только как
входной DTO. Это сохраняет исходное желание обновиться, даже если build позже
упал, был отложен или превратился в заявку на внешний контур.

Дефолты первого этапа:

- инициатор по умолчанию - `teamlead`;
- причина по умолчанию - "плановое обновление контура после обновления
  продуктовых фич";
- целевые контуры по умолчанию задаются application use case, а не самим DTO:
  текущий ручной `deploy` может работать с одним контуром, будущий scheduled
  release может планировать несколько контуров;
- если intent создан scheduler-ом или webhook-ом, технический источник
  фиксируется отдельно в `trigger type`, но доменный initiator все равно может
  оставаться `teamlead`, пока не появится отдельная модель ownership.

Поддерживаемые источники intent в целевой модели:

- `manual` - ручной запуск через CLI или будущий web/API;
- `backend_branch_push` - push в заранее настроенную backend-ветку;
- `backend_release_branch_push` - создание или обновление release-ветки backend;
- `scheduled` - запуск по расписанию: например, в 04:00 пятницы система
  подтягивает настроенные ветки из репозиториев и запускает весь release flow.

Время scheduled release нужно считать по явно заданной runtime timezone. Пока
отдельная настройка timezone не введена, рабочее допущение - локальная timezone
окружения, где запущен scheduler.

### Initiator / Owner

Субъект, который инициировал release intent.

На первых этапах это может быть простая строка: имя, email, логин или
служебное значение вроде `automation`. Позже это можно расширить до отдельной
модели пользователя или интеграции.

### ReleaseVersion

Value object номера релиза.

Отвечает за валидацию формата и сравнение, но не должен знать, как собирать
архивы или как двигать контуры. Политика генерации следующего номера должна
жить отдельно, потому что она зависит от правил проекта и истории.

Рабочий формат номера релиза сохраняет текущую схему:
`<BUILD_VERSION_BASE>.<DDMMYYYY_HHMM>`, например `1.0.3.30052026_1437`.
`BUILD_VERSION_BASE` хранит продуктовую часть версии, а дата и время дают
уникальность конкретного релиза. Третья цифра в base version меняется при
крупном глобальном обновлении.

### SourceSelection / SourceSnapshot

`source revision` в ранней формулировке лучше считать не одним commit-ом, а
снимком исходников по всем репозиториям, которые участвуют в релизе.

`SourceSelection` - то, что просит intent до разрешения в конкретные commit-ы:

- backend branch, tag или commit;
- frontend branch, tag или commit;
- дополнительные репозитории или SQL/migration источники, если они появятся;
- набор source repositories, которых сейчас может быть два, но модель должна
  выдерживать три, четыре и больше репозиториев;
- политика выбора веток по умолчанию для scheduled release.

`SourceSnapshot` - immutable результат разрешения selection:

- для каждого source repository: repo id, ref, фактический commit SHA и origin,
  из которого этот commit был получен;
- время разрешения;
- trigger/event metadata, если snapshot получен из webhook или scheduler.

Для ручного запуска source selection может приходить из CLI/API или из
дефолтной runtime policy. Для push-trigger-а backend commit обычно известен из
события, а остальные репозитории выбираются по политике. Для scheduled release
в 04:00 пятницы система должна сначала подтянуть настроенные ветки, затем
зафиксировать `SourceSnapshot` и только после этого запускать build.

Дефолтные ветки для scheduled release на первом этапе - `dev` во всех
участвующих репозиториях.

### SourceRepository / SourceOrigin

`SourceRepository` - логический исходный репозиторий продукта.

Важно: source repository не равен машине, контуру или deploy-компоненту. Один
репозиторий может давать несколько компонентов, один компонент может собираться
из нескольких репозиториев, а deploy одного компонента может затрагивать
несколько машин.

Содержит:

- стабильный repo id;
- роль в продукте: backend, frontend, migrations, shared library или другая;
- default origin;
- fallback origins или mirrors;
- правила выбора веток по умолчанию;
- техническую auth policy, если она нужна для доступа.

`SourceOrigin` - конкретный источник Git-данных: primary remote, mirror,
локальный bare clone или временный emergency clone.

Default origin можно считать константой конфигурации, но в экстренной ситуации
тимлид может изменить origin через настройки. На первом этапе достаточно
уметь изменить конфиг и зафиксировать в релизе, на каких origins он был
собран:

- какой origin использован в конкретном `SourceSnapshot`;
- какой commit SHA в итоге попал в сборку.

Если внешний источник упал и система пошла в клон, это не должно менять
доменный номер релиза. Воспроизводимость обеспечивается тем, что
`SourceSnapshot` фиксирует фактический origin и commit SHA.

Отдельное SQLite-событие для изменения origin не является обязательным
требованием первого этапа. Его можно добавить позже, если потребуется история
изменений настроек, а не только воспроизводимость конкретного релиза.

### Release

Основная доменная сущность поставки.

Содержит:

- номер релиза;
- ссылку на исходный intent/request;
- текущий lifecycle status;
- выбранный source snapshot, если он уже определен;
- связь с build attempts и успешными bundle-ами;
- сводное представление размещения по контурам.

Release не должен напрямую выполнять SSH, собирать frontend или писать файлы.
Этим занимаются application services/processes. Release хранит смысловую
модель: что именно поставляется и в каком состоянии находится поставка.

### ReleaseStatus

Статусная модель релиза должна быть ближе к ETL pipeline: каждый статус
фиксирует прохождение крупной стадии, а подробности ошибки живут в
`BuildAttempt`, `DeploymentAttempt` или `ReleasePlacement`.

Предлагаемый минимальный набор:

- `initiated` - intent принят, релиз создан, номер может быть уже назначен;
- `source_resolved` - source selection разрешен в immutable source snapshot;
- `build_running` - сборка bundle-а запущена;
- `build_succeeded` - bundle успешно собран и manifest записан;
- `build_failed` - сборка неуспешна из-за ошибки build pipeline или выбранного
  source snapshot;
- `source_invalid` - сборка невозможна, потому что source repository/ref не
  соответствует ожидаемому контракту;
- `dev_deploy_running` - размещение на DEV запущено;
- `dev_deploy_succeeded` - релиз успешно размещен на DEV;
- `dev_deploy_failed` - размещение на DEV упало;
- `test_request_created` - после DEV сформирована заявка на TEST;
- `test_confirmed` - внешнее размещение на TEST подтверждено и зафиксировано;
- `prod_request_created` - после подтвержденного TEST сформирована заявка на PROD;
- `prod_confirmed` - внешнее размещение на PROD подтверждено и зафиксировано;
- `cancelled` - intent/release остановлен вручную до завершения flow;
- `archived` - релиз закрыт для активных операций и остается только в истории.

Сводный `ReleaseStatus` не должен терять контурную детализацию. На каких
контурах релиз размещен, ожидает заявки или упал, хранит `ReleasePlacement`.
PROD flow строится на TEST-заявках: нельзя собрать или продвинуть PROD без
успешной TEST-заявки и подтверждения размещения на TEST.

### ReleaseBundle

Материализованный самодостаточный результат успешной сборки.

Содержит:

- номер релиза;
- директорию bundle-а;
- manifest;
- список artifacts;
- source snapshot и metadata сборки;
- время создания;
- ссылку на build attempt.

Bundle должен считаться immutable после успешной сборки. Если сборка
повторяется для того же release version и того же source snapshot, вся цепочка
должна быть идемпотентной. Отличаться может только техническое время генерации
и производные timestamps.

Один `Release` имеет ровно один успешный `ReleaseBundle`. Если после успешного
bundle-а требуется доработка ПО или новые commit-ы, это уже новый релиз с новым
номером. Неуспешные build attempts остаются историей того же intent/release до
момента успешной сборки или отмены.

### Component / DeployableComponent

`Component` - логическая часть продукта, которую можно собрать, упаковать или
разместить отдельно.

Component не равен source repository и не равен машине. В текущей системе
монолит еще может выглядеть как один backend, но целевая модель должна
выдерживать распил на несколько компонентов.

Примеры компонентов:

- backend;
- frontend;
- database.

Начальный набор components до распила монолита: backend, frontend, database.
Более мелкие компоненты вроде worker, reporting, cache, s3 или maintenance stub
не вводим как доменные components, пока они не понадобятся в реальном flow.

Компонент может:

- собираться из одного или нескольких source repositories;
- производить один или несколько artifacts;
- размещаться на одной или нескольких машинах;
- иметь разный deployment layout на `dev`, `test` и `prod`.

### Artifact

Отдельный файл внутри bundle-а.

Примеры:

- backend archive;
- frontend archive;
- DB schema SQL archive;
- DB data insert SQL archive;
- DB data update_parallel SQL archive;
- maintenance stub archive;
- `release_manifest.json`.

Artifact описывает имя, тип, локальный путь, целевой remote path и назначение.
Он не должен знать бизнес-правила продвижения релиза.

Минимальные оси классификации artifact:

- component id, к которому относится artifact;
- artifact kind: backend, frontend, db_schema, db_data, maintenance_stub,
  manifest или другой тип;
- scope: `shared`, `contour_specific`, `target_specific`;
- список контуров или deployment targets, если artifact не общий;
- признак переносимости внутри release bundle.

Контуронезависимые artifacts должны собираться один раз и переиспользоваться на
разных контурах. Контурозависимые artifacts допустимы, но их scope должен быть
явно записан в manifest, чтобы deploy не взял архив не для своего контура.

Текущее разделение:

- contour-specific artifacts: DB schema migrations и frontend builds;
- shared artifacts: backend archive, DB data insert SQL archive и DB data
  update SQL archive.

Если artifact помечен как contour-specific, deploy должен выбирать его только
для своего контура. Если для контура нет подходящего artifact или найден
artifact другого контура, это hard fail до размещения. Иными словами, чужой
контурный bundle не должен "почти подойти": он считается неподходящим по
контракту manifest/resolver.

### Manifest

Переносимое описание конкретного bundle-а.

Manifest должен оставаться частью release bundle и не зависеть от локальной
SQLite-базы. Его задача - позволить понять, что именно собрано, из каких
commit-ов, с какой SQL metadata и с каким набором artifacts.

### ReleaseChangeSet

Производная информация о том, что попало в релиз.

Сюда стоит подтягивать:

- список commit-ов по репозиториям;
- диапазоны commit-ов относительно предыдущего baseline или предыдущего
  успешного bundle-а;
- закрытые issue/task-номера, если они доступны из issue tracker-а или
  извлекаются из commit messages;
- краткое release notes/read model для owner-а и контуров TEST/PROD.

Change set не должен заменять `reason`: причина объясняет, зачем релиз
инициирован, а change set показывает, что фактически попало в сборку.
Если issue tracker недоступен, отсутствие закрытых issue не должно ломать
release flow, пока отдельная policy не сделает это обязательным quality gate.
Закрытые issues и commits не ограничивают право инициатора создать релиз:
простое желание переделать релиз остается валидной причиной.

Git range для change set на первом этапе: от последнего успешно
сгенерированного release bundle, который был размещен на DEV, до текущего
source snapshot.

### BuildAttempt

Попытка собрать bundle для релиза.

Содержит:

- номер релиза;
- source snapshot;
- статус: started, succeeded, failed;
- timestamps;
- ошибку, если сборка упала;
- путь к bundle-у, если сборка успешна;
- технический лог или ссылку на job.

BuildAttempt не равен Release. У одного релиза может быть несколько попыток
сборки, если первая упала или сборку повторили.

Для ошибок сборки нужно различать минимум две причины:

- `failed_build` - сборка упала из-за текущего состояния кода, тестов,
  зависимостей или иных проблем, которые относятся к выбранному source snapshot;
- `invalid_source_contract` - репозиторий или выбранный ref не соответствует
  ожидаемому контракту сборки, например пропали обязательные скрипты,
  директории или metadata.

Если для исправления требуется доработка ПО и новые commit-ы, это должно
переходить в новый релиз, а не перегенерировать старый release bundle с другим
содержимым.

### Contour

Value object контура размещения.

На текущем этапе известны `dev`, `test`, `prod`. Контур должен валидироваться
как доменное значение, а не как произвольная строка, размазанная по коду.

### DeploymentTarget / DeploymentLandscape

`DeploymentTarget` - конкретная точка размещения: VM, host, service slot,
рабочая директория, набор systemd/nginx/unit настроек или другой технический
адрес доставки.

Важное правило: deployment target не равен source repository и не равен
component. Сейчас машин фактически может быть около шести, а репозиториев два;
после распила монолита количество компонентов и количество машин все равно не
обязаны совпадать.

Начальный словарь deployment target roles:

- backend;
- frontend;
- database;
- cache;
- reporting;
- s3.

Это именно роли target-ов/машин, а не окончательный список components.

`DeploymentLandscape` - топология размещения для конкретного контура.

Содержит:

- contour;
- список deployment targets;
- mapping component -> deployment targets;
- контурные runtime overrides;
- service step policy;
- порядок остановки, распаковки, миграций, старта и healthcheck;
- правила выбора contour-specific artifacts.

Конфигурация landscape не меняется между релизами. Это runtime/config модель
контура, а не часть release bundle. Если инфраструктура меняется, сначала
обновляется конфигурация landscape, затем новые релизы используют уже
актуальную топологию.

Текущая топология:

- DEV: две машины; backend/frontend операции совмещены на одной машине;
- TEST: под контур заготовлены отдельные машины;
- PROD: под контур заготовлены отдельные машины.

DEV, TEST и PROD могут иметь разные landscapes. Поэтому `Contour` отвечает за
доменное имя и правила контура, а `DeploymentLandscape` - за фактическую форму
размещения.

### VirtualMachine / ExecutionEnvironment

`VirtualMachine` - инфраструктурный ресурс, на который можно подключиться для
deploy, проверки, тестового пайплайна или ручной диагностики.

VM не равна контуру и не равна релизу. Одна VM может быть частью
`DeploymentLandscape`, а может использоваться как отдельное окружение
выполнения тестового pipeline.

Минимально VM описывает:

- стабильный machine id;
- роль: app, database, cache, reporting, s3 или другая;
- hostname/address;
- auth profile;
- рабочие директории;
- ограничения доступа и допустимые операции.

`ExecutionEnvironment` - окружение выполнения pipeline-операций над bundle-ом.
Это может быть:

- contour-bound окружение, связанное с DEV/TEST/PROD landscape;
- sandbox/test окружение на app VM;
- временное окружение для проверки bundle-а без изменения контуров.

Для тестовых pipeline-ов важно отдельное правило: работа с release bundle на
app VM не должна автоматически считаться deploy на DEV и не должна менять
`ContourState`, `ReleasePlacement` или DEV baseline. Такие операции фиксируются
как validation/test attempts и jobs.

### BundleValidationAttempt

Попытка выполнить проверки release bundle в `ExecutionEnvironment`.

Содержит:

- номер релиза;
- ссылку на release bundle;
- execution environment;
- используемые machines;
- набор проверок или сценарий;
- статус: started, succeeded, failed, cancelled;
- timestamps;
- ошибку и ссылку на log/job.

`BundleValidationAttempt` не равен `DeploymentAttempt`: он может выполнять
SSH-команды, распаковывать или инспектировать bundle на app VM, но не двигает
baseline контура и не подтверждает размещение релиза на DEV/TEST/PROD.

### DeploymentAttempt

Попытка разместить релиз на конкретном контуре.

Содержит:

- номер релиза;
- контур;
- deployment landscape из текущей runtime-конфигурации контура;
- режим deploy: full, app-only, manual mark;
- статус: started, succeeded, failed;
- timestamps;
- ошибку, если размещение упало;
- ссылку на job или лог;
- факт изменения baseline.

DeploymentAttempt фиксирует попытку и ее результат. Он не обязан быть текущим
состоянием контура.

### ReleasePlacement / ContourPlacement

Состояние размещения конкретного релиза на конкретном контуре.

Это связь между Release и Contour: запланирован, ожидает ручного действия,
размещается, размещен, упал, пропущен, отменен. Эта сущность полезна, если мы
хотим видеть матрицу "релиз x контуры", а не только историю attempts.

На первом этапе ее можно не вводить в код, но стоит держать в целевой модели.
Принятое направление: `ReleasePlacement` нужно хранить явно, потому что для
релиза важно видеть, на каких контурах он был размещен, ожидает размещения или
требует ручного подтверждения.

### ContourState

Операционное состояние контура.

Отвечает на вопрос: какой релиз сейчас считается последним успешно
размещенным на контуре.

Это не сам Release и не сам DeploymentAttempt. Это baseline/read model,
который обновляется только после успешного подтверждения размещения или ручной
команды `mark-applied`.

### ExternalApprovalRequest

Заявка или внешнее ручное действие для TEST/PROD.

Нужна для сценариев, где simple-deploy не выполняет deploy напрямую, а готовит
package/request и ждет внешнего подтверждения. Эта сущность связана с Release,
Contour и, возможно, ReleaseBundle.

Базовый TEST/PROD flow:

1. Получен успешный release bundle.
2. Bundle успешно размещен на DEV.
3. Сформирована заявка на TEST.
4. Дальше выполняется внешняя административная процедура.
5. После подтверждения успешного размещения simple-deploy фиксирует результат
   и обновляет placement/contour state.

### Job

Локальная долгоживущая операция.

Job нужен для CLI/web/API orchestration: build, deploy, dry-run, validation
pipeline, подготовка заявки, проверка статуса. Job не является доменным
релизом, а является инфраструктурной оболочкой выполнения use case.

## Предварительные aggregate roots

На старте не нужно жестко вводить все агрегаты в код. Но полезно держать такие
границы:

- `Release` - корень для intent, версии, lifecycle и связи с bundle/placement;
- `ReleaseBundle` - корень для manifest, components и artifacts конкретной
  сборки;
- `ContourState` - отдельный operational aggregate/read model;
- `DeploymentLandscape` - read model или aggregate конфигурации размещения
  конкретного контура;
- `ExecutionEnvironment` - aggregate/read model для окружений выполнения
  тестовых и операционных pipeline-ов;
- `Job` - инфраструктурный aggregate для асинхронных операций;
- `ExternalApprovalRequest` - отдельный aggregate для ручных TEST/PROD flow.

Риск, которого нужно избегать: превратить `Release` в новый монолитный объект,
который знает про архивы, SQLite, SSH, сервисы, email и web jobs одновременно.

## Предлагаемые bounded contexts

### Release Management

Создание release intent, назначение номера, lifecycle релиза, связь с
инициатором, source selection и source snapshot.

### Bundle Building

Сборка самодостаточного release bundle, components, manifest, artifacts,
source snapshot, release change set и build attempts.

### Deployment / Placement

Размещение bundle-а на контурах, deployment landscapes, deployment targets,
deployment attempts, placement status, manual mark и обновление baseline.

### Validation / Test Pipelines

Проверки release bundle в execution environments: запуск сценариев на app VM,
инспекция bundle-а, smoke/validation jobs и фиксация результатов без изменения
DEV/TEST/PROD baseline.

### Source Registry

Описание source repositories, origins, mirrors, teamlead-controlled origin
overrides и фиксация того, откуда были получены commits для конкретного
source snapshot.

### Contour Registry

Текущее состояние контуров и история успешных baseline-ов.

### Operations

Jobs, logs, execution status, API/CLI orchestration, validation attempts и
долгие операции.

## Как это соотносится с текущими модулями

Текущий `tools-ci/simple_deploy/release` смешивает несколько будущих областей:

- `release/manifest.py` ближе всего к `ReleaseBundle` и `Manifest`;
- `release/artifacts.py` ближе всего к `ReleaseBundle`, `Component` и `Artifact`;
- `release/state.py` ближе к `Contour Registry`, `BuildAttempt`,
  `DeploymentAttempt`, `Job` и `ExternalApprovalRequest`;
- commits и closed issues в будущем должны стать `ReleaseChangeSet`, а не
  частью произвольного текстового описания релиза;
- текущие env/runtime настройки частично описывают будущие
  `DeploymentLandscape`, `DeploymentTarget`, `SourceRepository`,
  `SourceOrigin`, `VirtualMachine` и `ExecutionEnvironment`, но пока эти
  понятия не отделены от runner-а;
- `processes/*` уже похожи на application use cases;
- `windows_pipeline.py` пока остается compatibility runner-ом и holder-ом
  helper-ов, которые еще не получили чистые доменные границы.

Возможная будущая структура реализации, не обязательная для немедленного
переноса:

```text
simple_deploy/
  types/
    release.py
    contour.py
    artifacts.py
    components.py
    attempts.py
    jobs.py
  entities/
    release.py
    bundle.py
    source.py
    changes.py
    component.py
    contour.py
    landscape.py
    environment.py
    attempts.py
    jobs.py
  models/
    state.py
    release.py
    bundle.py
    placement.py
    validation.py
  dto/
    release.py
    bundle.py
    source.py
    changes.py
    component.py
    landscape.py
    environment.py
    attempts.py
    state.py
  configs/
    runtime.py
    sources.py
    components.py
    landscapes.py
    machines.py
  environments/
    registry.py
    machines.py
  sources/
    registry.py
    origins.py
  registry/
    sqlite.py
    queries.py
  bundles/
    manifest.py
    artifacts.py
    resolver.py
  processes/
    build.py
    deploy.py
    dry_run.py
    mark.py
    data_sql.py
```

В этой структуре слово "domain" остается архитектурным термином в
документации, но не названием пакета реализации. Чистые доменные сущности
лежат в `entities`, а общие типы и справочники - в `types`.

## Ответственность слоев данных

### Types

`types` содержит enum-ы, справочники, custom primitive types и простые
ограниченные значения без бизнес-логики.

Примеры:

- `ContourCode`;
- `ComponentId`;
- `ArtifactKind`;
- `ArtifactScope`;
- `DeploymentTargetRole`;
- `ReleaseTriggerType`;
- `ReleaseStatus`;
- `AttemptStatus`;
- `JobStatus`;
- `SourceOriginKind`;
- `ReleaseVersionString`;
- `CommitSha`;
- `RepoId`;
- `MachineId`.

`types` может проверять формат или допустимый набор значений, но не должен знать
про SQLite, FastAPI, SSH, файлы, порядок deploy или правила продвижения релиза.

### Entities

`entities` содержит чистые DDD entities и value objects: `Release`,
`ReleaseBundle`, `SourceSnapshot`, `ReleasePlacement`, `DeploymentLandscape` и
другие сущности, которые держат доменные инварианты.

Entities не являются API response, SQLite row или Pydantic configs schema.

### Models

`models` содержит внутренние application/read/storage-facing модели. Это форма
данных между registry/query/use case/presentation слоями: snapshot состояния,
списки attempts, матрица размещения, validation results.

Models могут быть Pydantic-моделями, но они не являются внешним контрактом API.

### DTO

`dto` содержит request/response DTO для внешних границ: HTTP API, CLI JSON,
будущая web-морда и интеграции.

DTO поддерживают внешний контракт и могут быть плоскими или удобными для
клиента. Они не должны становиться доменными сущностями.

### Configs

`configs` содержит Pydantic-схемы конфигурации и загрузчики runtime/env/json.

Configs отвечают за структурную валидацию конфигурации:

- обязательные поля;
- дефолты;
- список source origins;
- mapping component -> deployment target;
- описание virtual machines;
- описание execution environments;
- корректность artifact scope в конфигурации;
- связность runtime-настроек.

Configs не принимают бизнес-решения: например, "можно ли продвигать PROD"
проверяется в entities/application services, а не в configs schema.

## Принцип перехода к Pydantic

Pydantic стоит использовать в нескольких слоях, но с разными именами и
ответственностью:

- `types` - строгие enum-ы и primitive constrained types;
- `configs` - схемы и валидация конфигурации;
- `models` - внутренние read/application/storage-facing модели;
- `dto` - внешние request/response контракты.

DTO стоит вводить на внешних границах системы, а не вместо доменной модели.

Хорошие первые DTO:

- `CreateReleaseRequestDto`;
- `ReleaseTriggerDto`;
- `SourceSelectionDto`;
- `SourceSnapshotDto`;
- `SourceRepositoryDto`;
- `SourceOriginDto`;
- `ReleaseDto`;
- `ReleaseBundleDto`;
- `ComponentDto`;
- `ArtifactDto`;
- `ReleaseChangeSetDto`;
- `BuildAttemptDto`;
- `DeploymentAttemptDto`;
- `DeploymentLandscapeDto`;
- `DeploymentTargetDto`;
- `VirtualMachineDto`;
- `ExecutionEnvironmentDto`;
- `BundleValidationAttemptDto`;
- `ContourStateDto`;
- `JobDto`;
- `ExternalApprovalRequestDto`.

Границы применения DTO:

- CLI аргументы после парсинга;
- HTTP request/response в будущем API;
- webhook payload для push-trigger-ов;
- scheduler payload для релиза по расписанию;
- runtime-конфигурация source origins и deployment landscapes;
- runtime-конфигурация virtual machines и execution environments;
- сериализация данных из SQLite;
- данные для read-only dashboard;
- переносимые manifest/read models.

Доменные правила лучше держать не в DTO и не в configs, а в entities или
application services:

- назначение номера релиза;
- разрешение source selection в immutable source snapshot;
- выбор primary/fallback origin и фиксация фактически использованных origins в
  `SourceSnapshot`;
- сбор release change set из Git range и issue tracker-а;
- допустимые переходы статусов;
- сопоставление components с deployment targets конкретного контура;
- выбор execution environment для тестового pipeline;
- фиксация bundle validation без изменения `ContourState` и `ReleasePlacement`;
- выбор bundle-а для deploy;
- выбор shared или contour-specific artifact для deployment target;
- разрешение deploy на конкретный контур;
- фиксация baseline после успешного размещения;
- best-effort запись failed attempts.

## Предлагаемый порядок миграции

1. Зафиксировать этот документ и обсудить спорные места.
2. Добавить минимальные Pydantic DTO для read-only state/API без изменения
   бизнес-логики.
3. Разделить в именах `release bundle` и `release registry/state`, не двигая
   файлы широким переносом.
4. Ввести `types` и первые models/value objects для `SourceSelection`, `SourceSnapshot`,
   `ReleaseVersion` и `Contour`.
5. Ввести read-only models/configs для `SourceRepository`, `SourceOrigin`, `Component`,
   `DeploymentLandscape` и `DeploymentTarget` поверх текущей runtime
   конфигурации.
6. Ввести read-only models/configs для `VirtualMachine`, `ExecutionEnvironment` и
   `BundleValidationAttempt`, чтобы тестовые pipeline-ы могли работать с
   bundle-ом без влияния на DEV contour state.
7. Добавить read-only модель `ReleaseChangeSet` поверх Git/manifest данных без
   обязательной интеграции с issue tracker-ом.
8. Явно записывать artifact scope в manifest/read model: shared,
   contour-specific или target-specific.
9. Вынести SQLite registry из `release/state.py` в более точную область.
10. Постепенно заменить словари и произвольные строки на `types`, `models`,
    `dto` и `configs` на границах процессов.
11. Только после стабилизации языка двигать директории и публичные module paths.

## Принятые решения по открытым вопросам

1. Один `Release` имеет ровно один успешный `ReleaseBundle`.
2. Перегенерация при том же release version и том же source snapshot должна быть
   идемпотентной. Если нужны новые commit-ы или доработка ПО, это новый релиз.
3. `BuildAttempt` должен различать обычный failed build и невалидный source
   contract, например когда в репозитории пропали обязательные скрипты.
4. `ReleaseIntent` хранится отдельно как persisted entity.
5. `ReleasePlacement` нужен как отдельная data structure: релиз должен явно
   знать, на каких контурах он размещен или ожидает размещения.
6. Рабочий формат версии: `<BUILD_VERSION_BASE>.<DDMMYYYY_HHMM>`, например
   `1.0.3.30052026_1437`; третья цифра base version меняется при крупном
   глобальном обновлении.
7. TEST/PROD boundary: успешный bundle, успешный deploy на DEV, формирование
   заявки на TEST, внешняя административная процедура, затем фиксация успешного
   размещения в simple-deploy.
8. Для scheduled release дефолтные ветки - `dev`.
9. Закрытые issues не являются обязательным quality gate и не ограничивают
   простое желание переделать релиз.
10. Git range для change set считается от последнего успешного bundle,
    размещенного на DEV.
11. Изменение origin выполняет только тимлид через настройки. Для первого
    этапа достаточно зафиксировать в релизе, на каких origins он собран.
12. Начальный набор components: backend, frontend, database.
13. Начальный словарь deployment target roles: backend, frontend, database,
    cache, reporting, s3.
14. Статусную модель релиза рассматриваем как ETL pipeline: initiated,
    source_resolved, build/deploy success или failure, заявки и подтверждения
    внешних контуров.
15. PROD формируется на основе TEST-заявок и подтвержденного размещения на
    TEST. Нельзя собрать или продвинуть PROD без успешного TEST.
16. `DeploymentLandscape` не версионируется по релизам: конфигурация контура
    стабильна между релизами и меняется отдельно через runtime/config.
17. Текущий artifact scope: contour-specific - schema migrations и frontend
    builds; shared - backend archive, DB data insert и DB data update.
18. Contour-specific artifact для чужого контура считается неподходящим по
    контракту manifest/resolver и должен приводить к hard fail до размещения.
19. Виртуальные машины учитываются отдельно от контуров: app VM может
    использоваться для тестового pipeline над bundle-ом без влияния на DEV.
20. Тестовые pipeline-ы фиксируются как `BundleValidationAttempt`/`Job`, а не
    как `DeploymentAttempt`; они не меняют `ContourState`, `ReleasePlacement`
    и baseline контура.

## Оставшиеся открытые вопросы

На текущем уровне обсуждения ключевые доменные вопросы закрыты. Новые вопросы
лучше добавлять уже рядом с конкретным шагом внедрения DTO или изменением
схемы SQLite.

## Ближайшее практическое решение

До изменения кода считаем этот документ рабочим словарем. Следующий безопасный
шаг после обсуждения - выбрать один read-only DTO слой поверх текущего
`release/state.py`, чтобы начать переход к Pydantic без изменения поведения
CLI, builder и deploy-процессов.
