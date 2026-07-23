@echo off
chcp 65001 > nul
setlocal
title MasterQC Player V.1.1 - Dev Run
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   MasterQC Player V.1.1 - run from source
echo ================================================
echo.

tasklist /FI "IMAGENAME eq MasterQC Player.exe" 2>nul | find /I "MasterQC Player.exe" >nul
if not errorlevel 1 (
    echo [warning] Packaged MasterQC Player.exe is already running.
    echo           Close it first, then run dev_run.bat again.
    echo.
    pause
    exit /b 1
)

"%PY%" check_imports.py
if errorlevel 1 goto fail

echo.
echo Starting from source: main.py
echo.
"%PY%" main.py
exit /b %errorlevel%

:fail
echo.
echo Development check failed.
pause
exit /b 1
