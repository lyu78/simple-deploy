"""Общие идентификаторы контуров развертывания.

Модуль переэкспортирует канонический список контуров и валидатор из слоя
состояния релизов. Это дает вызывающему коду контурно-ориентированный import
path, при этом источником истины по допустимым именам остается состояние
релизов.
"""

from __future__ import annotations

from simple_deploy.release.state import CONTOURS, validate_contour

__all__ = ["CONTOURS", "validate_contour"]
