@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"
set "MXF_QC_USER_DATA_DIR=%CD%\tmp\dev_check_user_data"
if not exist "%MXF_QC_USER_DATA_DIR%" mkdir "%MXF_QC_USER_DATA_DIR%" > nul 2>&1

echo ================================================
echo   MXF QC Player V.1.0 - development check
echo ================================================
echo   user data: %MXF_QC_USER_DATA_DIR%
echo.

"%PY%" check_imports.py
if errorlevel 1 exit /b %errorlevel%

echo.
echo Running Python bytecode compile check...
"%PY%" -m py_compile check_imports.py safe.py process_registry.py theme.py constants.py db_models.py threads.py meters.py video_panel.py right_panel.py main.py
if errorlevel 1 exit /b %errorlevel%

where git > nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARN] git was not found. Skipping whitespace diff check.
) else if exist ".git" (
    echo.
    echo Running git whitespace diff check...
    git diff --check
    if errorlevel 1 exit /b %errorlevel%
)

if exist "ArchiveTagger.spec" (
    echo.
    echo [WARN] Legacy ArchiveTagger.spec exists locally.
    echo        build.bat does not use it; current builds use the MXF QC Player name.
)

echo.
echo [PASS] Development check completed.
exit /b 0
