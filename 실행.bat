@echo off
chcp 65001 > nul
setlocal
title MXF QC Player V.1.0
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo ================================================
echo   MXF QC Player V.1.0
echo ================================================
echo.

ffmpeg -version > nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg was not found in PATH. MXF conversion may fail.
    echo           Install with: winget install ffmpeg
    echo.
)

if exist "dist\MXF QC Player.exe" (
    echo Launching dist\MXF QC Player.exe
    start "" "dist\MXF QC Player.exe"
    exit /b 0
)

echo dist\MXF QC Player.exe not found. Running from source.
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

"%PY%" check_imports.py
if errorlevel 1 goto fail

"%PY%" main.py
exit /b %errorlevel%

:fail
echo.
echo Failed to start MXF QC Player.
pause
exit /b 1
