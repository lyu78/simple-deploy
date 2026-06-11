"""Типы версий релиза и версии сборки."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints


RELEASE_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
OPTIONAL_RELEASE_VERSION_PATTERN = r"^$|^[A-Za-z0-9][A-Za-z0-9_.-]*$"


ReleaseVersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=RELEASE_VERSION_PATTERN,
    ),
]
"""Непустой строковый идентификатор версии релиза."""


BuildVersionString = ReleaseVersionString
"""Текущее имя ReleaseVersionString на границах legacy-кода сборки и деплоя."""


OptionalBuildVersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=OPTIONAL_RELEASE_VERSION_PATTERN,
    ),
]
"""Версия сборки, которая может быть пустой в черновых local job записях."""


__all__ = [
    "BuildVersionString",
    "OptionalBuildVersionString",
    "ReleaseVersionString",
]
