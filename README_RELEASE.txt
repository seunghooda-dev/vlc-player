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
The program creates these files next to the EXE:

- archive.db
- settings.json
- logs\player.log
- tmp\

Do not install this folder under a location that blocks writes, such as a
locked Program Files directory, unless the user has write permission.

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

logs\player.log

Runtime Check
-------------
Use the ENV button in the top bar to verify VLC, FFmpeg, FFprobe, and FFplay.
The dialog shows each tool path, source, version/status, and the feature that
depends on it. It also checks whether the app folder, logs\, and tmp\ are
writable. If write access fails, move the package to a normal user-writable
folder such as Desktop, Documents, or a dedicated media tools folder.

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
smoke test, and starts the packaged EXE.

Version
-------
MXF QC Player V.1.0
