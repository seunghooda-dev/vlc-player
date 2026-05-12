@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PLAYER_EXE=%~dp0%APP_NAME%.exe"
if not exist "%PLAYER_EXE%" set "PLAYER_EXE=%~dp0release\%APP_NAME% %APP_VERSION%\%APP_NAME%.exe"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - release preflight
echo ================================================
echo.
echo Player:
echo   %PLAYER_EXE%
echo.

if not exist "%PLAYER_EXE%" (
    echo [FAIL] Player EXE was not found.
    exit /b 2
)

set "ROOT=%~dp0"
if not exist "%ROOT%README.txt" if not exist "%ROOT%README_RELEASE.txt" (
    echo [WARN] README file was not found next to this script.
) else (
    echo [OK] README found.
)

for %%T in (ffmpeg.exe ffprobe.exe ffplay.exe) do (
    if exist "%ROOT%tools\%%T" (
        echo [OK] tools\%%T
    ) else (
        where %%T > nul 2>&1
        if errorlevel 1 (
            echo [FAIL] %%T was not found in tools\ or PATH.
            exit /b 4
        ) else (
            echo [OK] %%T available in PATH.
        )
    )
)

for %%B in (smoke_mxf_test.bat stability_mxf_test.bat ui_layout_check.bat broadcast_sample_validation.bat broadcast_sample_set_validation.bat backup_release.bat rollback_release.bat) do (
    if exist "%ROOT%%%B" (
        echo [OK] %%B
    ) else (
        echo [WARN] %%B is missing.
    )
)

echo.
echo Running packaged UI layout check...
call "%ROOT%ui_layout_check.bat"
if errorlevel 1 (
    echo [FAIL] UI layout check failed.
    exit /b 7
)

echo.
echo Running packaged runtime check...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Start-Process -FilePath $env:PLAYER_EXE -ArgumentList '--runtime-check' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo [FAIL] Runtime check failed.
    exit /b 5
)

echo.
echo Running packaged startup smoke test...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Start-Process -FilePath $env:PLAYER_EXE -ArgumentList '--smoke-test' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo [FAIL] Startup smoke test failed.
    exit /b 6
)

if not "%~1"=="" (
    echo.
    echo Running MXF smoke test:
    echo   %~1
    call "%ROOT%smoke_mxf_test.bat" "%~1"
    if errorlevel 1 exit /b %errorlevel%
)

echo.
echo [PASS] Release preflight completed.
exit /b 0
