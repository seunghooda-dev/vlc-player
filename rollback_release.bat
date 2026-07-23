@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC Player"
rem Data folder name is independent from the EXE name (must match constants.APP_DATA_NAME).
set "DATA_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%%APP_NAME%.exe" (
    set "PACKAGE_DIR=%SCRIPT_DIR:~0,-1%"
) else (
    set "PACKAGE_DIR=%CD%\release\%PACKAGE_NAME%"
)
set "BACKUP_ROOT=%LOCALAPPDATA%\%DATA_NAME%\backups\release"
set "SELECTED=%~1"

echo ================================================
echo   %PACKAGE_NAME% - release rollback
echo ================================================
echo.

if not defined SELECTED (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=$env:BACKUP_ROOT; if(Test-Path -LiteralPath $root){ Get-ChildItem -LiteralPath $root -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName }"`) do set "SELECTED=%%P"
)

if not defined SELECTED (
    echo [FAIL] No release backup was found.
    echo Backup root:
    echo   %BACKUP_ROOT%
    exit /b 2
)

if not exist "%SELECTED%\%APP_NAME%.exe" (
    echo [FAIL] Selected backup does not contain %APP_NAME%.exe:
    echo   %SELECTED%
    exit /b 2
)

echo Selected backup:
echo   %SELECTED%
echo Target release:
echo   %PACKAGE_DIR%
echo.

if exist "%PACKAGE_DIR%\%APP_NAME%.exe" (
    echo Creating pre-rollback backup of the current release...
    call backup_release.bat
    if errorlevel 1 goto fail
)

if not exist "%PACKAGE_DIR%" mkdir "%PACKAGE_DIR%" > nul 2>&1
xcopy /E /I /Y "%SELECTED%\*" "%PACKAGE_DIR%\" > nul
if errorlevel 1 goto fail

echo.
echo [PASS] Rollback copy completed.
echo Note: rollback copies files over the release folder and does not delete user data.
exit /b 0

:fail
echo.
echo [FAIL] Release rollback failed.
exit /b 1
