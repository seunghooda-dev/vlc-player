# Archive Tagger Improvement Checklist

## Phase 1 - Stability and reproducible builds

- [x] Remove stale `_load_stt()` call that crashed file loading.
- [x] Make `check_imports.py` run on Windows console without encoding errors.
- [x] Update `requirements.txt` for the current PyQt desktop app.
- [x] Update `build.bat` for desktop exe builds.
- [x] Update `실행.bat` to launch the PyQt desktop app.
- [x] Rebuild `dist/ArchiveTagger.exe` after script cleanup.
- [x] Launch rebuilt app and confirm it stays running.

## Phase 2 - Codebase cleanup

- [ ] Decide whether legacy `app.py` Flask prototype should be archived or kept.
- [ ] Remove or isolate duplicate DB/probe/timecode logic from the legacy web path.
- [ ] Add a clean developer note for `main.py` vs `app.py`.
- [ ] Review `.gitignore` and keep runtime outputs out of source control.

## Phase 3 - User-facing improvements

- [ ] Add recent folders and recent files.
- [ ] Add quick search/filter in the file explorer.
- [ ] Add a visible cache cleanup action.
- [ ] Improve error messages for FFmpeg, missing files, and conversion failures.
- [ ] Decide whether STT should be restored as a PyQt tab or fully removed.
