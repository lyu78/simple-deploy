"""Request DTO для application use cases simple-deploy.

Модели описывают стабильный вход application layer. CLI, будущий web/API и
local job runner должны собирать эти DTO у себя на границе, чтобы сервисы не
знали про ``argparse``, HTTP payload или storage representation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from simple_deploy.core.paths import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_ENV_FILE,
    DEFAULT_SECRETS_FILE,
)
from simple_deploy.types import (
    BuildVersionString,
    ContourCodeEnum,
    OptionalBuildVersionString,
    OptionalCommitShaString,
)
from simple_deploy.types.fields import ErrorText

DEFAULT_REQUEST_TIMEOUT_SECONDS = 3600


class _ApplicationRequestBase(BaseModel):
    """Базовая immutable-модель request DTO application layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _EnvFilesRequestBase(_ApplicationRequestBase):
    """Базовый request с путями к runtime env и secrets файлам."""

    env_file: Path = Field(
        default=DEFAULT_ENV_FILE,
        description=(
            "Путь к dotenv-файлу с runtime env для Windows runner-а."
        ),
    )
    secrets_file: Path = Field(
        default=DEFAULT_SECRETS_FILE,
        description=(
            "Путь к dotenv-файлу с локальными secrets Windows runner-а."
        ),
    )


class _TimedEnvFilesRequestBase(_EnvFilesRequestBase):
    """Базовый request для команд, запускающих долгий subprocess."""

    timeout: StrictInt = Field(
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        gt=0,
        description=(
            "Timeout в секундах для subprocess-а текущей команды."
        ),
    )


class DryRunRequest(_EnvFilesRequestBase):
    """Request preflight-проверок без build/deploy side effects."""

    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        description=(
            "Путь к JSON runtime config Windows runner-а."
        ),
    )
    skip_data_sql_artifacts: StrictBool = Field(
        default=False,
        description=(
            "Отключает проверку data SQL artifacts для явного schema-only "
            "запуска."
        ),
    )
    app_only: StrictBool = Field(
        default=False,
        description=(
            "Ограничивает preflight проверками app VM без обязательных DB "
            "secrets и DB SSH checks."
        ),
    )


class BuildRequest(_TimedEnvFilesRequestBase):
    """Request сборки release bundle через builder pipeline."""

    skip_data_sql_artifacts: StrictBool = Field(
        default=False,
        description=(
            "Отключает генерацию data SQL artifacts для явной schema-only "
            "сборки."
        ),
    )


class DeployRequest(_EnvFilesRequestBase):
    """Request применения release bundle на deploy-контур."""

    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        description=(
            "Путь к JSON runtime config с deploy/runtime настройками."
        ),
    )
    build_version: OptionalBuildVersionString = Field(
        default="",
        description=(
            "Технический ключ release bundle. Пустая строка допустима только "
            "когда включен режим latest."
        ),
    )
    latest: StrictBool = Field(
        default=False,
        description=(
            "Выбирает последний локально собранный release bundle вместо "
            "явного build_version."
        ),
    )
    contour: ContourCodeEnum = Field(
        default=ContourCodeEnum.DEV,
        description=(
            "Deploy-контур, на который применяется выбранный release bundle."
        ),
    )
    include_set_default_sql: StrictBool = Field(
        default=False,
        description=(
            "Включает SQL artifacts вида set_default в deploy chain."
        ),
    )
    app_only: StrictBool = Field(
        default=False,
        description=(
            "Выполняет только app-часть deploy без DB steps."
        ),
    )


class PipelineRequest(_TimedEnvFilesRequestBase):
    """Request для pipeline use case ``dry-run -> build -> deploy latest``."""

    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        description=(
            "Путь к JSON runtime config для dry-run и deploy фаз pipeline."
        ),
    )
    contour: ContourCodeEnum = Field(
        default=ContourCodeEnum.DEV,
        description=(
            "Deploy-контур, на который pipeline применит latest bundle после "
            "успешной сборки."
        ),
    )
    include_set_default_sql: StrictBool = Field(
        default=False,
        description=(
            "Включает SQL artifacts вида set_default в deploy фазе pipeline."
        ),
    )
    skip_data_sql_artifacts: StrictBool = Field(
        default=False,
        description=(
            "Отключает data SQL artifact checks/generation в dry-run и build "
            "фазах pipeline."
        ),
    )
    app_only: StrictBool = Field(
        default=False,
        description=(
            "Выполняет app-only dry-run и app-only deploy фазу pipeline."
        ),
    )


class SetBaselineRequest(_EnvFilesRequestBase):
    """Request ручной установки baseline deploy-контура."""

    contour: ContourCodeEnum = Field(
        description=(
            "Deploy-контур, baseline которого задается вручную."
        ),
    )
    config_file: Path = Field(
        default=DEFAULT_CONFIG_FILE,
        description=(
            "Runtime config path used for initial_schema_baselines bootstrap."
        ),
    )
    build_version: OptionalBuildVersionString = Field(
        default="",
        description=(
            "Технический ключ release bundle для baseline. Может быть пустым,"
            " если baseline задается явным backend commit."
        ),
    )
    backend_commit: OptionalCommitShaString = Field(
        default="",
        description=(
            "Явный backend commit для ручного baseline без release bundle."
        ),
    )


class MarkAppliedRequest(_EnvFilesRequestBase):
    """Request ручной фиксации успешного применения release bundle."""

    contour: ContourCodeEnum = Field(
        description=(
            "Deploy-контур, где release bundle считается успешно примененным."
        ),
    )
    build_version: BuildVersionString = Field(
        description=(
            "Технический ключ release bundle, примененного на контур."
        ),
    )


class MarkFailedRequest(_EnvFilesRequestBase):
    """Request ручной фиксации неуспешного применения release bundle."""

    contour: ContourCodeEnum = Field(
        description=(
            "Deploy-контур, где release bundle считается неуспешным."
        ),
    )
    build_version: BuildVersionString = Field(
        description=(
            "Технический ключ release bundle, для которого фиксируется отказ."
        ),
    )
    error: ErrorText = Field(
        description=(
            "Текст причины неуспешного deploy attempt."
        ),
    )


RunnerCommandRequest: TypeAlias = (
    DryRunRequest
    | BuildRequest
    | DeployRequest
    | PipelineRequest
    | SetBaselineRequest
    | MarkAppliedRequest
    | MarkFailedRequest
)
"""Union всех request DTO, которые принимает совместимый runner dispatch."""


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "BuildRequest",
    "DeployRequest",
    "DryRunRequest",
    "MarkAppliedRequest",
    "MarkFailedRequest",
    "PipelineRequest",
    "RunnerCommandRequest",
    "SetBaselineRequest",
]
