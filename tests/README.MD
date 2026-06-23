# Tests

Тесты разложены по архитектурным зонам. `pytest tests` должен оставаться
основной командой запуска всего набора.

## Layout

- `application/` - application services и local job worker.
- `builder/` - сборка release artifacts и backend/data SQL artifacts.
- `config/` - runtime/topology config models.
- `core/` - command/env/path/SSH primitives shared by process layer.
- `domain/` - доменные entities, value objects и vocabulary types.
- `processes/` - process layer, Windows pipeline, deploy/dry-run behavior.
- `registry/` - SQLite registry, commands, queries, read models и state
  compatibility.
- `support/` - общая инфраструктурная поддержка.
- `web/` - FastAPI/web UI adapters и API contracts.

Windows pipeline characterization tests в `processes/` разделены по сценариям:
adapters, db SQL, runtime config, CLI/state, deploy flow, dry-run и
notifications. Общие constants/imports/helpers лежат в
`processes/windows_pipeline_test_support.py`.

Крупный builder test file пока только переложен в `builder/`. Его можно дробить
отдельным refactoring step, чтобы не смешивать перенос и изменение test setup.
