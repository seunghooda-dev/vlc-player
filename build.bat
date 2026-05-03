@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   Archive Tagger - build desktop executable
echo ================================================
echo.

"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

"%PY%" check_imports.py
if errorlevel 1 goto fail

"%PY%" -m PyInstaller --onefile --windowed --name ArchiveTagger --add-data "archive.db;." main.py
if errorlevel 1 goto fail

echo.
echo Build complete: dist\ArchiveTagger.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
