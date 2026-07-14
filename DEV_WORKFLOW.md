# MasterQC Development Workflow

Use the fast source workflow while editing code. Build the EXE only when the
change needs to be tested as a packaged app or prepared for release.

## Fast Development

1. Edit Python source files.
2. Run `dev_check.bat`.
3. Run `dev_run.bat` to start `main.py` directly.
4. Commit and push source changes after verification.

`dev_check.bat` is the default fast gate. It runs import consistency checks,
Python bytecode compilation, `git diff --check`, and lightweight regression
checks for metadata QC, settings normalization, audio channel clamping, supported
video extensions, and DF/NDF timecode conversion. It does not launch playback or
build an EXE, so it should stay quick enough to run after ordinary source edits.

Pure-logic unit tests live under `tests\` and run with `pytest` (dev dependency in
`requirements-dev.txt`). They need no GUI or VLC, so they also run headless in CI
(`.github\workflows\ci.yml`). Run them with:

    python -m pytest

The GitHub Actions CI runs the pytest suite plus the full `check_imports.py` gate
(the import gate uses the Qt offscreen platform so it works without a display).

If `ArchiveTagger.spec` exists locally, `dev_check.bat` prints a warning. That
file is a legacy ignored artifact and is not used by the current build path.
Current packaged builds are driven by `build.bat` and use the `MasterQC`
name.

`dev_run.bat` does not build `dist\MasterQC.exe`. If the packaged EXE is
already running, close it before starting the source version so the single
instance guard does not activate the wrong window.

## Packaged EXE

Run `build.bat` only when the packaged EXE must be refreshed:

- before testing PyInstaller-specific behavior
- before handing the EXE to another PC
- after dependency/path changes that only matter in packaged mode

## Release Package

Run `package_release.bat` only when a portable release zip is needed. It calls
`build.bat`, copies the EXE and docs, and optionally includes FFmpeg tools.

## Safety Rule

Do not delete, move, or overwrite source media files during development. Test
scripts should only write inside the app workspace runtime folders such as
`logs\`, `tmp\`, `dist\`, or `release\`.
