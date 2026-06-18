"""Пакет release manifest и артефактов.

Release package описывает переносимое содержимое собранного релиза:
``release_manifest.json``, локальные файлы артефактов и правила их резолвинга.
Он не владеет SQLite state, baseline-ами контуров, build/deploy attempts, jobs
или external requests: это область ``simple_deploy.registry``.

Модуль ``release.state`` оставлен только как compatibility import path поверх
``registry.state`` для старого кода.
"""
