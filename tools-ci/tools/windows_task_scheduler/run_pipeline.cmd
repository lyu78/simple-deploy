@echo off
setlocal

rem Пример запуска Windows-only simple-deploy pipeline по расписанию.
rem Держи этот файл в tools-ci\tools\windows_task_scheduler и запускай его из Task Scheduler.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..\..") do set "PROJECT_ROOT=%%~fI"
set "LOG_DIR=%PROJECT_ROOT%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%I"
set "WRAPPER_LOG=%LOG_DIR%\scheduled-pipeline-%STAMP%.log"

cd /d "%PROJECT_ROOT%"

echo [%DATE% %TIME%] Starting simple-deploy pipeline>"%WRAPPER_LOG%"
echo Project root: %PROJECT_ROOT%>>"%WRAPPER_LOG%"

".venv\Scripts\python.exe" tools-ci\tools\windows_pipeline.py pipeline >>"%WRAPPER_LOG%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%DATE% %TIME%] Finished with exit code %RC%>>"%WRAPPER_LOG%"
exit /b %RC%
