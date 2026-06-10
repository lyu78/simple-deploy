"""Импортируемая CLI-точка входа для Windows pipeline.

Исторический исполняемый скрипт остается по пути
``tools-ci/tools/windows_pipeline.py``. Этот модуль дает пакетный import path
для тех же функций ``main`` и ``parse_args``, чтобы будущие процессные модули
можно было подключать к CLI без изменения публичного контракта команд.
"""

from __future__ import annotations

from simple_deploy.windows_pipeline import main, parse_args

__all__ = ["main", "parse_args"]
