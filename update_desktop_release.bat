@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MXF QC Player"
set "APP_VERSION=V.1.0"
set "PACKAGE_DIR=%CD%\release\%APP_NAME% %APP_VERSION%"
set "TARGET_EXE=%PACKAGE_DIR%\%APP_NAME%.exe"
set "SHORTCUT_NAME=%APP_NAME% %APP_VERSION%.lnk"
set "PRESERVE_DIR=%TEMP%\mxf_qc_player_preserve_%RANDOM%%RANDOM%"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - desktop update
echo ================================================
echo.

if exist "%PACKAGE_DIR%" (
    mkdir "%PRESERVE_DIR%" > nul 2>&1
    if exist "%PACKAGE_DIR%\settings.json" copy /y "%PACKAGE_DIR%\settings.json" "%PRESERVE_DIR%\settings.json" > nul
    if exist "%PACKAGE_DIR%\archive.db" copy /y "%PACKAGE_DIR%\archive.db" "%PRESERVE_DIR%\archive.db" > nul
)

call package_release.bat
if errorlevel 1 goto fail

if not exist "%TARGET_EXE%" (
    echo [error] Packaged EXE was not found:
    echo   %TARGET_EXE%
    goto fail
)

if exist "%PRESERVE_DIR%\settings.json" (
    copy /y "%PRESERVE_DIR%\settings.json" "%PACKAGE_DIR%\settings.json" > nul
) else if exist "%CD%\settings.json" (
    copy /y "%CD%\settings.json" "%PACKAGE_DIR%\settings.json" > nul
)
if exist "%PRESERVE_DIR%\archive.db" (
    copy /y "%PRESERVE_DIR%\archive.db" "%PACKAGE_DIR%\archive.db" > nul
)
if exist "%PRESERVE_DIR%" rmdir /s /q "%PRESERVE_DIR%" > nul 2>&1

echo.
echo Updating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$target=$env:TARGET_EXE;" ^
  "$shortcutPath=Join-Path $desktop $env:SHORTCUT_NAME;" ^
  "$shell=New-Object -ComObject WScript.Shell;" ^
  "$shortcut=$shell.CreateShortcut($shortcutPath);" ^
  "$shortcut.TargetPath=$target;" ^
  "$shortcut.WorkingDirectory=(Split-Path -Parent $target);" ^
  "$shortcut.Description='%APP_NAME% %APP_VERSION%';" ^
  "$shortcut.IconLocation=$target + ',0';" ^
  "$shortcut.Save();" ^
  "Write-Host $shortcutPath"
if errorlevel 1 goto fail

echo.
echo Verifying packaged runtime...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath $env:TARGET_EXE -ArgumentList '--smoke-test' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto fail

echo.
echo Starting %APP_NAME% from release package...
start "" "%TARGET_EXE%"

echo.
echo Done.
exit /b 0

:fail
if exist "%PRESERVE_DIR%" rmdir /s /q "%PRESERVE_DIR%" > nul 2>&1
echo.
echo Desktop release update failed.
exit /b 1
