@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "TARGET_EXE=%CD%\%APP_NAME%.exe"
set "TARGET_ICON=%CD%\mxf_qc_player.ico"

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
  "$ver='v'+((Get-Item $target).VersionInfo.ProductVersion -replace '\.\d+$','');" ^
  "Get-ChildItem -Path $desktop -Filter '%APP_NAME%*.lnk' -ErrorAction SilentlyContinue | Remove-Item -Force;" ^
  "$shortcutPath=Join-Path $desktop ('%APP_NAME% '+$ver+'.lnk');" ^
  "$shell=New-Object -ComObject WScript.Shell;" ^
  "$shortcut=$shell.CreateShortcut($shortcutPath);" ^
  "$shortcut.TargetPath=$target;" ^
  "$shortcut.WorkingDirectory=(Split-Path -Parent $target);" ^
  "$shortcut.Description=('%APP_NAME% '+$ver);" ^
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
echo Desktop shortcut path is printed above.
exit /b 0
