"""Базовые enum-классы для доменных справочников."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar


DomainStringEnumType = TypeVar("DomainStringEnumType", bound="DomainStringEnum")


class DomainStringEnum(str, Enum):
    """Базовый enum для строковых доменных справочников."""

    @classmethod
    def get_values(cls: type[DomainStringEnumType]) -> tuple[str, ...]:
        """Возвращает значения справочника в порядке объявления."""
        return tuple(item.value for item in cls)


__all__ = ["DomainStringEnum"]
