@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\start-simple-deploy.ps1"
exit /b %ERRORLEVEL%
