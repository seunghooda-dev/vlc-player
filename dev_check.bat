@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   MXF QC Player V.1.0 - development check
echo ================================================
echo.

"%PY%" check_imports.py
exit /b %errorlevel%
