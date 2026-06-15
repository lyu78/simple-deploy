"""Типы виртуальных машин и execution infrastructure."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints


MACHINE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


MachineId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=MACHINE_ID_PATTERN,
    ),
]
"""Стабильный идентификатор виртуальной машины."""


__all__ = ["MachineId"]
