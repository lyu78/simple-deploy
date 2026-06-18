"""Корневой пакет release/deploy toolkit-а simple-deploy.

Пакет является новой общей областью для кода, который постепенно выносится из
отдельных runner- и builder-скриптов. Его задача - дать CLI, web/API, builder-у
и будущим локальным jobs один набор прикладных модулей вместо параллельных
реализаций одной и той же логики.

Основные границы внутри пакета:

* ``processes`` - операторские use cases: build, deploy, dry-run, mark и data SQL;
* ``application`` - прикладные сервисы поверх процессов для CLI, web/API и jobs;
* ``registry`` - локальное durable state в SQLite и read/query boundary;
* ``config`` - typed-обертки над текущим runtime config и целевой topology;
* ``entities`` - чистые доменные сущности без SQLite, SSH и HTTP;
* ``models`` и ``dto`` - внутренние read models и внешние API/JSON контракты;
* ``types`` - общие ограниченные строки, enum-ы и справочники.

Корневой пакет не должен превращаться в монолитный facade. Новая логика должна
попадать в конкретную область, а не импортироваться сюда только ради удобства.
"""
