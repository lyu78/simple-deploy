"""Результаты application/process use cases simple-deploy."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from simple_deploy.types.contour import ContourCodeEnum
from simple_deploy.types.release import OptionalBuildVersionString


@dataclass(frozen=True)
class ProcessResult:
    """Структурированный результат выполнения process/use-case операции.

    CLI продолжает использовать ``exit_code`` и прежние bool/int wrapper-ы.
    Web/API и local job runner получают тот же исход в форме DTO-like объекта
    без разбора stdout и без знания о конкретной process-функции.
    """

    ok: bool
    exit_code: int = 0
    message: str = ""
    build_version: OptionalBuildVersionString = ""
    contour: ContourCodeEnum | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.exit_code < 0:
            raise ValueError("ProcessResult exit_code must be non-negative")
        object.__setattr__(
            self, "details", MappingProxyType(dict(self.details))
        )

    @classmethod
    def success(
        cls,
        message: str = "",
        *,
        build_version: str = "",
        contour: ContourCodeEnum | None = None,
        details: Mapping[str, object] | None = None,
    ) -> ProcessResult:
        """Возвращает успешный результат use case."""
        return cls(
            ok=True,
            exit_code=0,
            message=message,
            build_version=build_version,
            contour=contour,
            details=details or {},
        )

    @classmethod
    def failure(
        cls,
        message: str = "",
        *,
        exit_code: int = 1,
        build_version: str = "",
        contour: ContourCodeEnum | None = None,
        details: Mapping[str, object] | None = None,
    ) -> ProcessResult:
        """Возвращает неуспешный результат use case."""
        return cls(
            ok=False,
            exit_code=exit_code,
            message=message,
            build_version=build_version,
            contour=contour,
            details=details or {},
        )

    @classmethod
    def from_exit_code(
        cls,
        exit_code: int,
        *,
        success_message: str = "",
        failure_message: str = "",
        details: Mapping[str, object] | None = None,
    ) -> ProcessResult:
        """Преобразует код возврата subprocess/CLI в структурированный результат."""
        if exit_code == 0:
            return cls.success(success_message, details=details)
        return cls.failure(
            failure_message or f"process exited with code {exit_code}",
            exit_code=exit_code,
            details=details,
        )


__all__ = ["ProcessResult"]
