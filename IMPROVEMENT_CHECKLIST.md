# MXF QC Player Improvement Checklist

## Phase 1 - Stability and reproducible builds

- [x] Remove stale `_load_stt()` call that crashed file loading.
- [x] Make `check_imports.py` run on Windows console without encoding errors.
- [x] Update `requirements.txt` for the current PyQt desktop app.
- [x] Update `build.bat` for desktop exe builds.
- [x] Stabilize PyInstaller runtime paths for `archive.db`, `settings.json`, `logs`, and `tmp`.
- [x] Add portable release package script with README and optional FFmpeg tools.
- [x] Add in-app runtime diagnostics for VLC, FFmpeg, FFprobe, and FFplay.
- [x] Add writable location diagnostics for app folder, logs, and tmp.
- [x] Add fast development run/check scripts to avoid unnecessary EXE builds.
- [x] Harden app shutdown for transcode, preconvert, black, and mute worker threads.
- [x] Clean stale orphan audio mix processes on startup.
- [x] Add visible in-app cache summary and cleanup action.
- [x] Add playback start watchdog for stalled VLC video or dead audio mix processes.
- [x] Gate first audio mix start until VLC video position actually advances.
- [x] Auto-recover dead audio mix processes during playback with retry limits.
- [x] Lock playback, channel, and analysis controls while CUE loading is active.
- [x] Wait briefly for VLC media readiness before completing MXF CUE.
- [x] Add UI timeout handling for black and mute analysis jobs.
- [x] Recover from corrupt `settings.json` by backing it up and restoring defaults.
- [x] Rotate oversized `player.log` files and prune old log backups.
- [x] Auto-scan full-file EBU R128 loudness on CUE and show exact I/LRA/TP on the meter.
- [x] Update `실행.bat` to launch the PyQt desktop app.
- [x] Rebuild `dist/MXF QC Player.exe` after script cleanup.
- [x] Launch rebuilt app and confirm it stays running.

## Phase 2 - Codebase cleanup

- [ ] Decide whether legacy `app.py` Flask prototype should be archived or kept.
- [ ] Remove or isolate duplicate DB/probe/timecode logic from the legacy web path.
- [ ] Add a clean developer note for `main.py` vs `app.py`.
- [x] Document source-run vs EXE-build workflow for development.
- [x] Review `.gitignore` and keep runtime outputs out of source control.

## Phase 3 - User-facing improvements

- [ ] Add recent folders and recent files.
- [ ] Add quick search/filter in the file explorer.
- [x] Add a visible cache cleanup action.
- [ ] Improve error messages for FFmpeg, missing files, and conversion failures.
- [ ] Decide whether STT should be restored as a PyQt tab or fully removed.
