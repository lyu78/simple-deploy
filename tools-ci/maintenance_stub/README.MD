# Maintenance stub

Эта директория содержит default-архив страницы технических работ:

```text
tools-ci/maintenance_stub/maintenance_stub.tar.gz
```

Архив универсальный и не привязан к версии релиза. Во время полного DEV deploy
runner загружает его на app VM и распаковывает в
`FRONTEND_RELEASE_PATH` до запуска DB scripts. Настоящий frontend
распаковывается только после успешного выполнения DB scripts, распаковки
backend, management-команд и запуска сервисов.

Текущий архив содержит один верхнеуровневый каталог `build/`:

```text
build/index.html
build/assets/...
```

Runner распаковывает архив с `--strip-components=1`, поэтому в целевой
`FRONTEND_RELEASE_PATH` напрямую попадают `index.html` и `assets/`.

После распаковки заглушки полный deploy запрашивает `https://DEV_DOMAIN/` и
проверяет, что возвращенный HTML содержит настроенный
`maintenance_stub_verify_marker`. Default-архив содержит marker:

```text
Плановые технические работы
```

Если архив заменяется другой универсальной заглушкой, обновите
`maintenance_stub_verify_marker` в `windows_pipeline.local.json`.

Deploy runner проверяет наличие архива до остановки app-сервисов, когда
`maintenance_stub_enabled` равен `true`.
