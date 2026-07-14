@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PACKAGE_DIR=%CD%\release\%APP_NAME% %APP_VERSION%"
set "TARGET_EXE=%PACKAGE_DIR%\%APP_NAME%.exe"
set "TARGET_ICON=%PACKAGE_DIR%\mxf_qc_player.ico"
set "SHORTCUT_NAME=%APP_NAME% %APP_VERSION%.lnk"

echo ================================================
echo   %APP_NAME% %APP_VERSION% - desktop update
echo ================================================
echo.
echo User data is stored outside the release folder:
echo   %LOCALAPPDATA%\%APP_NAME%
echo The release folder will contain only program files, tools, README, and licenses.

if exist "%TARGET_EXE%" (
    echo.
    echo Backing up current release before update...
    call backup_release.bat
    if errorlevel 1 goto fail
)

call package_release.bat
if errorlevel 1 goto fail

if not exist "%TARGET_EXE%" (
    echo [error] Packaged EXE was not found:
    echo   %TARGET_EXE%
    goto fail
)
if not exist "%TARGET_ICON%" (
    echo [warning] Shortcut icon was not found, using EXE icon:
    echo   %TARGET_ICON%
    set "TARGET_ICON=%TARGET_EXE%"
)

echo.
echo Updating desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop=[Environment]::GetFolderPath('Desktop');" ^
  "$target=$env:TARGET_EXE;" ^
  "$icon=$env:TARGET_ICON;" ^
  "$shortcutPath=Join-Path $desktop $env:SHORTCUT_NAME;" ^
  "if(Test-Path -LiteralPath $shortcutPath){ Remove-Item -LiteralPath $shortcutPath -Force };" ^
  "$shell=New-Object -ComObject WScript.Shell;" ^
  "$shortcut=$shell.CreateShortcut($shortcutPath);" ^
  "$shortcut.TargetPath=$target;" ^
  "$shortcut.WorkingDirectory=(Split-Path -Parent $target);" ^
  "$shortcut.Description='%APP_NAME% %APP_VERSION%';" ^
  "$shortcut.IconLocation=$icon + ',0';" ^
  "$shortcut.Save();" ^
  "$legacy=Join-Path $desktop 'MXF QC Player V.1.0.lnk'; if(Test-Path -LiteralPath $legacy){ Remove-Item -LiteralPath $legacy -Force };" ^
  "try { Start-Process -FilePath ie4uinit.exe -ArgumentList '-show' -WindowStyle Hidden -Wait } catch {};" ^
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
echo.
echo Desktop release update failed.
exit /b 1
