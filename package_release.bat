@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "APP_NAME=MasterQC Player"
rem Data folder name is independent from the EXE name (must match constants.APP_DATA_NAME).
set "DATA_NAME=MasterQC"
set "APP_VERSION=V.1.1"
set "PACKAGE_NAME=%APP_NAME% %APP_VERSION%"
set "RELEASE_ROOT=release"
rem How many timestamped release zips to keep. Older ones are pruned after packaging.
set "KEEP_ZIPS=3"
set "PACKAGE_DIR=%CD%\%RELEASE_ROOT%\%PACKAGE_NAME%"
for /f %%T in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "BUILD_STAMP=%%T"
set "ZIP_PATH=%CD%\%RELEASE_ROOT%\%PACKAGE_NAME%_%BUILD_STAMP%.zip"
set "ZIP_LATEST_PATH=%CD%\%RELEASE_ROOT%\%PACKAGE_NAME%.zip"
set "USER_DATA_DIR=%LOCALAPPDATA%\%DATA_NAME%"

echo ================================================
echo   %PACKAGE_NAME% - portable release package
echo ================================================
echo.
echo Release folder:
echo   %PACKAGE_DIR%
echo User data folder:
echo   %USER_DATA_DIR%
echo.

call "%~dp0build.bat"
if errorlevel 1 goto fail

if not exist "dist\%APP_NAME%\%APP_NAME%.exe" (
    echo [error] dist\%APP_NAME%\%APP_NAME%.exe was not found.
    goto fail
)

if exist "%PACKAGE_DIR%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$pkg=$env:PACKAGE_DIR; $data=$env:USER_DATA_DIR; if ($env:LOCALAPPDATA -and (Test-Path -LiteralPath $pkg)) {" ^
      "$names=@('settings.json','archive.db'); $found=$false; foreach($name in $names){ if(Test-Path -LiteralPath (Join-Path $pkg $name)){ $found=$true } }" ^
      "if($found){ $stamp=Get-Date -Format 'yyyyMMdd_HHmmss'; $backup=Join-Path $data ('backups\legacy-release-' + $stamp); New-Item -ItemType Directory -Force -Path $backup | Out-Null; New-Item -ItemType Directory -Force -Path $data | Out-Null;" ^
      "foreach($name in $names){ $src=Join-Path $pkg $name; if(Test-Path -LiteralPath $src){ Copy-Item -LiteralPath $src -Destination (Join-Path $backup $name) -Force; $target=Join-Path $data $name; if(-not (Test-Path -LiteralPath $target)){ Copy-Item -LiteralPath $src -Destination $target -Force } } }" ^
      "$logDir=Join-Path $data 'logs'; New-Item -ItemType Directory -Force -Path $logDir | Out-Null; $event=[ordered]@{timestamp=(Get-Date).ToString('s'); name='legacy-release-runtime'; source=$pkg; target=$backup; status='copied'; message='legacy release settings/db preserved before package refresh'} | ConvertTo-Json -Compress; Add-Content -LiteralPath (Join-Path $logDir 'migration.log') -Value $event -Encoding UTF8;" ^
      "Write-Host ('Preserved legacy runtime data to ' + $backup) } }"
    if errorlevel 1 goto fail
)

if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
mkdir "%PACKAGE_DIR%" > nul 2>&1
mkdir "%PACKAGE_DIR%\tools" > nul 2>&1
mkdir "%PACKAGE_DIR%\LICENSES" > nul 2>&1

echo Copying application files...
xcopy /E /I /Y "dist\%APP_NAME%\*" "%PACKAGE_DIR%\" > nul
if errorlevel 1 goto fail
copy /y "README_RELEASE.txt" "%PACKAGE_DIR%\README.txt" > nul
copy /y "OPERATOR_QUICK_START_KO.txt" "%PACKAGE_DIR%\OPERATOR_QUICK_START_KO.txt" > nul
copy /y "UPDATE_POLICY.txt" "%PACKAGE_DIR%\UPDATE_POLICY.txt" > nul
copy /y "BROADCAST_SAMPLE_CHECKLIST.txt" "%PACKAGE_DIR%\BROADCAST_SAMPLE_CHECKLIST.txt" > nul
copy /y "BROADCAST_SAMPLE_SET.txt" "%PACKAGE_DIR%\BROADCAST_SAMPLE_SET.txt" > nul
copy /y "smoke_mxf_test.bat" "%PACKAGE_DIR%\smoke_mxf_test.bat" > nul
copy /y "stability_mxf_test.bat" "%PACKAGE_DIR%\stability_mxf_test.bat" > nul
copy /y "ui_layout_check.bat" "%PACKAGE_DIR%\ui_layout_check.bat" > nul
copy /y "preflight_check.bat" "%PACKAGE_DIR%\preflight_check.bat" > nul
copy /y "broadcast_sample_validation.bat" "%PACKAGE_DIR%\broadcast_sample_validation.bat" > nul
copy /y "broadcast_sample_set_validation.bat" "%PACKAGE_DIR%\broadcast_sample_set_validation.bat" > nul
copy /y "broadcast_sample_set_validation.ps1" "%PACKAGE_DIR%\broadcast_sample_set_validation.ps1" > nul
copy /y "install_desktop_shortcut.bat" "%PACKAGE_DIR%\install_desktop_shortcut.bat" > nul
copy /y "backup_release.bat" "%PACKAGE_DIR%\backup_release.bat" > nul
copy /y "rollback_release.bat" "%PACKAGE_DIR%\rollback_release.bat" > nul
copy /y "assets\mxf_qc_player.ico" "%PACKAGE_DIR%\mxf_qc_player.ico" > nul
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

set "PACKAGE_EXE=%PACKAGE_DIR%\%APP_NAME%.exe"
echo.
echo Verifying packaged EXE startup path...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath $env:PACKAGE_EXE -ArgumentList '--smoke-test' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto fail

echo.
echo Checking full packaged runtime...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath $env:PACKAGE_EXE -ArgumentList '--runtime-check' -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 (
    echo [warning] Full runtime check found missing optional tools or blocked storage.
    echo           The app will show details with the ENV button on the target PC.
)

echo.
echo Cleaning verification runtime files...
if exist "%PACKAGE_DIR%\archive.db" del /q "%PACKAGE_DIR%\archive.db" > nul 2>&1
if exist "%PACKAGE_DIR%\settings.json" del /q "%PACKAGE_DIR%\settings.json" > nul 2>&1
if exist "%PACKAGE_DIR%\logs" rmdir /s /q "%PACKAGE_DIR%\logs"
if exist "%PACKAGE_DIR%\tmp" rmdir /s /q "%PACKAGE_DIR%\tmp"
if exist "%PACKAGE_DIR%\backups" rmdir /s /q "%PACKAGE_DIR%\backups"

echo.
echo Creating zip package...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%ZIP_PATH%') { Remove-Item -LiteralPath '%ZIP_PATH%' -Force }; if (Test-Path -LiteralPath '%ZIP_LATEST_PATH%') { Remove-Item -LiteralPath '%ZIP_LATEST_PATH%' -Force }; Compress-Archive -LiteralPath '%PACKAGE_DIR%' -DestinationPath '%ZIP_PATH%' -Force; Copy-Item -LiteralPath '%ZIP_PATH%' -Destination '%ZIP_LATEST_PATH%' -Force"
if errorlevel 1 goto fail

echo.
echo Pruning old release zips (keeping newest %KEEP_ZIPS%)...
rem Only timestamped zips of this package are pruned. The latest-copy alias,
rem the release folder, and encrypted .7z hand-off packages are never touched.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%CD%\%RELEASE_ROOT%' -Filter '%PACKAGE_NAME%_*.zip' -File | Sort-Object LastWriteTime -Descending | Select-Object -Skip %KEEP_ZIPS% | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host ('  pruned: ' + $_.Name) }"
if errorlevel 1 goto fail

echo.
echo Release folder:
echo   %PACKAGE_DIR%
echo Release zip:
echo   %ZIP_PATH%
echo Latest zip:
echo   %ZIP_LATEST_PATH%
echo User data folder:
echo   %USER_DATA_DIR%
echo.
echo Done.
exit /b 0

:fail
echo.
echo Release package failed.
exit /b 1
