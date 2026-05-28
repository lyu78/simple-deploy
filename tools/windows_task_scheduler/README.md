# Пример Windows Task Scheduler

В этой директории лежит пример обертки для запуска Windows-only pipeline по
расписанию.

## Файлы

- `run_pipeline.cmd` - запускает `tools\windows_pipeline.py pipeline` из корня
  проекта и пишет wrapper-лог в `logs\scheduled-pipeline-<timestamp>.log`.

Python runner дополнительно пишет свой отдельный лог запуска в
`logs\<timestamp>-pipeline.log`.

## Рекомендуемое расписание

Используй одну ежедневную задачу на 08:00, которая запускает полный pipeline:

```bat
C:\example\simple-deploy\tools\windows_task_scheduler\run_pipeline.cmd
```

Не ставь `build` и `deploy --latest` отдельными пересекающимися задачами.
`deploy --latest` может взять неполный релиз, если стартует в момент, когда
`build` еще записывает артефакты.

## Создание задачи через GUI

1. Открой **Task Scheduler**.
2. Выбери **Create Task...**.
3. Вкладка General:
   - Name: `simple-deploy pipeline`
   - Включи **Run whether user is logged on or not**.
   - Включай **Run with highest privileges** только если локальному Windows
     пользователю это нужно для доступа к репозиторию, SSH-ключу или сетевым
     ресурсам.
4. Вкладка Triggers:
   - New...
   - Begin the task: `On a schedule`
   - Settings: `Daily`
   - Start: `08:00`
5. Вкладка Actions:
   - New...
   - Action: `Start a program`
   - Program/script:
     `C:\example\simple-deploy\tools\windows_task_scheduler\run_pipeline.cmd`
   - Start in:
     `C:\example\simple-deploy`
6. Вкладка Settings:
   - Включи **Do not start a new instance**.
   - Опционально включи **Stop the task if it runs longer than** и выбери время
     с запасом относительно обычной длительности запуска.
7. Сохрани задачу и введи пароль Windows-пользователя, если система попросит.

## Создание задачи через schtasks

Запускать из Command Prompt или PowerShell с правами администратора:

```bat
schtasks /Create ^
  /TN "simple-deploy pipeline" ^
  /SC DAILY ^
  /ST 08:00 ^
  /TR "C:\example\simple-deploy\tools\windows_task_scheduler\run_pipeline.cmd" ^
  /RL HIGHEST ^
  /F
```

Если задача должна запускаться, когда пользователь не залогинен, настрой
сохраненные учетные данные через GUI после создания задачи или используй
`/RU <user> /RP <password>` согласно локальной политике безопасности.

## Ручная проверка

Перед включением расписания запусти:

```bat
C:\example\simple-deploy\tools\windows_task_scheduler\run_pipeline.cmd
```

Затем проверь:

```bat
dir C:\example\simple-deploy\logs
```

Wrapper-лог должен содержать exit code процесса. Лог runner-а содержит подробный
вывод dry-run, build, deploy и healthcheck.
