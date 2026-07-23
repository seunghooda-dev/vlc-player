@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC Player"
rem Data folder name is independent from the EXE name (must match constants.APP_DATA_NAME).
set "DATA_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PLAYER_EXE=%~dp0%APP_NAME%.exe"
if not exist "%PLAYER_EXE%" set "PLAYER_EXE=%~dp0release\%APP_NAME% %APP_VERSION%\%APP_NAME%.exe"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - UI layout check
echo ================================================
echo.
echo Player:
echo   %PLAYER_EXE%
echo.

if not exist "%PLAYER_EXE%" (
    echo [FAIL] Player EXE was not found.
    exit /b 2
)

tasklist /FI "IMAGENAME eq %APP_NAME%.exe" 2>nul | find /I "%APP_NAME%.exe" >nul
if not errorlevel 1 (
    echo [FAIL] %APP_NAME% is already running. Close it before the UI layout check.
    exit /b 3
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe=$env:PLAYER_EXE; $p=Start-Process -FilePath $exe -ArgumentList '--ui-layout-check' -Wait -PassThru; exit $p.ExitCode"
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo [PASS] UI layout check completed.
    echo LOG:
    echo   %LOCALAPPDATA%\%DATA_NAME%\logs\player.log
    exit /b 0
)

echo.
echo [FAIL] UI layout check failed. Exit code: %RC%
echo Check LOG:
echo   %LOCALAPPDATA%\%DATA_NAME%\logs\player.log
exit /b %RC%
