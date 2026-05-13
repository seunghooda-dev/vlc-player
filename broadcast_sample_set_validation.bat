@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "ROOT_DIR=%CD%"
set "SET_FILE=%~1"
if not defined SET_FILE set "SET_FILE=%ROOT_DIR%\BROADCAST_SAMPLE_SET.txt"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT_DIR%\broadcast_sample_set_validation.ps1" -SetFile "%SET_FILE%" -Root "%ROOT_DIR%"
exit /b %ERRORLEVEL%
