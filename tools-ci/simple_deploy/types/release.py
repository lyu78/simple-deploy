"""
Типы версий релиза и версий сборки.

В текущем toolkit-е эти значения имеют один строковый формат, но разный смысл.
Версия релиза - логический идентификатор release resource/intent в registry и
dashboard. Версия сборки - технический идентификатор конкретного результата
build pipeline, по которому находятся release directory, manifest и artifacts.

Сборка не равна bundle. ``BuildVersionString`` - это строковый ключ, а
``ReleaseBundle`` - материализованный результат успешной сборки: source
snapshot, ссылки на artifacts, время создания и id build attempt. В legacy
границах поле по-прежнему называется ``build_version``, поэтому оба типа
сохраняют одинаковые constraints.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

RELEASE_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
OPTIONAL_RELEASE_VERSION_PATTERN = r"^$|^[A-Za-z0-9][A-Za-z0-9_.-]*$"


ReleaseVersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=RELEASE_VERSION_PATTERN,
    ),
    Field(
        description=(
            "Непустой логический идентификатор release resource/intent. "
            "В текущем legacy-контракте имеет тот же строковый формат, что "
            "и build_version."
        ),
    ),
]
"""Непустой строковый идентификатор версии релиза."""


BuildVersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=RELEASE_VERSION_PATTERN,
    ),
    Field(
        description=(
            "Непустой технический идентификатор конкретной сборки release "
            "bundle. Это строковый ключ bundle-а, а не сам bundle с "
            "artifacts и source snapshot."
        ),
    ),
]
"""
Непустой строковый идентификатор конкретной сборки release bundle.

Сборка здесь означает результат build pipeline, который может быть записан как
``ReleaseBundle``. Сам bundle - отдельная структура с artifacts, source
snapshot и metadata; ``BuildVersionString`` хранит только его строковый ключ.
"""


OptionalBuildVersionString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=OPTIONAL_RELEASE_VERSION_PATTERN,
    ),
    Field(
        description=(
            "Версия сборки release bundle; пустая строка используется в "
            "черновых job записях до привязки к конкретному bundle."
        ),
    ),
]
"""Версия сборки, которая может быть пустой в черновых local job записях."""


__all__ = [
    "BuildVersionString",
    "OptionalBuildVersionString",
    "ReleaseVersionString",
]
