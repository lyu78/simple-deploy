"""Типы source snapshot и Git revision.

Идентификаторы с суффиксом ``Id`` в этом модуле являются строковыми кодами,
а не числовыми database id. Например, ``RepoId`` ожидает стабильный slug
логического repository: ``backend``, ``frontend-app`` или ``db.migrations``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from simple_deploy.types._enum import DomainStringEnum

COMMIT_SHA_PATTERN = r"^[0-9a-fA-F]{6,40}$"
OPTIONAL_COMMIT_SHA_PATTERN = r"^$|^[0-9a-fA-F]{6,40}$"
SOURCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class SourceOriginKindEnum(DomainStringEnum):
    """Справочник видов источников Git-данных."""

    PRIMARY_REMOTE = "primary_remote"
    MIRROR = "mirror"
    LOCAL_BARE_CLONE = "local_bare_clone"
    EMERGENCY_CLONE = "emergency_clone"


SOURCE_ORIGIN_KINDS = SourceOriginKindEnum.get_values()


CommitShaString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=6,
        pattern=COMMIT_SHA_PATTERN,
    ),
    Field(
        description=(
            "Git commit SHA в короткой или полной форме."
        ),
    ),
]
"""Git commit SHA в короткой или полной форме."""


OptionalCommitShaString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=OPTIONAL_COMMIT_SHA_PATTERN,
    ),
    Field(
        description=(
            "Git commit SHA; пустая строка используется до фиксации "
            "результата attempt."
        ),
    ),
]
"""Git commit SHA, который может быть пустым до фиксации результата attempt."""


RepoId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=SOURCE_ID_PATTERN,
    ),
    Field(
        description=(
            "Строковый код логического source repository. Это не числовой "
            "database id, не URL и не путь; ожидается стабильный slug вроде "
            "'backend', 'frontend-app' или 'db.migrations'."
        ),
    ),
]
"""
Строковый код логического source repository.

``RepoId`` связывает topology, source snapshot и компоненты. Значение должно
начинаться с буквы или цифры и может содержать только буквы, цифры, ``_``,
``.`` и ``-``. Path/URL-синтаксис вроде ``group/backend`` не допускается.
"""


__all__ = [
    "CommitShaString",
    "OptionalCommitShaString",
    "RepoId",
    "SOURCE_ORIGIN_KINDS",
    "SourceOriginKindEnum",
]
