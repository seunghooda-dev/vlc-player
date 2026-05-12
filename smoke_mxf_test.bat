@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PLAYER_EXE=%~dp0%APP_NAME%.exe"
if not exist "%PLAYER_EXE%" set "PLAYER_EXE=%~dp0release\%APP_NAME% %APP_VERSION%\%APP_NAME%.exe"

set "SAMPLE_MXF=%~1"
if not defined SAMPLE_MXF if exist "%USERPROFILE%\Desktop\new wide.mxf" set "SAMPLE_MXF=%USERPROFILE%\Desktop\new wide.mxf"
if not defined SAMPLE_MXF if exist "%USERPROFILE%\Desktop\newswide.mxf" set "SAMPLE_MXF=%USERPROFILE%\Desktop\newswide.mxf"
if not defined SAMPLE_MXF for %%F in ("%USERPROFILE%\Desktop\*.mxf") do if not defined SAMPLE_MXF set "SAMPLE_MXF=%%~fF"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - MXF smoke test
echo ================================================
echo.
echo Player:
echo   %PLAYER_EXE%
echo Sample:
echo   %SAMPLE_MXF%
echo.

if not exist "%PLAYER_EXE%" (
    echo [FAIL] Player EXE was not found.
    exit /b 2
)

if not defined SAMPLE_MXF (
    echo [FAIL] Sample MXF was not found.
    echo Usage:
    echo   smoke_mxf_test.bat "C:\path\sample.mxf"
    exit /b 2
)

if not exist "%SAMPLE_MXF%" (
    echo [FAIL] Sample MXF was not found.
    echo Usage:
    echo   smoke_mxf_test.bat "C:\path\sample.mxf"
    exit /b 2
)

tasklist /FI "IMAGENAME eq %APP_NAME%.exe" 2>nul | find /I "%APP_NAME%.exe" >nul
if not errorlevel 1 (
    echo [FAIL] %APP_NAME% is already running. Close it before the smoke test.
    exit /b 3
)

echo Running automated CUE / 5-second playback / audio-process check...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe=$env:PLAYER_EXE; & $exe --mxf-smoke-test $env:SAMPLE_MXF --play-seconds 5; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo [PASS] MXF smoke test completed.
    exit /b 0
)

echo.
echo [FAIL] MXF smoke test failed. Exit code: %RC%
echo Check LOG in the app or:
echo   %LOCALAPPDATA%\%APP_NAME% %APP_VERSION%\logs\player.log
exit /b %RC%
