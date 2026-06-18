"""Функции email для deploy-уведомлений и preflight-проверок."""

from __future__ import annotations

import re


class SafeFormatDict(dict):
    """Словарь для format_map с сохранением неизвестных placeholders."""

    def __missing__(self, key: str) -> str:
        """Возвращает исходный placeholder, если значения нет в контексте."""
        return "{" + key + "}"


def normalize_email_list(value: object) -> list[str]:
    """Нормализует строку или список адресов в очищенный список email."""
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[;,]", value)
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        items = [str(value)]
    return [item.strip() for item in items if item.strip()]


def format_outlook_template(
    template: object, context: dict[str, object]
) -> str:
    """Форматирует Outlook-шаблон без падения на неизвестных placeholders."""
    return str(template).format_map(SafeFormatDict(context))


__all__ = [
    "SafeFormatDict",
    "format_outlook_template",
    "normalize_email_list",
]
