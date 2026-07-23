MasterQC Player V.1.1
=====================

This is a portable Windows package for broadcast QC playback and inspection
(MXF, MOV, MP4, and other formats VLC can read).

Quick Start
-----------
1. Run "MasterQC Player.exe".
2. Use "파일 추가" to add MXF files.
3. Double-click a file in the list, or select it and press CUE.
4. Use the Black / Mute tabs for manual QC detection, or press "일괄" in
   the file tab to run black + mute detection for all listed files.
5. During batch QC, press "취소" if the current validation needs to stop.
6. Press "리포트" in the file tab to export the file-list QC result as CSV/TXT.

Korean operator quick guide:

OPERATOR_QUICK_START_KO.txt

Runtime Files
-------------
The release folder is for program files only:

- MasterQC Player.exe
- _internal\
- tools\
- mxf_qc_player.ico
- README.txt
- LICENSES\

User data is stored separately under:

%LOCALAPPDATA%\MasterQC

This folder keeps the shorter name on purpose. The program was renamed to
MasterQC Player, but the data folder is left unchanged so existing settings,
QC history, and reports stay in place after the update.

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

The package uses a folder-style executable build. Keep MasterQC Player.exe and
the _internal\ folder together when moving the app to another PC.

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
- the same folder as MasterQC Player.exe
- or Windows PATH

Logs
----
If a file does not play or a detection job fails, open the LOG button in the
top bar or check:

%LOCALAPPDATA%\MasterQC\logs\player.log

Data migration and legacy release preservation events are recorded in:

%LOCALAPPDATA%\MasterQC\logs\migration.log

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

For a command-line deployment check, close MasterQC Player first and run:

preflight_check.bat

This verifies bundled tools or PATH tools, runs a strict runtime check, runs a
startup smoke test, and confirms the deployment helper scripts are present.
It also warns when release support files are missing, including the Korean quick
guide, update policy, sample checklist, sample set, Desktop shortcut installer,
icon, and third-party notices.

UI Layout Check
---------------
To verify the main window at common operating sizes, close MasterQC Player and
run:

ui_layout_check.bat

The check opens the packaged player briefly and validates the video stage,
timecode, transport controls, volume area, right panel, and file list at
1280x800, 1600x900, and 1920x1080.

Diagnostic Report
-----------------
Press REPORT in the top bar to immediately create a diagnostic ZIP under the
default reports folder. In the ENV or CHECK dialog, press "리포트 저장" if you
want to choose the destination manually. Use "최근 리포트" to open the newest
diagnostic ZIP and "폴더 열기" to open the reports folder.
The report includes:

- runtime environment text
- package/tool path status
- recent player.log and migration.log tail
- database quick_check result
- current registered child process status

Reports are stored by default under:

%LOCALAPPDATA%\MasterQC\reports

QC Result Report
----------------
The file tab has a "리포트" button. It exports the current file list with:

- file name and path
- file size
- media format, codec, resolution, FPS, DF flag, duration, audio channel count,
  source timecode, and bit rate when FFprobe can read them
- QC status
- black detection status and range count
- mute detection status and range count
- last QC update time

CSV export uses UTF-8 with BOM so it opens cleanly in Excel on Windows.
The file list also has filters for "전체", "완료", and "문제" so multiple MXF
files can be reviewed faster after analysis.

Batch QC
--------
The file tab has an "일괄" button. It processes all files in the current list
in order:

1. black detection
2. mute detection on 1/2CH
3. DB status save
4. file-list badge refresh

Playback and audio helper processes are paused while batch analysis is running
so FFmpeg analysis work does not fight with VLC playback.

The "취소" button stops an active batch run after the current analysis worker is
closed. When "자동저장" is checked, a CSV QC report is automatically written to
the reports folder after the batch finishes.

Automatic Retention
-------------------
On startup, the app automatically removes generated files older than seven
days from these user data folders:

- tmp\
- logs\ rotated log files
- backups\
- reports\

The cleanup is limited to %LOCALAPPDATA%\MasterQC. Original MXF
files, Desktop files, and files outside the app user data folder are never
removed by this retention policy.

Deployment Smoke Test
---------------------
For deployment checks, the EXE also supports a no-GUI startup test:

MasterQC Player.exe --smoke-test

This verifies that the packaged app can start and write its runtime files. A
stricter dependency check is also available:

MasterQC Player.exe --runtime-check

The strict check returns a non-zero exit code when VLC, FFmpeg, FFprobe,
FFplay, or required writable folders are missing.

For a real MXF playback test, close MasterQC Player first and run:

smoke_mxf_test.bat "C:\path\sample.mxf"

If no path is provided, the script tries to use a MXF file on the Desktop. It
opens the packaged player, loads the sample MXF, waits for CUE, plays for five
seconds, verifies the audio child process, then closes the player. This test is
manual/deployment-only and does not run during normal app startup.

The same test can be called directly:

MasterQC Player.exe --mxf-smoke-test "C:\path\sample.mxf" --play-seconds 5

Long Playback Stability Test
----------------------------
For long-run playback checks, close MasterQC Player first and run:

stability_mxf_test.bat "C:\path\long_sample.mxf" 1800 30

The second value is playback duration in seconds. The third value is the
progress check interval in seconds. The script opens the packaged player,
loads the MXF, plays it for the requested time, logs periodic playback/audio
child-process status, closes the player, and checks that packaged FFmpeg/FFplay
helper processes were not left behind.

The same test can be called directly:

MasterQC Player.exe --mxf-stability-test "C:\path\long_sample.mxf" --play-seconds 1800 --check-interval 30

Use a sample longer than the requested duration. The stability mode intentionally
fails when the sample is shorter than the requested playback time.

Broadcast Sample Validation
---------------------------
For a practical sample-by-sample release check, close MasterQC Player and run:

broadcast_sample_validation.bat "C:\path\sample-folder"

If a single MXF file is provided, that file is checked. If a folder is provided,
all MXF files directly inside that folder are checked. If no path is provided,
the script checks MXF files on the Desktop. Each sample runs the same automated
CUE / five-second playback / audio-process check used by smoke_mxf_test.bat.

The script writes a report to:

%LOCALAPPDATA%\MasterQC\reports

Use BROADCAST_SAMPLE_CHECKLIST.txt to decide which real-world sample types
should be covered before deployment.

For a fixed real-world broadcast sample set, edit:

BROADCAST_SAMPLE_SET.txt

Each non-comment row uses:

label|absolute_mxf_path|notes

Then run:

broadcast_sample_set_validation.bat BROADCAST_SAMPLE_SET.txt

This is useful when you want every release to pass the same representative
MXF set instead of whatever files happen to be on the Desktop.
The BAT file delegates the row-by-row loop to broadcast_sample_set_validation.ps1
so all sample rows are validated and written to one report.

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

The Desktop shortcut points directly to mxf_qc_player.ico in the release
folder. If the icon design changes, the shortcut is deleted and recreated so
Windows is less likely to keep an old cached icon.

Target PC Shortcut Setup
------------------------
After copying the release folder to another PC, run:

install_desktop_shortcut.bat

It creates a Desktop shortcut pointing to the copied folder, refreshes the
shortcut icon, and runs a runtime check. It does not move or delete user data.

Release ZIPs are written with a timestamped name and a latest-copy alias:

MasterQC Player V.1.1_YYYYMMDD_HHMMSS.zip
MasterQC Player V.1.1.zip

Before replacing the development release folder, update_desktop_release.bat
backs up the current program folder under:

%LOCALAPPDATA%\MasterQC\backups\release

If a new build has a problem, close the app and run rollback_release.bat to
copy the latest release backup back into the release folder.

Version
-------
MasterQC Player V.1.1

The EXE includes Windows file-version metadata. The release update policy is
documented in UPDATE_POLICY.txt.
