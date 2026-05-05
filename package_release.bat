@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "RELEASE_ROOT=release"
set "PACKAGE_DIR=%RELEASE_ROOT%\%PACKAGE_NAME%"
set "ZIP_PATH=%RELEASE_ROOT%\%PACKAGE_NAME%.zip"

echo ================================================
echo   %PACKAGE_NAME% - portable release package
echo ================================================
echo.

call build.bat
if errorlevel 1 goto fail

if not exist "dist\%APP_NAME%.exe" (
    echo [error] dist\%APP_NAME%.exe was not found.
    goto fail
)

if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
mkdir "%PACKAGE_DIR%" > nul 2>&1
mkdir "%PACKAGE_DIR%\tools" > nul 2>&1
mkdir "%PACKAGE_DIR%\LICENSES" > nul 2>&1

copy /y "dist\%APP_NAME%.exe" "%PACKAGE_DIR%\%APP_NAME%.exe" > nul
copy /y "README_RELEASE.txt" "%PACKAGE_DIR%\README.txt" > nul
copy /y "THIRD_PARTY_NOTICES.txt" "%PACKAGE_DIR%\LICENSES\THIRD_PARTY_NOTICES.txt" > nul

echo.
echo Copying optional FFmpeg tools...
for %%T in (ffmpeg.exe ffprobe.exe ffplay.exe) do (
    for /f "delims=" %%P in ('where %%T 2^>nul') do (
        copy /y "%%P" "%PACKAGE_DIR%\tools\%%T" > nul
    )
    if exist "%PACKAGE_DIR%\tools\%%T" (
        echo   OK %%T
    ) else (
        echo   missing %%T - target PC must provide it in PATH or tools\
    )
)

echo.
echo Creating zip package...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%ZIP_PATH%') { Remove-Item -LiteralPath '%ZIP_PATH%' -Force }; Compress-Archive -LiteralPath '%PACKAGE_DIR%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 goto fail

echo.
echo Release folder:
echo   %PACKAGE_DIR%
echo Release zip:
echo   %ZIP_PATH%
echo.
echo Done.
exit /b 0

:fail
echo.
echo Release package failed.
exit /b 1
