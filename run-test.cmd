@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-test.ps1" %*
exit /b %ERRORLEVEL%
