"""
Типы deploy-контуров и contour scope для локальных заданий.

Deploy contour - реальная среда продвижения релиза: ``dev``, ``test`` или
``prod``. Для ``local_jobs`` есть отдельный primitive ``JobContourScope``:
пустая строка там не означает "контур неизвестен", а фиксирует unscoped job,
например сборку bundle-а без привязки к конкретному deploy-контуру.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from simple_deploy.types._enum import DomainStringEnum


class ContourCodeEnum(DomainStringEnum):
    """Справочник deploy-контуров продукта."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


CONTOUR_CODES = ContourCodeEnum.get_values()
JOB_CONTOUR_SCOPE_CODES = ("", *CONTOUR_CODES)


JobContourScope = Annotated[
    Literal[JOB_CONTOUR_SCOPE_CODES],
    Field(
        description=(
            "Contour scope локальной job. Пустая строка означает unscoped "
            "job без привязки к deploy-контуру, а не неизвестный contour."
        ),
    ),
]
"""
Contour scope local job.

Пустая строка означает unscoped job, иначе ожидается deploy contour.
"""


__all__ = [
    "CONTOUR_CODES",
    "ContourCodeEnum",
    "JOB_CONTOUR_SCOPE_CODES",
    "JobContourScope",
]
