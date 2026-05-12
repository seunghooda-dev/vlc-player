@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "SET_FILE=%~1"
if not defined SET_FILE set "SET_FILE=%~dp0BROADCAST_SAMPLE_SET.txt"
set "REPORT_DIR=%LOCALAPPDATA%\%PACKAGE_NAME%\reports"
if not exist "%REPORT_DIR%" mkdir "%REPORT_DIR%" > nul 2>&1
for /f %%T in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
set "REPORT=%REPORT_DIR%\broadcast-sample-set-%STAMP%.txt"
set /a SAMPLE_COUNT=0
set /a PASS_COUNT=0
set /a FAIL_COUNT=0

echo ================================================
echo   %PACKAGE_NAME% - broadcast sample set validation
echo ================================================
echo.
echo Sample set:
echo   %SET_FILE%
echo Report:
echo   %REPORT%
echo.

if not exist "%SET_FILE%" (
    echo [FAIL] Sample set file was not found.
    exit /b 2
)

>"%REPORT%" echo %PACKAGE_NAME% broadcast sample set validation
>>"%REPORT%" echo Started: %DATE% %TIME%
>>"%REPORT%" echo Sample set: %SET_FILE%
>>"%REPORT%" echo.

for /f "usebackq tokens=1,2,* delims=|" %%A in ("%SET_FILE%") do call :run_line "%%~A" "%%~B" "%%~C"

>>"%REPORT%" echo.
>>"%REPORT%" echo Summary: total=%SAMPLE_COUNT% pass=%PASS_COUNT% fail=%FAIL_COUNT%

echo.
echo Summary:
echo   total=%SAMPLE_COUNT% pass=%PASS_COUNT% fail=%FAIL_COUNT%
echo Report:
echo   %REPORT%

if "%SAMPLE_COUNT%"=="0" (
    echo.
    echo [FAIL] No sample rows were found.
    exit /b 2
)

if not "%FAIL_COUNT%"=="0" (
    echo.
    echo [FAIL] One or more samples failed validation.
    exit /b 8
)

echo.
echo [PASS] Broadcast sample set validation completed.
exit /b 0

:run_line
set "LABEL=%~1"
set "SAMPLE=%~2"
set "NOTES=%~3"

if not defined LABEL exit /b 0
if "!LABEL:~0,1!"=="#" exit /b 0
if not defined SAMPLE exit /b 0

set /a SAMPLE_COUNT+=1
echo.
echo [%SAMPLE_COUNT%] !LABEL!
echo   !SAMPLE!
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo Label: !LABEL!
>>"%REPORT%" echo Sample: !SAMPLE!
>>"%REPORT%" echo Notes: !NOTES!

if not exist "!SAMPLE!" (
    set /a FAIL_COUNT+=1
    echo   [FAIL] missing file
    >>"%REPORT%" echo Result: FAIL missing file
    exit /b 0
)

call "%~dp0smoke_mxf_test.bat" "!SAMPLE!" >> "%REPORT%" 2>&1
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" (
    set /a PASS_COUNT+=1
    echo   [PASS]
    >>"%REPORT%" echo Result: PASS
) else (
    set /a FAIL_COUNT+=1
    echo   [FAIL] exit=!RC!
    >>"%REPORT%" echo Result: FAIL exit=!RC!
)
exit /b 0
