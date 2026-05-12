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

set "PLAY_SECONDS=%~2"
if not defined PLAY_SECONDS set "PLAY_SECONDS=1800"
set "CHECK_INTERVAL=%~3"
if not defined CHECK_INTERVAL set "CHECK_INTERVAL=30"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - MXF stability test
echo ================================================
echo.
echo Player:
echo   %PLAYER_EXE%
echo Sample:
echo   %SAMPLE_MXF%
echo Duration:
echo   %PLAY_SECONDS% seconds
echo Check interval:
echo   %CHECK_INTERVAL% seconds
echo.

if not exist "%PLAYER_EXE%" (
    echo [FAIL] Player EXE was not found.
    exit /b 2
)

if not defined SAMPLE_MXF (
    echo [FAIL] Sample MXF was not found.
    echo Usage:
    echo   stability_mxf_test.bat "C:\path\sample.mxf" 1800 30
    exit /b 2
)

if not exist "%SAMPLE_MXF%" (
    echo [FAIL] Sample MXF was not found.
    echo Usage:
    echo   stability_mxf_test.bat "C:\path\sample.mxf" 1800 30
    exit /b 2
)

tasklist /FI "IMAGENAME eq %APP_NAME%.exe" 2>nul | find /I "%APP_NAME%.exe" >nul
if not errorlevel 1 (
    echo [FAIL] %APP_NAME% is already running. Close it before the stability test.
    exit /b 3
)

echo Running automated CUE / long playback / audio-process / cleanup check...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe=$env:PLAYER_EXE; & $exe --mxf-stability-test $env:SAMPLE_MXF --play-seconds $env:PLAY_SECONDS --check-interval $env:CHECK_INTERVAL; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [FAIL] MXF stability test failed. Exit code: %RC%
    echo Check LOG in:
    echo   %LOCALAPPDATA%\%APP_NAME% %APP_VERSION%\logs\player.log
    exit /b %RC%
)

echo.
echo Checking for leftover packaged FFmpeg/FFplay helper processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$root=Split-Path -Parent $env:PLAYER_EXE; Start-Sleep -Seconds 2; $left=Get-Process ffmpeg,ffplay -ErrorAction SilentlyContinue | Where-Object { try { $_.Path -like ($root + '*') } catch { $false } }; if($left){ $left | ForEach-Object { Write-Host ('  leftover ' + $_.ProcessName + ' pid=' + $_.Id + ' path=' + $_.Path) }; exit 9 }; exit 0"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [FAIL] Leftover helper process detected.
    exit /b %RC%
)

echo.
echo [PASS] MXF stability test completed.
echo LOG:
echo   %LOCALAPPDATA%\%APP_NAME% %APP_VERSION%\logs\player.log
exit /b 0
