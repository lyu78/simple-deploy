"""Типы source snapshot и Git revision."""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints


COMMIT_SHA_PATTERN = r"^[0-9a-fA-F]{6,40}$"
OPTIONAL_COMMIT_SHA_PATTERN = r"^$|^[0-9a-fA-F]{6,40}$"


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


__all__ = [
    "CommitShaString",
    "OptionalCommitShaString",
]
