"""Compatibility registry boundary поверх текущей SQLite state реализации.

Модуль временно переэкспортирует ``simple_deploy.release.state`` без изменения
объектов, функций и поведения. Это осознанный промежуточный шаг: старый путь
остается источником реализации, а новый путь фиксирует правильную архитектурную
область для будущих read/query и application слоев.

После переноса SQLite-кода сюда callers, которые уже используют
``simple_deploy.registry.state``, не должны будут меняться.
"""

from simple_deploy.release import state as _release_state
from simple_deploy.release.state import *  # noqa: F403


__all__ = list(_release_state.__all__)
