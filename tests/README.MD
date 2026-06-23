# Tests

Тесты разложены по архитектурным зонам. `pytest tests` должен оставаться
основной командой запуска всего набора.

## Layout

- `application/` - application services и local job worker.
- `builder/` - сборка release artifacts и backend/data SQL artifacts.
- `config/` - runtime/topology config models.
- `domain/` - доменные entities, value objects и vocabulary types.
- `processes/` - process layer, Windows pipeline, deploy/dry-run behavior.
- `registry/` - SQLite registry, commands, queries, read models и state
  compatibility.
- `support/` - общая инфраструктурная поддержка.
- `web/` - FastAPI/web UI adapters и API contracts.

Крупные process/builder test files пока только переложены по директориям. Их
можно дробить отдельным refactoring step, чтобы не смешивать rename и изменение
test setup.
