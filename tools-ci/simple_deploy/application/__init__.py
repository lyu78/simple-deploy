"""Прикладной слой use cases simple-deploy.

Application layer - это стабильная граница для CLI, web/API и будущих local jobs.
Он принимает уже разобранные команды или request-модели, вызывает process/use-case
реализации и возвращает результат без знания о HTTP, argparse dispatch или SQLite
schema details.

На текущем срезе сервисы делегируют существующим ``processes`` modules. Это
сохраняет поведение Windows runner-а и дает отдельную точку подключения для
будущих API/job endpoints.
"""

from simple_deploy.application.services import (
    build,
    deploy,
    mark_applied,
    mark_failed,
    set_baseline,
)

__all__ = [
    "build",
    "deploy",
    "mark_applied",
    "mark_failed",
    "set_baseline",
]
