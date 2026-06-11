"""Типы компонент продукта."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints


COMPONENT_IDS = ("backend", "frontend", "database")


def _validate_component_id(value: str) -> str:
    """Проверяет идентификатор компонента продукта."""

    if value not in COMPONENT_IDS:
        raise ValueError(f"Unknown component id: {value}. Expected one of: {', '.join(COMPONENT_IDS)}")
    return value


ComponentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_component_id),
]
"""Идентификатор логической части продукта."""


__all__ = [
    "COMPONENT_IDS",
    "ComponentId",
]
