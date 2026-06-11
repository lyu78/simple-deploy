"""Типы deploy-контуров."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class ContourCodeEnum(DomainStringEnum):
    """Справочник deploy-контуров продукта."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


CONTOUR_CODES = ContourCodeEnum.get_values()


def _validate_contour_code(value: str) -> str:
    """Проверяет, что строка является известным deploy-контуром."""

    if value not in CONTOUR_CODES:
        raise ValueError(f"Unknown contour: {value}. Expected one of: {', '.join(CONTOUR_CODES)}")
    return value


def _validate_optional_contour_code(value: str) -> str:
    """Проверяет optional deploy-контур с допустимой пустой строкой."""

    return value if value == "" else _validate_contour_code(value)


ContourCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_contour_code),
]
"""Строковый код deploy-контура."""


OptionalContourCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_optional_contour_code),
]
"""Код deploy-контура, который может быть пустым в черновых local job записях."""


__all__ = [
    "CONTOUR_CODES",
    "ContourCode",
    "ContourCodeEnum",
    "OptionalContourCode",
]
