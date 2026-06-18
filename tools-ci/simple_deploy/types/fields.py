"""Описанные primitive-поля для доменных и read/storage моделей."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

SourceRefString = Annotated[
    str,
    Field(
        description=(
            "Git ref source repository, по которому была получена revision."
        ),
    ),
]
"""Git ref исходного репозитория."""


SourceOriginIdString = Annotated[
    str,
    Field(
        description=(
            "Строковый код source origin, из которого получена revision. "
            "Это не числовой database id; значение должно совпадать с "
            "origin_id из topology."
        ),
    ),
]
"""Строковый код источника Git-данных из topology."""


ResolvedAtString = Annotated[
    str,
    Field(
        description=(
            "UTC timestamp фиксации source snapshot после разрешения refs "
            "в commit SHA."
        ),
    ),
]
"""UTC timestamp разрешения source snapshot."""


ArtifactIdString = Annotated[
    str,
    Field(
        description=(
            "Строковый идентификатор artifact внутри release bundle "
            "manifest/read model. Это не числовой database id."
        ),
    ),
]
"""Строковый идентификатор артефакта релиза."""


ArtifactNameString = Annotated[
    str,
    Field(
        description=(
            "Стабильное имя artifact внутри release bundle и deploy-плана."
        ),
    ),
]
"""Стабильное имя артефакта релиза."""


ArtifactRemoteArchiveString = Annotated[
    str,
    Field(
        description=(
            "Временный путь архива на целевой VM перед распаковкой artifact."
        ),
    ),
]
"""Удаленный путь архива артефакта."""


ArtifactExtractPathString = Annotated[
    str,
    Field(
        description=(
            "Целевой каталог на VM, куда распаковывается artifact релиза."
        ),
    ),
]
"""Каталог распаковки артефакта."""


ArtifactEntrypointDirString = Annotated[
    str,
    Field(
        description=(
            "Каталог внутри SQL artifact, где ожидается entrypoint-файл."
        ),
    ),
]
"""Каталог entrypoint-файла SQL artifact."""


ArtifactEntrypointPatternString = Annotated[
    str,
    Field(
        description=(
            "Glob-шаблон entrypoint-файла внутри SQL artifact."
        ),
    ),
]
"""Glob-шаблон entrypoint-файла SQL artifact."""


ArtifactsJsonString = Annotated[
    str,
    Field(
        description=(
            "JSON-строка со списком artifacts, сохраненная в registry."
        ),
    ),
]
"""JSON-представление artifacts release bundle."""


PayloadJsonString = Annotated[
    str,
    Field(
        description=(
            "JSON-строка payload, сохраненная в registry."
        ),
    ),
]
"""JSON-представление payload записи registry."""


LogPathString = Annotated[
    str,
    Field(
        description=(
            "Путь к log-файлу операции; пустая строка означает, что лог "
            "еще не назначен."
        ),
    ),
]
"""Путь к log-файлу операции."""


ExternalIdString = Annotated[
    str,
    Field(
        description=(
            "Строковый идентификатор TEST/PROD заявки во внешней системе; "
            "это не локальный registry id. Пустая строка означает, что он "
            "еще не получен."
        ),
    ),
]
"""Строковый идентификатор заявки во внешней системе."""


ErrorText = Annotated[
    str,
    Field(
        description=(
            "Текст ошибки операции; пустая строка означает отсутствие ошибки."
        ),
    ),
]
"""Текст ошибки операции."""


CreatedAtString = Annotated[
    str,
    Field(
        description=(
            "UTC timestamp создания записи или ресурса."
        ),
    ),
]
"""UTC timestamp создания записи или ресурса."""


UpdatedAtString = Annotated[
    str,
    Field(
        description=(
            "UTC timestamp последнего обновления записи или ресурса."
        ),
    ),
]
"""UTC timestamp последнего обновления записи или ресурса."""


StartedAtString = Annotated[
    str,
    Field(
        description=(
            "UTC timestamp начала операции; пустая строка означает, что "
            "операция еще не стартовала."
        ),
    ),
]
"""UTC timestamp начала операции."""


FinishedAtString = Annotated[
    str,
    Field(
        description=(
            "UTC timestamp завершения операции; пустая строка означает, что "
            "операция еще не завершилась."
        ),
    ),
]
"""UTC timestamp завершения операции."""


CommandStdoutText = Annotated[
    str,
    Field(
        description=(
            "Текст stdout завершенной локальной команды."
        ),
    ),
]
"""Текст stdout локальной команды."""


CommandStderrText = Annotated[
    str,
    Field(
        description=(
            "Текст stderr завершенной локальной команды."
        ),
    ),
]
"""Текст stderr локальной команды."""


SqlTableNameString = Annotated[
    str,
    Field(
        description=(
            "Имя SQL-таблицы, найденное при разборе INSERT statement."
        ),
    ),
]
"""Имя SQL-таблицы из parsed INSERT."""


SqlValidationRuleString = Annotated[
    str,
    Field(
        description=(
            "Код правила SQL validation, которое выявило проблему."
        ),
    ),
]
"""Код правила SQL validation."""


SqlValidationDetailText = Annotated[
    str,
    Field(
        description=(
            "Человекочитаемое описание найденной SQL validation проблемы."
        ),
    ),
]
"""Описание проблемы SQL validation."""


__all__ = [
    "ArtifactEntrypointDirString",
    "ArtifactEntrypointPatternString",
    "ArtifactExtractPathString",
    "ArtifactIdString",
    "ArtifactNameString",
    "ArtifactRemoteArchiveString",
    "ArtifactsJsonString",
    "CommandStderrText",
    "CommandStdoutText",
    "CreatedAtString",
    "ErrorText",
    "ExternalIdString",
    "FinishedAtString",
    "LogPathString",
    "PayloadJsonString",
    "ResolvedAtString",
    "SourceOriginIdString",
    "SourceRefString",
    "SqlTableNameString",
    "SqlValidationDetailText",
    "SqlValidationRuleString",
    "StartedAtString",
    "UpdatedAtString",
]
