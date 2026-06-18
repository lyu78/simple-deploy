"""
Registry boundary для локального durable state simple-deploy.

Registry - это область, через которую прикладной код должен работать с
локальной историей и operational state toolkit-а: release bundles, contour
baselines, build/deploy attempts, local jobs и external TEST/PROD requests.

Пакет разделяет низкоуровневый storage API, read/query проекции и write/use-
case команды:

* ``registry.state`` - storage-facing API текущей SQLite implementation;
* ``registry.queries`` - read models для dashboard/API;
* ``registry.commands`` - небольшие write-команды поверх state.

Реальная SQLite implementation живет в ``simple_deploy.registry.state``. Старый
путь ``simple_deploy.release.state`` остается compatibility re-export-ом, чтобы
не ломать существующие локальные imports.

Важно: registry не является доменной сущностью ``Release`` и не выполняет
deploy. Он хранит факты и проекции локального состояния, над которыми работают
CLI, web/API и процессы.
"""

from simple_deploy.registry.state import *  # noqa: F401,F403
