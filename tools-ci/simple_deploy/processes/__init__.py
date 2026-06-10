"""Пакет операторских процессов совместимого Windows runner-а.

Здесь собраны process entrypoints шага 5: ``data_sql``, ``mark``, ``build``,
``dry_run`` и ``deploy``. Низкоуровневые helper-слои config/runtime, SSH, app,
DB, service steps, healthcheck и email пока могут оставаться в compatibility
runner-е, чтобы процессный split не смешивался с переносом core-слоя.
"""
