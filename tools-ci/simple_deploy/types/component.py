"""Типы компонент продукта."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class ComponentIdEnum(DomainStringEnum):
    """Справочник логических компонентов продукта."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"


COMPONENT_IDS = ComponentIdEnum.get_values()


__all__ = [
    "COMPONENT_IDS",
    "ComponentIdEnum",
]
