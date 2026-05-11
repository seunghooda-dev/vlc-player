MXF QC Player V.1.0
===================

This is a portable Windows package for MXF QC playback and inspection.

Quick Start
-----------
1. Run "MXF QC Player.exe".
2. Use "파일 추가" to add MXF files.
3. Double-click a file in the list, or select it and press CUE.
4. Use the Black / Mute tabs for manual QC detection.

Runtime Files
-------------
The release folder is for program files only:

- MXF QC Player.exe
- tools\
- README.txt
- LICENSES\

User data is stored separately under:

%LOCALAPPDATA%\MXF QC Player V.1.0

The program creates these files there:

- archive.db
- settings.json
- logs\player.log
- logs\migration.log
- tmp\
- backups\

The app folder only needs to be readable. The user data folder must be
writable. This separation makes future updates safer because replacing the app
folder does not overwrite operator settings, logs, or QC history.

Dependencies
------------
VLC is required for MXF video playback.

Recommended:
- Install VLC from https://www.videolan.org/vlc/

FFmpeg / FFprobe / FFplay are required for:
- selected channel audio output
- audio meters
- black detection
- mute detection

This package may include FFmpeg tools in the tools\ folder. If they are not
included, install FFmpeg or place ffmpeg.exe, ffprobe.exe, and ffplay.exe in:

- tools\
- the same folder as MXF QC Player.exe
- or Windows PATH

Logs
----
If a file does not play or a detection job fails, open the LOG button in the
top bar or check:

%LOCALAPPDATA%\MXF QC Player V.1.0\logs\player.log

Data migration and legacy release preservation events are recorded in:

%LOCALAPPDATA%\MXF QC Player V.1.0\logs\migration.log

This log uses one JSON record per line and is rotated automatically when it
grows large.

Runtime Check
-------------
Use the ENV button in the top bar to verify VLC, FFmpeg, FFprobe, and FFplay.
The dialog shows each tool path, source, version/status, and the feature that
depends on it. It also checks whether the app folder is readable and whether
the user data folder, logs\, tmp\, and backups\ are writable.

Deployment Smoke Test
---------------------
For deployment checks, the EXE also supports a no-GUI startup test:

MXF QC Player.exe --smoke-test

This verifies that the packaged app can start and write its runtime files. A
stricter dependency check is also available:

MXF QC Player.exe --runtime-check

The strict check returns a non-zero exit code when VLC, FFmpeg, FFprobe,
FFplay, or required writable folders are missing.

Desktop Update
--------------
On the development PC, run this helper after source changes when you want the
release EXE and desktop shortcut updated together:

update_desktop_release.bat

It rebuilds the portable package, refreshes the Desktop shortcut, performs a
smoke test, and starts the packaged EXE. It does not copy settings.json,
archive.db, logs\, tmp\, or backups\ back into the release folder. If old
runtime files are found in a previous release folder, they are preserved under
the user data backups folder before the package is refreshed.

Version
-------
MXF QC Player V.1.0
