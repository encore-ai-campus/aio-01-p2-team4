@echo off
setlocal

rem Windows entry point: call the PowerShell implementation in this repository.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_openai.ps1" %*
exit /b %ERRORLEVEL%
