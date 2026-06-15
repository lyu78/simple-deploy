"""Типы внешних заявок на продвижение релиза."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class ExternalRequestTypeEnum(DomainStringEnum):
    """Справочник типов внешних TEST/PROD заявок."""

    DEPLOY = "deploy"


EXTERNAL_REQUEST_TYPES = ExternalRequestTypeEnum.get_values()


def _validate_external_request_type(value: str) -> str:
    """Проверяет тип внешней TEST/PROD заявки."""

    if value not in EXTERNAL_REQUEST_TYPES:
        raise ValueError(
            f"Unknown external request type: {value}. Expected one of: {', '.join(EXTERNAL_REQUEST_TYPES)}"
        )
    return value


ExternalRequestType = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_external_request_type),
]
"""Тип внешней TEST/PROD заявки."""


__all__ = [
    "EXTERNAL_REQUEST_TYPES",
    "ExternalRequestType",
    "ExternalRequestTypeEnum",
]
