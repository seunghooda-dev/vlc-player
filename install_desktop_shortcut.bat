@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "TARGET_EXE=%CD%\%APP_NAME%.exe"
set "TARGET_ICON=%CD%\mxf_qc_player.ico"
set "SHORTCUT_NAME=%PACKAGE_NAME%.lnk"

echo ================================================
echo   %PACKAGE_NAME% - target PC shortcut setup
echo ================================================
echo.

if not exist "%TARGET_EXE%" (
    echo [error] ?? ??? ?? ? ????.
    echo   %TARGET_EXE%
    exit /b 1
)

if not exist "%TARGET_ICON%" (
    echo [warning] ??? ??? ?? ? ?? EXE ???? ?????.
    set "TARGET_ICON=%TARGET_EXE%"
)

echo Creating desktop shortcut...
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
  "$shortcut.Description='%PACKAGE_NAME%';" ^
  "$shortcut.IconLocation=$icon + ',0';" ^
  "$shortcut.Save();" ^
  "try { Start-Process -FilePath ie4uinit.exe -ArgumentList '-show' -WindowStyle Hidden -Wait } catch {};" ^
  "Write-Host $shortcutPath"
if errorlevel 1 exit /b 1

echo.
echo Running runtime check...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath $env:TARGET_EXE -ArgumentList '--runtime-check' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo [warning] ?? ?? ?? ??. ? ?? ? CHECK ?? ENV ??? ?????.
) else (
    echo [ok] Runtime check passed.
)

echo.
echo Done.
echo Desktop shortcut:
echo   %USERPROFILE%\Desktop\%SHORTCUT_NAME%
exit /b 0
