"""Registry boundary для локального durable state simple-deploy.

Registry - это область, через которую прикладной код должен работать с
локальной историей и operational state toolkit-а: release bundles, contour
baselines, build/deploy attempts, local jobs и external TEST/PROD requests.

Пакет разделяет низкоуровневый storage API, read/query проекции и write/use-case
команды:

* ``registry.state`` - compatibility API текущей SQLite implementation;
* ``registry.queries`` - read models для dashboard/API;
* ``registry.commands`` - небольшие write-команды поверх state.

Сейчас реализация SQLite еще физически находится в ``simple_deploy.release.state``.
Этот пакет намеренно переэкспортирует тот же API как compatibility boundary:
новые query/application слои могут импортировать state из ``simple_deploy.registry``
уже сейчас, а перенос SQLite implementation в будущем не потребует менять их
публичные зависимости.

Важно: registry не является доменной сущностью ``Release`` и не выполняет deploy.
Он хранит факты и проекции локального состояния, над которыми работают CLI,
web/API и процессы.
"""

from simple_deploy.registry.state import *  # noqa: F403
