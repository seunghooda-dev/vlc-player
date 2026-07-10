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
set "BACKUP_KEEP=3"

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
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root=$env:BACKUP_ROOT; $keep=[int]$env:BACKUP_KEEP; if(Test-Path -LiteralPath $root){" ^
  "$dirs=Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending;" ^
  "$dirs | Select-Object -Skip $keep | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue };" ^
  "$latest=($dirs | Where-Object { Test-Path -LiteralPath $_.FullName } | Select-Object -First 1);" ^
  "if($latest){ Set-Content -LiteralPath (Join-Path $root 'latest.txt') -Value $latest.FullName -Encoding UTF8 }" ^
  "}"
echo [PASS] Release backup completed.
exit /b 0

:fail
echo.
echo [FAIL] Release backup failed.
exit /b 1
