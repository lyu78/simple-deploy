"""Типы source snapshot и Git revision."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

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


def _validate_source_origin_kind(value: str) -> str:
    """Проверяет вид source origin."""

    if value not in SOURCE_ORIGIN_KINDS:
        raise ValueError(
            f"Unknown source origin kind: {value}. Expected one of: {', '.join(SOURCE_ORIGIN_KINDS)}"
        )
    return value


CommitShaString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=6,
        pattern=COMMIT_SHA_PATTERN,
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
]
"""Git commit SHA, который может быть пустым до фиксации результата attempt."""


RepoId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=SOURCE_ID_PATTERN,
    ),
]
"""Стабильный идентификатор source repository."""


SourceOriginKind = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_source_origin_kind),
]
"""Вид source origin для SourceSnapshot/SourceRepository."""


__all__ = [
    "CommitShaString",
    "OptionalCommitShaString",
    "RepoId",
    "SOURCE_ORIGIN_KINDS",
    "SourceOriginKind",
    "SourceOriginKindEnum",
]
