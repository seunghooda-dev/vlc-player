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

Version
-------
MXF QC Player V.1.0
