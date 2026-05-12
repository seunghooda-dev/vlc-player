@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%%APP_NAME%.exe" (
    set "PACKAGE_DIR=%SCRIPT_DIR:~0,-1%"
) else (
    set "PACKAGE_DIR=%CD%\release\%PACKAGE_NAME%"
)
set "BACKUP_ROOT=%LOCALAPPDATA%\%PACKAGE_NAME%\backups\release"

echo ================================================
echo   %PACKAGE_NAME% - release backup
echo ================================================
echo.

if not exist "%PACKAGE_DIR%\%APP_NAME%.exe" (
    echo [FAIL] Current release EXE was not found:
    echo   %PACKAGE_DIR%\%APP_NAME%.exe
    exit /b 2
)

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%" > nul 2>&1
for /f %%T in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "DEST=%BACKUP_ROOT%\%STAMP%"

echo Source:
echo   %PACKAGE_DIR%
echo Backup:
echo   %DEST%
echo.

mkdir "%DEST%" > nul 2>&1
xcopy /E /I /Y "%PACKAGE_DIR%\*" "%DEST%\" > nul
if errorlevel 1 goto fail

>"%BACKUP_ROOT%\latest.txt" echo %DEST%
echo [PASS] Release backup completed.
exit /b 0

:fail
echo.
echo [FAIL] Release backup failed.
exit /b 1
