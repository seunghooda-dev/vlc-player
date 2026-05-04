@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\seung\AppData\Local\Python\bin\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================
echo   Archive Tagger - build desktop executable
echo ================================================
echo.

"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail

"%PY%" check_imports.py
if errorlevel 1 goto fail

where ffmpeg > nul 2>&1
if errorlevel 1 (
    echo [warning] FFmpeg was not found in PATH.
    echo           The EXE will still build, but audio mix / black / mute detection need FFmpeg.
)

where ffplay > nul 2>&1
if errorlevel 1 (
    echo [warning] FFplay was not found in PATH.
    echo           Selected-channel audio output needs FFplay.
)

if not exist "%ProgramFiles%\VideoLAN\VLC\libvlc.dll" (
    if not exist "%ProgramFiles(x86)%\VideoLAN\VLC\libvlc.dll" (
        echo [warning] VLC libvlc.dll was not found in the default Program Files path.
        echo           The EXE will start with a clear warning if VLC is missing.
    )
)

"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ArchiveTagger ^
    --hidden-import vlc ^
    --hidden-import numpy ^
    main.py
if errorlevel 1 goto fail

echo.
echo Build complete: dist\ArchiveTagger.exe
echo Runtime files will be created next to the EXE: archive.db, settings.json, logs\, tmp\
echo External dependencies are not bundled: VLC, FFmpeg, FFplay must be installed or placed in PATH/app tools folder.
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
