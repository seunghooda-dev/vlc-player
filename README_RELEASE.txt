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
- reports\

The app folder only needs to be readable. The user data folder must be
writable. This separation makes future updates safer because replacing the app
folder does not overwrite operator settings, logs, or QC history.

On first launch after an older package, if settings.json or archive.db is found
only in the old release folder, the app copies it to the user data folder and
shows "기존 설정 복사됨" or "기존 DB 복사됨". If the new user data file already
exists, it is left untouched.

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
the user data folder, logs\, tmp\, backups\, and reports\ are writable.

Use the CHECK button in the top bar before copying the program to another PC.
It summarizes:

- VLC availability
- ffmpeg.exe / ffprobe.exe / ffplay.exe availability
- whether FFmpeg tools are included in tools\
- LOCALAPPDATA write access
- DB/log/tmp/backups/report folder status

Diagnostic Report
-----------------
In the ENV or CHECK dialog, press "리포트 저장" to create a diagnostic ZIP.
The report includes:

- runtime environment text
- package/tool path status
- recent player.log and migration.log tail
- database quick_check result
- current registered child process status

Reports are stored by default under:

%LOCALAPPDATA%\MXF QC Player V.1.0\reports

Automatic Retention
-------------------
On startup, the app automatically removes generated files older than seven
days from these user data folders:

- tmp\
- logs\ rotated log files
- backups\
- reports\

The cleanup is limited to %LOCALAPPDATA%\MXF QC Player V.1.0. Original MXF
files, Desktop files, and files outside the app user data folder are never
removed by this retention policy.

Deployment Smoke Test
---------------------
For deployment checks, the EXE also supports a no-GUI startup test:

MXF QC Player.exe --smoke-test

This verifies that the packaged app can start and write its runtime files. A
stricter dependency check is also available:

MXF QC Player.exe --runtime-check

The strict check returns a non-zero exit code when VLC, FFmpeg, FFprobe,
FFplay, or required writable folders are missing.

For a real MXF playback test, close MXF QC Player first and run:

smoke_mxf_test.bat "C:\path\sample.mxf"

If no path is provided, the script tries to use a MXF file on the Desktop. It
opens the packaged player, loads the sample MXF, waits for CUE, plays for five
seconds, verifies the audio child process, then closes the player. This test is
manual/deployment-only and does not run during normal app startup.

The same test can be called directly:

MXF QC Player.exe --mxf-smoke-test "C:\path\sample.mxf" --play-seconds 5

Long Playback Stability Test
----------------------------
For long-run playback checks, close MXF QC Player first and run:

stability_mxf_test.bat "C:\path\long_sample.mxf" 1800 30

The second value is playback duration in seconds. The third value is the
progress check interval in seconds. The script opens the packaged player,
loads the MXF, plays it for the requested time, logs periodic playback/audio
child-process status, closes the player, and checks that packaged FFmpeg/FFplay
helper processes were not left behind.

The same test can be called directly:

MXF QC Player.exe --mxf-stability-test "C:\path\long_sample.mxf" --play-seconds 1800 --check-interval 30

Use a sample longer than the requested duration. The stability mode intentionally
fails when the sample is shorter than the requested playback time.

Access Notes
------------
When using external drives, NAS, or network shares, make sure the target PC has
read permission and the file is not locked by another program. The player will
show a clearer warning when a drive is disconnected, a network path is
unavailable, or the file cannot be opened.

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
