@echo off
chcp 65001 > nul
setlocal
title Archive Tagger - MXF Player
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo ================================================
echo   Archive Tagger - MXF Player
echo ================================================
echo.

ffmpeg -version > nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg was not found in PATH. MXF conversion may fail.
    echo           Install with: winget install ffmpeg
    echo.
)

if exist "dist\ArchiveTagger.exe" (
    echo Launching dist\ArchiveTagger.exe
    start "" "dist\ArchiveTagger.exe"
    exit /b 0
)

echo dist\ArchiveTagger.exe not found. Running from source.
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

"%PY%" check_imports.py
if errorlevel 1 goto fail

"%PY%" main.py
exit /b %errorlevel%

:fail
echo.
echo Failed to start Archive Tagger.
pause
exit /b 1
