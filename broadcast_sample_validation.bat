@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PLAYER_EXE=%~dp0%APP_NAME%.exe"
if not exist "%PLAYER_EXE%" set "PLAYER_EXE=%~dp0release\%APP_NAME% %APP_VERSION%\%APP_NAME%.exe"

set "TARGET=%~1"
set "REPORT_DIR=%LOCALAPPDATA%\%APP_NAME%\reports"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%" > nul 2>&1
for /f %%T in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "REPORT=%REPORT_DIR%\broadcast-sample-validation-%STAMP%.txt"
set /a PASS_COUNT=0
set /a FAIL_COUNT=0
set /a SAMPLE_COUNT=0

echo ================================================
echo   %APP_NAME% %APP_VERSION% - broadcast sample validation
echo ================================================
echo.
echo Player:
echo   %PLAYER_EXE%
echo Report:
echo   %REPORT%
echo.

if not exist "%PLAYER_EXE%" (
    echo [FAIL] Player EXE was not found.
    exit /b 2
)

tasklist /FI "IMAGENAME eq %APP_NAME%.exe" 2>nul | find /I "%APP_NAME%.exe" >nul
if not errorlevel 1 (
    echo [FAIL] %APP_NAME% is already running. Close it before validation.
    exit /b 3
)

>"%REPORT%" echo %APP_NAME% %APP_VERSION% broadcast sample validation
>>"%REPORT%" echo Started: %DATE% %TIME%
>>"%REPORT%" echo Player: %PLAYER_EXE%
>>"%REPORT%" echo.

if not "%TARGET%"=="" (
    if exist "%TARGET%\*" (
        echo Target folder: %TARGET%
        >>"%REPORT%" echo Target folder: %TARGET%
        for %%F in ("%TARGET%\*.mxf") do if exist "%%~fF" call :run_one "%%~fF"
    ) else (
        if exist "%TARGET%" (
            call :run_one "%TARGET%"
        ) else (
            echo [FAIL] Target file or folder was not found:
            echo   %TARGET%
            exit /b 2
        )
    )
) else (
    echo No target was provided. Scanning Desktop MXF files.
    >>"%REPORT%" echo Target: Desktop MXF files
    for %%F in ("%USERPROFILE%\Desktop\*.mxf") do if exist "%%~fF" call :run_one "%%~fF"
)

>>"%REPORT%" echo.
>>"%REPORT%" echo Summary: total=%SAMPLE_COUNT% pass=%PASS_COUNT% fail=%FAIL_COUNT%
echo.
echo Summary:
echo   total=%SAMPLE_COUNT% pass=%PASS_COUNT% fail=%FAIL_COUNT%
echo Report:
echo   %REPORT%

if "%SAMPLE_COUNT%"=="0" (
    echo.
    echo [FAIL] No MXF samples were found.
    exit /b 2
)

if not "%FAIL_COUNT%"=="0" (
    echo.
    echo [FAIL] One or more samples failed validation.
    exit /b 8
)

echo.
echo [PASS] Broadcast sample validation completed.
exit /b 0

:run_one
set "SAMPLE=%~1"
set /a SAMPLE_COUNT+=1
echo.
echo [%SAMPLE_COUNT%] %SAMPLE%
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo Sample: %SAMPLE%
call "%~dp0smoke_mxf_test.bat" "%SAMPLE%" >> "%REPORT%" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
    set /a PASS_COUNT+=1
    echo   [PASS]
    >>"%REPORT%" echo Result: PASS
) else (
    set /a FAIL_COUNT+=1
    echo   [FAIL] exit=%RC%
    >>"%REPORT%" echo Result: FAIL exit=%RC%
)
exit /b 0
