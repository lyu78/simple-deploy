"""Compatibility import path для локального registry state.

SQLite state больше не принадлежит release package: реальная implementation
живет в ``simple_deploy.registry.state``. Этот модуль оставлен как стабильный
legacy import path для старого builder/test/process кода и внешних локальных
скриптов, которые еще импортируют ``simple_deploy.release.state``.
"""

from simple_deploy.registry import state as _registry_state
from simple_deploy.registry.state import *  # noqa: F401,F403

__all__ = list(_registry_state.__all__)
