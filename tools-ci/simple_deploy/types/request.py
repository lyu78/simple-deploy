"""Типы внешних заявок на продвижение релиза."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class ExternalRequestTypeEnum(DomainStringEnum):
    """Справочник типов внешних TEST/PROD заявок."""

    DEPLOY = "deploy"


EXTERNAL_REQUEST_TYPES = ExternalRequestTypeEnum.get_values()


__all__ = [
    "EXTERNAL_REQUEST_TYPES",
    "ExternalRequestTypeEnum",
]
