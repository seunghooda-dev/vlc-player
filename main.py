"""
main.py — 진입점
MainWindow + 전역 예외 처리 + 앱 실행
"""
import sys
import math
import time
import subprocess
import json
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSplitter, QDialog, QPushButton, QMessageBox, QPlainTextEdit,
    QComboBox, QLineEdit, QFileDialog, QSizePolicy,
)
from PyQt6.QtCore    import Qt, QTimer, QUrl, QCoreApplication
from PyQt6.QtGui     import (
    QColor, QPalette, QFont, QFontDatabase, QIcon, QDesktopServices,
    QShortcut, QKeySequence,
)
from PyQt6.QtMultimedia import QMediaPlayer

from constants    import (
    C, STYLE, LOG_DIR, TMP_DIR, BASE_DIR, RESOURCE_DIR, REPORT_DIR, APP_DIR, USER_DATA_DIR,
    SETTINGS_PATH, DB_PATH, log, APP_FONT_QT,
    check_runtime_environment, format_runtime_environment, format_runtime_startup_alert,
    cleanup_child_processes, cleanup_orphan_audio_processes, runtime_child_process_status,
    cache_summary, cleanup_runtime_cache, cleanup_old_generated_files, format_bytes, format_cache_summary,
    create_diagnostic_report, load_settings, save_settings,
    _hidden_subprocess_flags,
    _path_mtime, _path_size,
)
from video_panel  import VideoPanel
from right_panel  import RightPanel
from threads      import RuntimeWarmupThread, BlackDetectThread, AudioAnalyzeThread, FreezeDetectThread


APP_WINDOW_TITLE = "MXF QC Player V.1.0"
APP_MUTEX_NAME = r"Local\MXF_QC_Player_V1_SingleInstance"
APP_ICON_PATH = RESOURCE_DIR / "assets" / "mxf_qc_player.ico"
_single_instance_handle = None


def _as_dict_result(result, label):
    if isinstance(result, dict):
        return result
    log.warning(f'{label} returned unexpected result type: {type(result).__name__}')
    return {}


def _safe_float(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return int(parsed)
    except Exception:
        pass
    return default


def _final_child_cleanup(label='shutdown'):
    """Run a final two-pass child-process cleanup and log what remains."""
    try:
        summary = _as_dict_result(cleanup_child_processes(), f'{label} child cleanup')
        log.info(
            f'{label} child cleanup pass1: '
            f"running_before={summary.get('running_before')} "
            f"running_after={summary.get('running_after')}"
        )
        if summary.get('running_after'):
            time.sleep(0.25)
            summary = _as_dict_result(cleanup_child_processes(), f'{label} child cleanup retry')
            log.warning(
                f'{label} child cleanup pass2: '
                f"running_before={summary.get('running_before')} "
                f"running_after={summary.get('running_after')}"
            )
        cleaned = cleanup_orphan_audio_processes()
        if cleaned:
            log.warning(f'{label} orphan audio cleanup: {cleaned} process(es)')
        return summary
    except Exception as e:
        log.debug(f'{label} final child cleanup failed: {e}')
        return {}


def _activate_existing_window():
    if not sys.platform.startswith('win'):
        return False
    try:
        import ctypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.FindWindowW(None, APP_WINDOW_TITLE)
        if not hwnd:
            return False
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as e:
        log.debug(f'activate existing window failed: {e}')
        return False


def _acquire_single_instance():
    """Windows named mutex로 중복 실행을 막는다."""
    global _single_instance_handle
    if not sys.platform.startswith('win'):
        return True
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        ERROR_ALREADY_EXISTS = 183
        deadline = time.monotonic() + 6.0
        waited = False
        while True:
            handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
            err = ctypes.get_last_error()
            if not handle:
                log.warning(f'single instance mutex creation failed: {err}')
                return True
            if err != ERROR_ALREADY_EXISTS:
                _single_instance_handle = handle
                if waited:
                    log.info('single instance acquired after stale mutex wait')
                return True
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            if _activate_existing_window():
                log.info('중복 실행 차단 — 기존 창 활성화')
                return False
            if time.monotonic() >= deadline:
                log.info('중복 실행 차단 — 기존 창 미확인')
                return False
            waited = True
            time.sleep(0.25)
    except Exception as e:
        log.warning(f'single instance check failed: {e}')
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = load_settings()
        self._runtime = None
        self._warmup_thread = None
        self._migration_notice_shown = False
        self.setWindowTitle(APP_WINDOW_TITLE)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        size = self._settings.get('window_size', [1400, 980])
        width = _safe_int(size[0] if isinstance(size, (list, tuple)) and len(size) > 0 else 1400, 1400)
        height = _safe_int(size[1] if isinstance(size, (list, tuple)) and len(size) > 1 else 980, 980)
        self.resize(max(640, width), max(480, height))
        self.setMinimumSize(1100, 760)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._build_ui()
        self._install_shortcuts()

    def _install_shortcuts(self):
        self._shortcut_cancel_analysis = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._shortcut_cancel_analysis.setContext(Qt.ShortcutContext.WindowShortcut)
        self._shortcut_cancel_analysis.activated.connect(self._cancel_analysis_shortcut)

    def _cancel_analysis_shortcut(self):
        rp = getattr(self, 'rp', None)
        if not rp:
            return
        try:
            active = bool(getattr(rp, '_analysis_active', None)) or bool(rp._analysis_thread_running())
        except Exception:
            active = bool(getattr(rp, '_analysis_active', None))
        if not active:
            return
        if hasattr(rp, '_cancel_current_analysis'):
            rp._cancel_current_analysis()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # 타이틀 바
        tb = QWidget(); tb.setFixedHeight(42)
        tb.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #080A0F,stop:0.5 #111827,stop:1 #080A0F);"
            f"border-bottom:1px solid {C['border']};"
        )
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(12,0,12,0); tbl.setSpacing(8)
        mark = QLabel('▣')
        mark.setFixedWidth(22)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"color:{C['blue']};font-family:'Segoe UI Symbol','Segoe UI';font-size:17px;"
            "font-weight:700;background:transparent;"
        )
        tbl.addWidget(mark)
        ttl = QLabel("MXF  QC  PLAYER")
        ttl.setStyleSheet(
            f"color:{C['text1']};font-family:'Cascadia Mono','Consolas','D2Coding';"
            "font-size:14px;font-weight:800;letter-spacing:0px;background:transparent;"
        )
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.addWidget(ttl,1)
        _top_btn_style = (
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #1C2433,stop:1 #101722);"
            f"color:{C['text2']};border:1px solid {C['border']};"
            "border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:800;"
            "padding:0 9px;}"
            f"QPushButton:hover{{background:#253149;color:{C['text0']};border-color:{C['blue']};}}"
            "QPushButton:pressed{background:#0B1018;padding-top:1px;}"
        )
        env_btn = QPushButton("ENV")
        env_btn.setFixedHeight(24)
        env_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        env_btn.setToolTip("VLC / FFmpeg 실행 환경 확인")
        env_btn.setStyleSheet(_top_btn_style)
        env_btn.clicked.connect(self._show_runtime_dialog)
        tbl.addWidget(env_btn)
        check_btn = QPushButton("CHECK")
        check_btn.setFixedHeight(24)
        check_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        check_btn.setToolTip("배포 전 체크리스트")
        check_btn.setStyleSheet(_top_btn_style)
        check_btn.clicked.connect(self._show_deployment_check_dialog)
        tbl.addWidget(check_btn)
        cache_btn = QPushButton("CACHE")
        cache_btn.setFixedHeight(24)
        cache_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        cache_btn.setToolTip("tmp 캐시 상태 보기 / 정리")
        cache_btn.setStyleSheet(_top_btn_style)
        cache_btn.clicked.connect(self._show_cache_dialog)
        tbl.addWidget(cache_btn)
        log_btn = QPushButton("LOG")
        log_btn.setFixedHeight(24)
        log_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_btn.setToolTip("최근 오류 로그 보기")
        log_btn.setStyleSheet(_top_btn_style)
        log_btn.clicked.connect(self._show_error_log)
        tbl.addWidget(log_btn)
        report_btn = QPushButton("REPORT")
        report_btn.setFixedHeight(24)
        report_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        report_btn.setToolTip("진단 ZIP을 기본 리포트 폴더에 즉시 저장")
        report_btn.setStyleSheet(_top_btn_style)
        report_btn.clicked.connect(self._quick_save_diagnostic_report)
        tbl.addWidget(report_btn)
        info_btn = QPushButton("INFO")
        info_btn.setFixedHeight(24)
        info_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        info_btn.setToolTip("릴리즈 / 빌드 정보 보기")
        info_btn.setStyleSheet(_top_btn_style)
        info_btn.clicked.connect(self._show_release_info_dialog)
        tbl.addWidget(info_btn)
        ver = QLabel("V.1.0"); ver.setStyleSheet(f"color:{C['text3']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;background:transparent;")
        tbl.addWidget(ver)
        root.addWidget(tb)

        # 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.vp = VideoPanel()
        self.rp = RightPanel(self.vp)
        self.vp._right_panel = self.rp   # Explorer 연동
        self.vp.setMinimumWidth(720)
        self.rp.setMinimumWidth(320)
        self.vp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.rp.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        splitter.addWidget(self.vp)
        splitter.addWidget(self.rp)
        splitter.setChildrenCollapsible(False)
        splitter.setOpaqueResize(True)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            "QSplitter::handle{"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(0,0,0,0),stop:0.42 rgba(0,0,0,0),"
            "stop:0.43 #263247,stop:0.57 #263247,"
            "stop:0.58 rgba(0,0,0,0),stop:1 rgba(0,0,0,0));"
            "border:none;"
            "margin:0;"
            "}"
            "QSplitter::handle:hover{"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(0,0,0,0),stop:0.34 rgba(0,0,0,0),"
            f"stop:0.35 {C['blue']},stop:0.65 {C['teal']},"
            "stop:0.66 rgba(0,0,0,0),stop:1 rgba(0,0,0,0));"
            "border:none;"
            "}"
        )
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        try:
            splitter.handle(1).setCursor(Qt.CursorShape.SizeHorCursor)
        except Exception:
            pass
        splitter_sizes = self._settings.get('splitter_sizes', [980, 420])
        left_size = _safe_int(
            splitter_sizes[0] if isinstance(splitter_sizes, (list, tuple)) and len(splitter_sizes) > 0 else 980,
            980,
        )
        right_size = _safe_int(
            splitter_sizes[1] if isinstance(splitter_sizes, (list, tuple)) and len(splitter_sizes) > 1 else 420,
            420,
        )
        splitter.setSizes([max(100, left_size), max(100, right_size)])
        root.addWidget(splitter, 1)
        self._splitter = splitter

        def _keep_ratio(pos=None, idx=None):
            self._settings = save_settings(splitter_sizes=splitter.sizes())
        self._keep_ratio = _keep_ratio
        splitter.splitterMoved.connect(_keep_ratio)

        # 상태 바
        self.vp.status_changed.connect(self.statusBar().showMessage)
        self.statusBar().showMessage("  ● READY   |   MXF QC Player V.1.0   |   GPU: NVIDIA")

        self.vp.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.vp.setFocus()

    def start_runtime_warmup(self):
        if self._warmup_thread and self._warmup_thread.isRunning():
            return
        recent_files = self._settings.get('recent_files', [])
        if not recent_files:
            log.info('runtime warmup skipped: no recent files')
            return
        t = RuntimeWarmupThread(recent_files[:3])
        self._warmup_thread = t

        def _done(result, thread=t):
            result = _as_dict_result(result, 'runtime warmup')
            tools = result.get('tools') or {}
            if not isinstance(tools, dict):
                log.warning(f"runtime warmup tools returned unexpected type: {type(tools).__name__}")
                tools = {}
            tool_summary = ', '.join(
                f"{name}={_safe_float((state if isinstance(state, dict) else {}).get('elapsed', 0)):.3f}s"
                for name, state in tools.items()
            )
            recent = result.get('recent_probe') or {}
            if not isinstance(recent, dict):
                log.warning(f"runtime warmup recent_probe returned unexpected type: {type(recent).__name__}")
                recent = {}
            recent_summary = ''
            if recent:
                recent_summary = (
                    f" recent={recent.get('file', '?')} "
                    f"ok={recent.get('ok')} "
                    f"source={recent.get('source', 'unknown')} "
                    f"{_safe_float(recent.get('elapsed', 0)):.3f}s"
                )
            log.info(
                f"runtime warmup complete: total={_safe_float(result.get('elapsed', 0)):.3f}s "
                f"tools=[{tool_summary}]{recent_summary}"
            )

        def _cleanup(thread=t):
            if self._warmup_thread is thread:
                self._warmup_thread = None

        t.completed.connect(_done)
        t.finished.connect(_cleanup)
        t.start()
        log.info('runtime warmup started')

    def show_runtime_status(self, runtime):
        self._attach_audio_child_status(runtime)
        self._runtime = runtime
        for item in runtime.get('items', []):
            level = log.info if item.get('ok') else log.warning
            level(f"runtime {item.get('name')}: {item.get('message')}")
        for item in runtime.get('storage', []):
            level = log.info if item.get('ok') else log.warning
            level(f"storage {item.get('name')}: {item.get('message')}")
        for item in runtime.get('migration', []):
            status = item.get('status')
            level = log.warning if status == 'failed' else log.info
            level(f"migration {item.get('name')}: {status} - {item.get('message')}")
        migration_log = runtime.get('migration_log') or {}
        if migration_log.get('path'):
            log.info(f"migration log: {migration_log.get('path')}")
        for err in migration_log.get('errors') or []:
            log.warning(f"migration log write failed: {err}")
        self._log_package_check(runtime)
        self._log_legacy_root_data(runtime)
        self._log_audio_child_status(runtime)
        if runtime.get('ok'):
            msg = "  ● READY   |   VLC / FFmpeg / FFprobe / FFplay / 저장 위치 OK   |   MXF QC Player V.1.0"
            self.statusBar().showMessage(msg)
            try:
                self.vp.ai_lbl.setText("✓ 실행 환경 확인 완료 — VLC / FFmpeg / FFprobe / FFplay / 저장 위치 OK")
            except Exception as e:
                log.debug(f'runtime ai label: {e}')
            self._show_migration_notice(runtime)
            return
        problems = ', '.join(runtime.get('problems', []))
        msg = f"  ⚠ 실행 환경 확인 필요: {problems}"
        self.statusBar().showMessage(msg)
        try:
            self.vp.ai_lbl.setText(f"⚠ 실행 환경 확인 필요: {problems}")
        except Exception as e:
            log.debug(f'runtime warning label: {e}')
        self._show_migration_notice(runtime)

    def _migration_notice_lines(self, runtime):
        labels = {
            'settings.json': '기존 설정 복사됨',
            'archive.db': '기존 DB 복사됨',
        }
        lines = []
        for item in runtime.get('migration', []):
            if item.get('status') != 'copied':
                continue
            label = labels.get(item.get('name'), f"기존 {item.get('name', '데이터')} 복사됨")
            if label not in lines:
                lines.append(label)
        return lines

    def _show_migration_notice(self, runtime):
        if self._migration_notice_shown:
            return
        lines = self._migration_notice_lines(runtime)
        if not lines:
            return
        self._migration_notice_shown = True
        message = ' / '.join(lines)
        log.info(f'migration notice: {message}')
        self.statusBar().showMessage(f"  ✓ {message}", 8000)
        try:
            self.vp.ai_lbl.setText(f"✓ {message}")
        except Exception as e:
            log.debug(f'migration notice label: {e}')

        def _popup():
            QMessageBox.information(
                self,
                "기존 데이터 복사 완료",
                "\n".join(lines) + "\n\n새 사용자 데이터 폴더로 복사했고, 기존 파일은 그대로 보존했습니다."
            )
        QTimer.singleShot(350, _popup)

    def _log_legacy_root_data(self, runtime):
        groups = runtime.get('legacy_data') or []
        if not groups:
            log.info("legacy root data: none")
            return
        for group in groups:
            names = ', '.join(item.get('name', '') for item in group.get('items', []))
            log.info(
                "legacy root data found: "
                f"label={group.get('label')} root={group.get('root')} "
                f"items={names or '-'} policy=inform_only"
            )

    def _log_package_check(self, runtime):
        for item in runtime.get('package_check') or []:
            level = log.info if item.get('ok') else log.warning
            level(
                "package check: "
                f"{item.get('name')} ok={item.get('ok')} "
                f"info={item.get('message')} path={item.get('path') or '-'}"
            )

    def _attach_audio_child_status(self, runtime):
        try:
            audio = self.vp.audio_mix.diagnostic_status()
            audio['expected'] = bool(self.vp._audio_mix_expected())
            runtime['audio_mix'] = audio
        except Exception as e:
            runtime['audio_mix'] = {'error': str(e)}
        return runtime

    def _log_audio_child_status(self, runtime):
        audio = runtime.get('audio_mix') or {}
        if audio:
            log.info(
                "audio child status: "
                f"expected={audio.get('expected')} playing={audio.get('playing')} "
                f"ffmpeg={audio.get('ffmpeg')} pid={audio.get('ffmpeg_pid') or '-'} "
                f"ffplay={audio.get('ffplay')} pid={audio.get('ffplay_pid') or '-'} "
                f"ch={audio.get('channels') or '-'} file={Path(audio.get('file') or '').name or '-'}"
            )
            if audio.get('last_error'):
                log.warning(f"audio child last error: {audio.get('last_error')}")
        children = runtime.get('child_processes') or []
        if children:
            for child in children:
                log.info(
                    "registered child process: "
                    f"pid={child.get('pid')} state={child.get('state')} "
                    f"label={child.get('label')} cmd={child.get('command') or '-'}"
                )
        else:
            log.info("registered child process: none")

    def _deployment_check_text(self, runtime):
        lines = []
        package_items = runtime.get('package_check') or []
        storage_items = runtime.get('storage') or []
        required_ok = bool(runtime.get('ok'))
        package_ok = all(item.get('ok') for item in package_items)
        storage_ok = all(item.get('ok') or not item.get('required', True) for item in storage_items)
        ready = required_ok and package_ok and storage_ok
        lines.append(f"판정: {'배포 가능' if ready else '확인 필요'}")
        lines.append('')
        lines.append('배포 실행본')
        lines.append('-' * 42)
        for item in package_items:
            mark = 'OK' if item.get('ok') else 'CHECK'
            lines.append(f"[{mark}] {item.get('name')} — {item.get('message') or '-'}")
            lines.append(f"  {item.get('path') or '-'}")
            if item.get('hint'):
                lines.append(f"  참고: {item.get('hint')}")
        lines.append('')
        lines.append('저장/로그/DB')
        lines.append('-' * 42)
        for item in storage_items:
            mark = 'OK' if item.get('ok') else 'CHECK'
            lines.append(f"[{mark}] {item.get('name')} — {item.get('message') or '-'}")
            lines.append(f"  {item.get('path') or '-'}")
            if item.get('hint'):
                lines.append(f"  조치: {item.get('hint')}")
        lines.append('')
        lines.append('운영 메모')
        lines.append('-' * 42)
        lines.append('- 다른 PC에서는 VLC 설치 또는 libvlc.dll 포함 경로가 필요합니다.')
        lines.append('- ffmpeg.exe / ffprobe.exe / ffplay.exe는 tools 폴더 포함을 권장합니다.')
        lines.append('- settings.json, archive.db, logs, tmp, backups, reports는 LOCALAPPDATA에 저장됩니다.')
        lines.append('- 문제 발생 시 ENV > 리포트 저장으로 진단 ZIP을 전달하세요.')
        return '\n'.join(lines)

    def _git_commit_short(self):
        roots = []
        for root in (Path(__file__).resolve().parent, BASE_DIR, APP_DIR, APP_DIR.parent):
            try:
                root = Path(root).resolve()
            except Exception:
                continue
            if root not in roots:
                roots.append(root)
        for root in roots:
            if not (root / '.git').exists():
                continue
            try:
                result = subprocess.run(
                    ['git', 'rev-parse', '--short', 'HEAD'],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=_hidden_subprocess_flags(),
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception as e:
                log.debug(f'git commit read failed at {root}: {e}')
        return '-'

    def _latest_release_package(self):
        roots = []
        for root in (APP_DIR.parent, APP_DIR.parent.parent, BASE_DIR / 'release'):
            try:
                root = Path(root).resolve()
            except Exception:
                continue
            if root not in roots:
                roots.append(root)
        candidates = []
        for root in roots:
            try:
                candidates.extend(root.glob('MXF QC Player V.1.0*.zip'))
            except Exception:
                pass
        candidates = [p for p in candidates if p.is_file()]
        if not candidates:
            return None
        return max(candidates, key=_path_mtime)

    def _release_info_text(self, runtime=None):
        runtime = runtime or self._runtime or check_runtime_environment()
        self._attach_audio_child_status(runtime)
        exe_path = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
        try:
            exe_mtime = _path_mtime(exe_path)
            exe_modified = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exe_mtime)) if exe_mtime else '-'
            exe_size = format_bytes(_path_size(exe_path))
        except Exception:
            exe_modified = '-'
            exe_size = '-'
        package = self._latest_release_package()
        if package:
            try:
                package_mtime = _path_mtime(package)
                package_text = (
                    f"{package}\n"
                    f"  modified={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(package_mtime)) if package_mtime else '-'} "
                    f"size={format_bytes(_path_size(package))}"
                )
            except Exception:
                package_text = str(package)
        else:
            package_text = '-'

        lines = []
        lines.append(APP_WINDOW_TITLE)
        lines.append('=' * 52)
        lines.append(f'실행 모드      : {"패키지 EXE" if getattr(sys, "frozen", False) else "개발 실행"}')
        lines.append(f'Git 커밋       : {self._git_commit_short()}')
        lines.append(f'실행 파일      : {exe_path}')
        lines.append(f'실행 파일 정보 : modified={exe_modified} size={exe_size}')
        lines.append(f'최신 패키지    : {package_text}')
        lines.append('')
        lines.append('저장 위치')
        lines.append('-' * 52)
        lines.append(f'APP_DIR        : {APP_DIR}')
        lines.append(f'RESOURCE_DIR   : {RESOURCE_DIR}')
        lines.append(f'USER_DATA_DIR  : {USER_DATA_DIR}')
        lines.append(f'SETTINGS_PATH  : {SETTINGS_PATH}')
        lines.append(f'DB_PATH        : {DB_PATH}')
        lines.append(f'LOG_DIR        : {LOG_DIR}')
        lines.append(f'TMP_DIR        : {TMP_DIR}')
        lines.append(f'REPORT_DIR     : {REPORT_DIR}')
        lines.append('')
        lines.append('런타임 도구')
        lines.append('-' * 52)
        for item in runtime.get('items', []):
            mark = 'OK' if item.get('ok') else 'CHECK'
            lines.append(f"[{mark}] {item.get('name')} — {item.get('message') or '-'}")
            if item.get('path'):
                lines.append(f"  path={item.get('path')}")
        audio = runtime.get('audio_mix') or {}
        lines.append('')
        lines.append('오디오 자식 프로세스')
        lines.append('-' * 52)
        lines.append(
            f"expected={audio.get('expected')} playing={audio.get('playing')} "
            f"ffmpeg={audio.get('ffmpeg')} pid={audio.get('ffmpeg_pid') or '-'} "
            f"ffplay={audio.get('ffplay')} pid={audio.get('ffplay_pid') or '-'} "
            f"ch={audio.get('channels') or '-'}"
        )
        if audio.get('last_error'):
            lines.append(f"last_error={audio.get('last_error')}")
        lines.append('')
        lines.append('메모')
        lines.append('-' * 52)
        lines.append('- 설정, DB, 로그, 캐시, 리포트는 사용자 데이터 폴더에 분리 저장됩니다.')
        lines.append('- QC 요약은 archive.db에 저장되어 파일을 다시 추가해도 상태가 유지됩니다.')
        lines.append('- 재생 진행 이상은 화면을 방해하지 않고 player.log와 진단 리포트에 기록됩니다.')
        return '\n'.join(lines)

    def _show_release_info_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('릴리즈 정보')
        dlg.resize(900, 620)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16,14,16,14)
        lay.setSpacing(10)
        title = QLabel('릴리즈 정보')
        title.setStyleSheet(f"color:{C['text0']};font-size:14px;font-weight:700;background:transparent;")
        lay.addWidget(title)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._release_info_text())
        text.setStyleSheet(
            f"QPlainTextEdit{{background:{C['panel2']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
            "padding:10px;selection-background-color:#264f78;}}"
        )
        lay.addWidget(text, 1)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        copy_btn = QPushButton('복사')
        report_btn = QPushButton('리포트 저장')
        latest_btn = QPushButton('최근 리포트')
        folder_btn = QPushButton('폴더 열기')
        refresh_btn = QPushButton('새로고침')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, report_btn, latest_btn, folder_btn, refresh_btn, close_btn):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:12px;padding:0 14px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )

        def _refresh():
            rt = check_runtime_environment()
            self._attach_audio_child_status(rt)
            text.setPlainText(self._release_info_text(rt))
            title.setText('릴리즈 정보 — 갱신됨')

        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(text.toPlainText()),
            title.setText('릴리즈 정보 — 복사됨')
        ))
        report_btn.clicked.connect(lambda: self._save_diagnostic_report(self._runtime))
        latest_btn.clicked.connect(self._open_latest_diagnostic_report)
        folder_btn.clicked.connect(self._open_reports_folder)
        refresh_btn.clicked.connect(_refresh)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(report_btn)
        rl.addWidget(latest_btn)
        rl.addWidget(folder_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def _save_diagnostic_report(self, runtime=None):
        runtime = runtime or check_runtime_environment()
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        default = REPORT_DIR / 'mxf-qc-diagnostic.zip'
        path, _ = QFileDialog.getSaveFileName(
            self,
            '진단 리포트 저장',
            str(default),
            'ZIP 파일 (*.zip)'
        )
        if not path:
            return
        try:
            report = create_diagnostic_report(path, runtime=runtime)
            log.info(f'diagnostic report exported: {report}')
            QMessageBox.information(self, '진단 리포트 저장 완료', f'진단 리포트를 저장했습니다.\n\n{report}')
        except Exception as e:
            log.error(f'diagnostic report export failed: {e}')
            QMessageBox.warning(self, '진단 리포트 저장 실패', str(e))

    def _quick_save_diagnostic_report(self):
        runtime = check_runtime_environment()
        self._attach_audio_child_status(runtime)
        try:
            report = create_diagnostic_report(runtime=runtime)
            log.info(f'diagnostic report quick-exported: {report}')
            self.statusBar().showMessage(f"  ✓ 진단 리포트 저장 완료 — {report}", 8000)
            QMessageBox.information(self, '진단 리포트 저장 완료', f'진단 리포트를 저장했습니다.\n\n{report}')
        except Exception as e:
            log.error(f'diagnostic report quick export failed: {e}')
            QMessageBox.warning(self, '진단 리포트 저장 실패', str(e))

    def _latest_diagnostic_report(self):
        try:
            candidates = list(REPORT_DIR.glob('mxf-qc-diagnostic-*.zip'))
            candidates.extend(REPORT_DIR.glob('mxf-qc-diagnostic.zip'))
            candidates = [p for p in candidates if p.is_file()]
            if not candidates:
                return None
            return max(candidates, key=_path_mtime)
        except Exception as e:
            log.debug(f'latest diagnostic lookup failed: {e}')
            return None

    def _open_reports_folder(self):
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(REPORT_DIR)))
            self.statusBar().showMessage(f"  📁 리포트 폴더 열기 — {REPORT_DIR}", 5000)
        except Exception as e:
            log.warning(f'open reports folder failed: {e}')
            QMessageBox.warning(self, '리포트 폴더 열기 실패', str(e))

    def _open_latest_diagnostic_report(self):
        report = self._latest_diagnostic_report()
        if not report:
            QMessageBox.information(self, '최근 진단 리포트', '아직 저장된 진단 ZIP이 없습니다.')
            return
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))
            self.statusBar().showMessage(f"  📄 최근 진단 리포트 열기 — {report.name}", 5000)
        except Exception as e:
            log.warning(f'open latest diagnostic failed: {e}')
            QMessageBox.warning(self, '최근 진단 리포트 열기 실패', str(e))

    def _show_deployment_check_dialog(self):
        runtime = check_runtime_environment()
        self._attach_audio_child_status(runtime)
        dlg = QDialog(self)
        dlg.setWindowTitle('배포 전 체크리스트')
        dlg.resize(860, 600)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16,14,16,14)
        lay.setSpacing(10)
        title = QLabel('배포 전 체크리스트')
        title.setStyleSheet(f"color:{C['text0']};font-size:14px;font-weight:700;background:transparent;")
        lay.addWidget(title)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._deployment_check_text(runtime))
        text.setStyleSheet(
            f"QPlainTextEdit{{background:{C['panel2']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
            "padding:10px;selection-background-color:#264f78;}}"
        )
        lay.addWidget(text, 1)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        report_btn = QPushButton('리포트 저장')
        latest_btn = QPushButton('최근 리포트')
        folder_btn = QPushButton('폴더 열기')
        refresh_btn = QPushButton('새로고침')
        close_btn = QPushButton('닫기')
        for btn in (report_btn, latest_btn, folder_btn, refresh_btn, close_btn):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:12px;padding:0 14px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )
        def _refresh():
            rt = check_runtime_environment()
            self._attach_audio_child_status(rt)
            text.setPlainText(self._deployment_check_text(rt))
            title.setText('배포 전 체크리스트 — 갱신됨')
        report_btn.clicked.connect(lambda: self._save_diagnostic_report(runtime))
        latest_btn.clicked.connect(self._open_latest_diagnostic_report)
        folder_btn.clicked.connect(self._open_reports_folder)
        refresh_btn.clicked.connect(_refresh)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(report_btn)
        rl.addWidget(latest_btn)
        rl.addWidget(folder_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def _show_runtime_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('실행 환경 진단')
        dlg.resize(920, 620)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16,14,16,14)
        lay.setSpacing(10)

        title = QLabel('실행 환경 진단')
        title.setStyleSheet(
            f"color:{C['text0']};font-size:14px;font-weight:700;"
            "padding-bottom:4px;background:transparent;"
        )
        lay.addWidget(title)

        summary = QLabel('')
        summary.setStyleSheet(f"color:{C['text1']};font-size:12px;background:transparent;")
        lay.addWidget(summary)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            f"QPlainTextEdit{{background:{C['panel2']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
            "padding:10px;selection-background-color:#264f78;}}"
        )
        lay.addWidget(text, 1)

        def _refresh_runtime():
            runtime = check_runtime_environment()
            self.show_runtime_status(runtime)
            text.setPlainText(format_runtime_environment(runtime))
            if runtime.get('ok'):
                title.setText('실행 환경 진단 — 정상')
                summary.setText('VLC, FFmpeg 계열 도구, 앱 저장 위치가 모두 확인됐습니다.')
            else:
                missing = ', '.join(runtime.get('problems', []))
                title.setText('실행 환경 진단 — 확인 필요')
                summary.setText(f'확인이 필요한 항목: {missing}')

        _refresh_runtime()

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        copy_btn = QPushButton('복사')
        report_btn = QPushButton('리포트 저장')
        latest_btn = QPushButton('최근 리포트')
        folder_btn = QPushButton('폴더 열기')
        refresh_btn = QPushButton('새로고침')
        log_btn = QPushButton('로그 보기')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, report_btn, latest_btn, folder_btn, refresh_btn, log_btn, close_btn):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:12px;padding:0 14px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(text.toPlainText()),
            title.setText('실행 환경 진단 — 복사됨')
        ))
        report_btn.clicked.connect(lambda: self._save_diagnostic_report(self._runtime))
        latest_btn.clicked.connect(self._open_latest_diagnostic_report)
        folder_btn.clicked.connect(self._open_reports_folder)
        refresh_btn.clicked.connect(_refresh_runtime)
        log_btn.clicked.connect(self._show_error_log)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(report_btn)
        rl.addWidget(latest_btn)
        rl.addWidget(folder_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(log_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def _show_cache_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('캐시 관리')
        dlg.resize(860, 560)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16,14,16,14)
        lay.setSpacing(10)

        title = QLabel('캐시 관리')
        title.setStyleSheet(
            f"color:{C['text0']};font-size:14px;font-weight:700;"
            "padding-bottom:4px;background:transparent;"
        )
        lay.addWidget(title)

        summary = QLabel('')
        summary.setStyleSheet(f"color:{C['text1']};font-size:12px;background:transparent;")
        lay.addWidget(summary)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            f"QPlainTextEdit{{background:{C['panel2']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
            "padding:10px;selection-background-color:#264f78;}}"
        )
        lay.addWidget(text, 1)

        def _refresh_cache(label=None):
            data = cache_summary()
            text.setPlainText(format_cache_summary(data))
            base = (
                f"tmp 캐시 {data.get('total_files', 0)}개 파일 / "
                f"{format_bytes(data.get('total_bytes', 0))}"
            )
            summary.setText(label or base)
            title.setText('캐시 관리')

        def _cleanup_cache():
            data = cache_summary()
            if data.get('total_files', 0) == 0 and not data.get('entries'):
                _refresh_cache('정리할 캐시가 없습니다.')
                return
            answer = QMessageBox.question(
                dlg,
                '캐시 정리',
                "앱 tmp 폴더 안의 캐시만 삭제합니다.\n\n"
                f"{TMP_DIR}\n\n"
                "원본 MXF, 바탕화면 파일, 파일 목록은 삭제하지 않습니다.\n"
                "재생 또는 분석 중이라면 먼저 정지한 뒤 실행하는 것을 권장합니다.\n\n"
                f"현재 캐시: {data.get('total_files', 0)}개 파일 / {format_bytes(data.get('total_bytes', 0))}\n\n"
                "정리할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            result = _as_dict_result(cleanup_runtime_cache(), 'cache cleanup')
            failed = result.get('failed', [])
            if not isinstance(failed, list):
                log.warning(f"cache cleanup failed list returned unexpected type: {type(failed).__name__}")
                failed = []
            deleted_entries = _safe_int(result.get('deleted_entries', 0))
            deleted_files = _safe_int(result.get('deleted_files', 0))
            freed_bytes = _safe_int(result.get('freed_bytes', 0))
            label = (
                f"정리 완료: {deleted_entries}개 항목, "
                f"{format_bytes(freed_bytes)} 확보"
            )
            if failed:
                label += f" / 실패 {len(failed)}개"
            log.info(
                f"cache cleanup: entries={deleted_entries} "
                f"files={deleted_files} "
                f"freed={format_bytes(freed_bytes)} "
                f"failed={len(failed)}"
            )
            _refresh_cache(label)
            if failed:
                text.appendPlainText('\n정리 실패 항목\n' + '-' * 42)
                for item in failed[:20]:
                    text.appendPlainText(item)

        _refresh_cache()

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        copy_btn = QPushButton('복사')
        refresh_btn = QPushButton('새로고침')
        cleanup_btn = QPushButton('캐시 정리')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, refresh_btn, cleanup_btn, close_btn):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:12px;padding:0 14px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )
        cleanup_btn.setStyleSheet(
            f"QPushButton{{background:#2a1f21;color:{C['orange']};border:1px solid #5a3a2b;"
            "border-radius:6px;font-size:12px;padding:0 14px;}"
            f"QPushButton:hover{{background:#37241f;color:{C['yellow']};border-color:{C['orange']};}}"
        )
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(text.toPlainText()),
            title.setText('캐시 관리 — 복사됨')
        ))
        refresh_btn.clicked.connect(lambda: _refresh_cache())
        cleanup_btn.clicked.connect(_cleanup_cache)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(cleanup_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def _recent_error_log_text(self, max_lines=300, mode='warn', keyword=''):
        log_path = LOG_DIR / 'player.log'
        try:
            if not log_path.exists():
                return f"로그 파일이 아직 없습니다.\n\n{log_path}"
            lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            modes = {
                'all':   ('ALL', None),
                'warn':  ('WARNING / ERROR / CRITICAL', ('] WARNING', '] ERROR', '] CRITICAL')),
                'error': ('ERROR / CRITICAL', ('] ERROR', '] CRITICAL')),
                'child': ('자식/오디오 프로세스', ('child ', 'audio child', 'audio mix', 'ffplay', 'ffmpeg')),
                'playback': ('VLC / 재생', ('VLC', 'PLAYER ERROR', 'play watchdog', 'cue', 'load_file')),
                'analysis': ('FFmpeg / 분석', ('BlackDetect', 'AudioAnalyze', 'LoudnessAnalyze', 'analysis', 'black detect', 'audio analyze', 'loudness')),
                'db': ('DB / SQLite', ('[DB]', 'sqlite', 'database', 'archive.db')),
            }
            label, levels = modes.get(mode, modes['warn'])
            if levels is None:
                picked = lines[-max_lines:]
            else:
                picked = [line for line in lines if any(level in line for level in levels)][-max_lines:]
            key = str(keyword or '').strip()
            if key:
                picked = [line for line in picked if key.lower() in line.lower()][-max_lines:]
            header = f"LOG FILE: {log_path}\nFILTER : {label}\nKEYWORD: {key or '-'}\nLINES  : {len(picked)} / {len(lines)}\n"
            if not picked:
                return header + "\n표시할 로그가 없습니다."
            return header + "\n" + "\n".join(picked[-max_lines:])
        except Exception as e:
            return f"로그 읽기 실패: {e}"

    def _show_error_log(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('오류 로그')
        dlg.resize(920, 580)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16,14,16,14)
        lay.setSpacing(10)

        title = QLabel('오류 로그')
        title.setStyleSheet(
            f"color:{C['text0']};font-size:14px;font-weight:700;"
            f"padding-bottom:4px;background:transparent;"
        )
        lay.addWidget(title)

        filter_row = QWidget()
        fl = QHBoxLayout(filter_row)
        fl.setContentsMargins(0,0,0,0)
        fl.setSpacing(8)
        filter_lbl = QLabel('필터')
        filter_lbl.setStyleSheet(f"color:{C['text2']};font-size:12px;background:transparent;")
        filter_combo = QComboBox()
        filter_combo.addItem('경고+', 'warn')
        filter_combo.addItem('오류만', 'error')
        filter_combo.addItem('자식/오디오', 'child')
        filter_combo.addItem('VLC/재생', 'playback')
        filter_combo.addItem('FFmpeg/분석', 'analysis')
        filter_combo.addItem('DB', 'db')
        filter_combo.addItem('전체', 'all')
        filter_combo.setFixedHeight(30)
        filter_combo.setStyleSheet(
            f"QComboBox{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            "border-radius:6px;font-size:12px;padding:0 10px;min-width:96px;}"
            f"QComboBox:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            f"QComboBox QAbstractItemView{{background:{C['panel']};color:{C['text1']};"
            f"selection-background-color:rgba(90,167,255,35);border:1px solid {C['border2']};}}"
        )
        fl.addWidget(filter_lbl)
        fl.addWidget(filter_combo)
        keyword_edit = QLineEdit()
        keyword_edit.setPlaceholderText('검색어')
        keyword_edit.setClearButtonEnabled(True)
        keyword_edit.setFixedHeight(30)
        keyword_edit.setStyleSheet(
            f"QLineEdit{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            "border-radius:6px;font-size:12px;padding:0 10px;min-width:150px;}}"
            f"QLineEdit:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        fl.addWidget(keyword_edit)
        fl.addStretch()
        lay.addWidget(filter_row)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            f"QPlainTextEdit{{background:{C['panel2']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;padding:10px;selection-background-color:#264f78;}}"
        )
        lay.addWidget(text, 1)

        def _refresh_log():
            mode = filter_combo.currentData() or 'warn'
            text.setPlainText(self._recent_error_log_text(mode=mode, keyword=keyword_edit.text()))
            title.setText('오류 로그')

        filter_combo.currentIndexChanged.connect(_refresh_log)
        keyword_edit.textChanged.connect(_refresh_log)
        _refresh_log()

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        copy_btn = QPushButton('복사')
        report_btn = QPushButton('리포트 저장')
        refresh_btn = QPushButton('새로고침')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, report_btn, refresh_btn, close_btn):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:12px;padding:0 14px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )
        copy_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(text.toPlainText()),
            title.setText('오류 로그 — 복사됨')
        ))
        report_btn.clicked.connect(lambda: self._save_diagnostic_report(self._runtime))
        refresh_btn.clicked.connect(_refresh_log)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(report_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def dragEnterEvent(self, e):
        self.vp.dragEnterEvent(e)

    def dragMoveEvent(self, e):
        self.vp.dragMoveEvent(e)

    def dragLeaveEvent(self, e):
        self.vp.dragLeaveEvent(e)

    def dropEvent(self, e):
        self.vp.dropEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Question or e.key() == Qt.Key.Key_Slash:
            self._show_shortcut_help()
            return
        self.vp.keyPressEvent(e)

    def _show_shortcut_help(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle('단축키 도움말')
        dlg.setFixedSize(420, 460)
        dlg.setStyleSheet(
            f"background:{C['panel']};color:{C['text0']};"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:13px;"
        )
        lay = QVBoxLayout(dlg); lay.setSpacing(0); lay.setContentsMargins(24,20,24,20)
        title = QLabel('⌨  단축키 목록')
        title.setStyleSheet(f"color:{C['text0']};font-size:15px;font-weight:700;"
                            f"padding-bottom:14px;")
        lay.addWidget(title)
        shortcuts = [
            ('재생 / 일시정지', 'Space'),
            ('IN 설정',        'I'),
            ('OUT 설정',       'O'),
            ('앞 프레임',      '→'),
            ('뒤 프레임',      '←'),
            ('10초 앞으로',    'Shift + →'),
            ('10초 뒤로',      'Shift + ←'),
            ('처음으로',       'Home'),
            ('끝으로',         'End'),
            ('검수 취소',       'Esc'),
            ('이 도움말',      '?  /  /'),
        ]
        for action, key in shortcuts:
            row = QWidget()
            row.setStyleSheet(f"border-bottom:1px solid {C['border']};")
            rl = QHBoxLayout(row); rl.setContentsMargins(0,8,0,8)
            act_lbl = QLabel(action)
            act_lbl.setStyleSheet(f"color:{C['text1']};font-size:12px;background:transparent;")
            key_lbl = QLabel(key)
            key_lbl.setStyleSheet(
                f"background:{C['panel3']};color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';"
                "font-size:12px;padding:2px 10px;border-radius:4px;"
                f"border:1px solid {C['border']};")
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rl.addWidget(act_lbl); rl.addStretch(); rl.addWidget(key_lbl)
            lay.addWidget(row)
        lay.addSpacing(16)
        close_btn = QPushButton('닫기')
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(
            f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            "border-radius:6px;font-size:12px;}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.exec()

    def _shutdown_worker_thread(self, thread, label, wait_ms=3000):
        if not thread:
            return False
        try:
            if hasattr(thread, 'abort'):
                thread.abort()
            if hasattr(thread, 'quit'):
                thread.quit()
            if hasattr(thread, 'isRunning') and not thread.isRunning():
                log.info(f'{label} 종료 확인')
                return True
            if hasattr(thread, 'wait') and thread.wait(wait_ms):
                log.info(f'{label} 종료')
                return True
            log.warning(f'{label} {wait_ms // 1000}초 내 미종료 — 강제 종료')
            if hasattr(thread, 'terminate'):
                thread.terminate()
            if hasattr(thread, 'wait'):
                thread.wait(1000)
            return False
        except RuntimeError as e:
            log.debug(f'{label} already deleted: {e}')
            return True
        except Exception as e:
            log.debug(f'{label} shutdown: {e}')
            return False

    def closeEvent(self, e):
        """창 닫을 때 모든 스레드/프로세스 안전 종료"""
        log.info('closeEvent — 종료 시작')
        try:
            vp = self.vp
            rp = self.rp
            self._log_child_process_snapshot('close begin')
            try:
                self._settings = save_settings(
                    window_size=[self.width(), self.height()],
                    splitter_sizes=self._splitter.sizes()
                )
            except Exception as ex:
                log.debug(f'save window settings: {ex}')

            # 트랜스코드 스레드
            try:
                if hasattr(rp, 'cancel_active_analysis'):
                    rp.cancel_active_analysis('프로그램 종료', wait_ms=1200, restore_runtime=False)
            except Exception as ex:
                log.debug(f'cancel active analysis on close: {ex}')
            try:
                vp._retire_probe()
            except Exception as ex:
                log.debug(f'retire probe on close: {ex}')
            try:
                vp._retire_loudness_analysis()
            except Exception as ex:
                log.debug(f'retire loudness on close: {ex}')
            vp._retire_tc()

            # 작업 스레드 — abort 플래그 → quit → wait → 필요 시 terminate
            worker_threads = []
            if getattr(self, '_warmup_thread', None):
                worker_threads.append((self._warmup_thread, 'warmup_thread'))
            worker_threads.extend((t, 'transcode_thread') for t in list(getattr(vp, '_dead_threads', [])))
            worker_threads.extend((t, 'preconvert_thread') for t in list(getattr(vp, '_preconvert_threads', [])))
            if getattr(rp, '_audio_thread', None):
                worker_threads.append((rp._audio_thread, 'audio_thread'))
            if getattr(rp, '_black_thread', None):
                worker_threads.append((rp._black_thread, 'black_thread'))
            if getattr(rp, '_freeze_thread', None):
                worker_threads.append((rp._freeze_thread, 'freeze_thread'))
            for thread, label in worker_threads:
                self._shutdown_worker_thread(thread, label)
            try:
                vp._dead_threads.clear()
                vp._preconvert_threads.clear()
                vp._preconvert_jobs.clear()
                rp._audio_thread = None
                rp._black_thread = None
                rp._freeze_thread = None
            except Exception as ex:
                log.debug(f'clear worker refs: {ex}')

            # 미터 스레드
            if hasattr(vp, 'meter_ctrl'):
                try: vp.meter_ctrl.set_playing(False)
                except Exception as e: log.debug(f'meter stop: {e}')

            # 플레이어 정지
            try:
                if hasattr(vp, '_cancel_audio_mix'):
                    vp._cancel_audio_mix()
                elif hasattr(vp, 'audio_mix'):
                    vp.audio_mix.stop()
            except Exception as e: log.debug(f'audio_mix stop: {e}')
            try: vp.player.stop()
            except Exception as e: log.debug(f'player stop: {e}')
            _final_child_cleanup('close')
            self._log_child_process_snapshot('close after cleanup')

            # tmp 파일 정리
            _cleanup_tmp_files()
            log.info('closeEvent — 정상 종료')
        except Exception as e:
            log.error(f'closeEvent 오류: {e}')
        e.accept()

    def _log_child_process_snapshot(self, label):
        try:
            rows = runtime_child_process_status()
            if not rows:
                log.info(f'child snapshot {label}: none')
                return
            for row in rows:
                log.info(
                    f"child snapshot {label}: pid={row.get('pid')} "
                    f"state={row.get('state')} label={row.get('label')} "
                    f"cmd={row.get('command') or '-'}"
                )
        except Exception as ex:
            log.debug(f'child snapshot {label}: {ex}')

def _setup_global_exception_handler():
    import traceback, threading

    def _handle(exc_type, exc_val, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_val, exc_tb)
            return
        msg = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        log.critical(f'[UNHANDLED EXCEPTION]\n{msg}')  # logs/player.log 기록
        _safe_console_print(f'[EXCEPTION - 프로그램 유지]\n{msg}')

    sys.excepthook = _handle

    def _thread_handle(args):
        if args.exc_type and not issubclass(args.exc_type, SystemExit):
            _handle(args.exc_type, args.exc_value, args.exc_traceback)
    try:
        threading.excepthook = _thread_handle
    except AttributeError:
        pass

def _cleanup_tmp_files():
    """시작 시 TMP_DIR 전체 정리 + 용량 체크"""
    def _is_within(child, root):
        try:
            child = Path(child).resolve()
            root = Path(root).resolve()
            return child == root or root in child.parents
        except Exception:
            return False

    def _safe_legacy_tmp_move(path):
        try:
            src = Path(path)
            if not src.is_file() or src.is_symlink():
                return
            if not _is_within(src, BASE_DIR):
                log.warning(f'구버전 tmp 이동 건너뜀: BASE_DIR 밖 경로 {src}')
                return
            if not src.name.startswith('_tmp_') or src.suffix.lower() != '.mp4':
                return
            target = TMP_DIR / src.name
            if target.exists():
                log.debug(f'구버전 tmp 이동 건너뜀: 대상 존재 {target.name}')
                return
            src.rename(target)
            log.info(f'구버전 tmp 이동: {src.name} → tmp/')
        except Exception as e:
            log.debug(f'tmp 이동 실패: {e}')

    def _safe_tmp_unlink(path):
        try:
            target = Path(path).resolve()
            if not _is_within(target, TMP_DIR):
                log.warning(f'tmp 정리 건너뜀: TMP_DIR 밖 경로 {target}')
                return 0.0
            if target.is_symlink() or not target.is_file():
                return 0.0
            size_mb = _path_size(target) / 1024**2
            target.unlink(missing_ok=True)
            return size_mb
        except Exception as e:
            log.debug(f'cleanup unlink: {e}')
            return 0.0

    def _tmp_file_record(path):
        try:
            target = Path(path).resolve()
            if not _is_within(target, TMP_DIR):
                return None
            if target.is_symlink() or not target.is_file():
                return None
            return (_path_mtime(target), _path_size(target) / 1024**2, target)
        except Exception as e:
            log.debug(f'cleanup stat skipped: {e}')
            return None

    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        # BASE_DIR에 남아있는 구버전 tmp 파일도 TMP_DIR로 이동
        for old_f in BASE_DIR.glob('_tmp_*.mp4'):
            _safe_legacy_tmp_move(old_f)
        # TMP_DIR 현황. 하위 캐시(audio_index 등)까지 포함해 전체 tmp 용량을 제한한다.
        tmp_records = []
        for p in TMP_DIR.rglob('*'):
            rec = _tmp_file_record(p)
            if rec:
                tmp_records.append(rec)
        tmp_records.sort(key=lambda row: row[0])
        tmp_files = [p for _, _, p in tmp_records]
        total_mb = sum(size_mb for _, size_mb, _ in tmp_records)
        log.info(f'TMP_DIR: {len(tmp_files)}개 파일, {total_mb:.1f}MB')
        # 2GB 초과 시 오래된 것부터 삭제
        while total_mb > 2048 and tmp_files:
            victim = tmp_files.pop(0)
            sz = _safe_tmp_unlink(victim)
            if sz > 0:
                total_mb -= sz
                log.info(f'tmp 정리: {victim.name} ({sz:.1f}MB)')
    except Exception as e: log.warning(f'cleanup_tmp 외곽: {e}')

def _cleanup_old_generated_files():
    try:
        result = _as_dict_result(cleanup_old_generated_files(7), 'old generated file cleanup')
        deleted_count = _safe_int(result.get('deleted_count', 0))
        freed = _safe_int(result.get('freed_bytes', 0))
        deleted = result.get('deleted', [])
        if not isinstance(deleted, list):
            log.warning(f"old generated cleanup deleted list returned unexpected type: {type(deleted).__name__}")
            deleted = []
        failed = result.get('failed', [])
        if not isinstance(failed, list):
            log.warning(f"old generated cleanup failed list returned unexpected type: {type(failed).__name__}")
            failed = []
        if deleted_count:
            log.info(
                f"7일 경과 생성 파일 정리: {deleted_count}개 / {format_bytes(freed)} "
                f"(cutoff={result.get('cutoff')})"
            )
            for item in deleted[:20]:
                if not isinstance(item, dict):
                    continue
                log.info(
                    f"  cleaned[{item.get('section')}] {item.get('path')} "
                    f"age={item.get('age_days')}d size={format_bytes(_safe_int(item.get('bytes', 0)))}"
                )
        else:
            log.info(f"7일 경과 생성 파일 정리: 대상 없음 (cutoff={result.get('cutoff')})")
        for err in failed[:10]:
            log.warning(f'7일 경과 생성 파일 정리 실패: {err}')
    except Exception as e:
        log.warning(f'7일 경과 생성 파일 정리 오류: {e}')

def _configure_app_style(app):
    app.setStyle("Fusion")
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    installed = set(QFontDatabase.families())
    app_font = APP_FONT_QT
    for candidate in ("Pretendard", "Inter", "Segoe UI Variable Text", "Segoe UI", "Noto Sans KR", "Malgun Gothic"):
        if candidate in installed:
            app_font = candidate
            break
    font = QFont(app_font, 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor('#0b0d12'))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Base,            QColor('#090b10'))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor('#141821'))
    palette.setColor(QPalette.ColorRole.Text,            QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Button,          QColor('#171b24'))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(C['blue']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C['text0']))
    app.setPalette(palette)

def _arg_value(name, default=None):
    try:
        idx = sys.argv.index(name)
        return sys.argv[idx + 1]
    except Exception:
        return default

def _safe_console_print(text):
    text = str(text)
    try:
        print(text)
        return
    except UnicodeEncodeError:
        pass
    stream = getattr(sys.stdout, 'buffer', None)
    if stream is None:
        return
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        stream.write(text.encode(encoding, 'backslashreplace') + b'\n')
        stream.flush()
    except Exception:
        try:
            stream.write(text.encode('utf-8', 'replace') + b'\n')
            stream.flush()
        except Exception:
            pass

def _current_process_media_children():
    if os.name != 'nt':
        return []
    script = f"""
$parentPid = {os.getpid()}
Get-CimInstance Win32_Process |
  Where-Object {{ $_.ParentProcessId -eq $parentPid -and ($_.Name -ieq 'ffmpeg.exe' -or $_.Name -ieq 'ffplay.exe') }} |
  ForEach-Object {{ "$($_.ProcessId)|$($_.Name)|$($_.CommandLine)" }}
"""
    try:
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_hidden_subprocess_flags(),
        )
        rows = []
        for line in (proc.stdout or '').splitlines():
            text = ' '.join(str(line or '').split())
            if text:
                rows.append(text[:500])
        return rows
    except Exception as e:
        log.debug(f'current process media child scan skipped: {e}')
        return []

def _run_mxf_smoke_test(filepath, play_seconds=5.0, max_seconds=30.0, check_interval=0.0, mode='smoke'):
    _setup_global_exception_handler()
    path = Path(filepath or '')
    if not path.exists() or not path.is_file():
        log.error(f'mxf smoke test failed: sample not found {filepath}')
        return 2
    if path.suffix.lower() != '.mxf':
        log.error(f'mxf smoke test failed: sample is not MXF {filepath}')
        return 2

    app = QApplication(sys.argv)
    _configure_app_style(app)
    if not _acquire_single_instance():
        log.error('mxf smoke test failed: MXF QC Player is already running')
        return 3

    runtime = check_runtime_environment()
    if not runtime.get('ok'):
        log.error(f"mxf smoke test failed: runtime check {runtime.get('problems')}")
        return 4

    win = MainWindow()
    win.show()
    win.show_runtime_status(runtime)

    result = {'code': 1, 'started_ms': 0, 'finished': False}
    deadline = time.monotonic() + 55.0
    max_seconds = max(1.0, _safe_float(max_seconds, 30.0))
    play_seconds = max(1.0, min(max_seconds, _safe_float(play_seconds, 5.0)))
    check_interval = max(2.0, _safe_float(check_interval, 15.0))
    sample = str(path)
    log.info(f'mxf {mode} test start: file={path.name} play_seconds={play_seconds:.1f}')

    def _checked_audio_channels():
        return [
            _safe_int(ch, 0) for cb, ch in (getattr(win.vp, '_ch_checks', []) or [])
            if cb.isChecked()
        ]

    def _set_checked_audio_channels(channels):
        wanted = {_safe_int(ch, 0) for ch in (channels or [])}
        for cb, ch in (getattr(win.vp, '_ch_checks', []) or []):
            if cb.isEnabled():
                cb.setChecked(_safe_int(ch, 0) in wanted)

    def _status_audio_channels():
        return [
            _safe_int(ch, 0) for ch in (win.vp.audio_mix.process_status().get('channels') or [])
        ]

    def _expected_default_audio_channels():
        if not bool(win.vp._audio_mix_expected()):
            return []
        source_count = _safe_int(win.vp._audio_source_count_from_info(getattr(win.vp, 'cur_info', {}) or {}), 0)
        if source_count <= 0:
            return []
        return [1] if source_count == 1 else [1, 2]

    def _validate_default_audio_selection(stage, require_running_channels=False):
        expected = _expected_default_audio_channels()
        if not expected:
            return ''
        selected = [
            _safe_int(ch, 0) for ch in (win.vp._get_selected_audio_channels() or [])
        ]
        checked = _checked_audio_channels()
        if selected != expected:
            return f'{stage}: selected audio channels {selected} != default {expected}'
        if checked != expected:
            return f'{stage}: checked audio channels {checked} != default {expected}'
        if require_running_channels:
            status_channels = [
                _safe_int(ch, 0) for ch in (win.vp.audio_mix.process_status().get('channels') or [])
            ]
            if status_channels != expected:
                return f'{stage}: audio mix channels {status_channels} != default {expected}'
        log.info(f'mxf {mode} default audio check ok: stage={stage} channels={expected}')
        return ''

    def _check_audio_route_restore():
        if result.get('finished'):
            return
        expected = _expected_default_audio_channels()
        if not expected:
            return _finish(0, 'cue/play/audio ok; route restore skipped no audio')
        selected = [_safe_int(ch, 0) for ch in (win.vp._get_selected_audio_channels() or [])]
        checked = _checked_audio_channels()
        status_channels = _status_audio_channels()
        audio_expected = bool(win.vp._audio_mix_expected())
        audio_ok = True if not audio_expected else bool(win.vp.audio_mix.is_running())
        if selected != expected or checked != expected:
            return _finish(23, f'audio route restore selection failed: selected={selected} checked={checked} expected={expected}')
        if audio_expected and status_channels != expected:
            return _finish(24, f'audio route restore mix failed: channels={status_channels} expected={expected}')
        if not audio_ok:
            return _finish(25, f'audio route restore process not running: {win.vp.audio_mix.process_status()}')
        moved_ms = max(0, _safe_int(win.vp.player.position(), 0) - _safe_int(result.get('started_ms'), 0))
        log.info(f'mxf {mode} audio route restore ok: channels={expected} moved={moved_ms}ms')
        return _finish(0, f'cue/play/audio/route ok moved={moved_ms}ms')

    def _check_audio_route_change():
        if result.get('finished'):
            return
        target = [3, 4]
        route_start_ms = _safe_int(result.get('route_start_ms'), 0)
        now_ms = _safe_int(win.vp.player.position(), 0)
        route_moved_ms = max(0, now_ms - route_start_ms)
        state = win.vp.player.playbackState()
        selected = [_safe_int(ch, 0) for ch in (win.vp._get_selected_audio_channels() or [])]
        checked = _checked_audio_channels()
        status_channels = _status_audio_channels()
        audio_status = win.vp.audio_mix.process_status()
        if state != QMediaPlayer.PlaybackState.PlayingState:
            return _finish(19, f'audio route change stopped playback: state={state}')
        if route_moved_ms < 350:
            return _finish(20, f'audio route change stalled playback: moved={route_moved_ms}ms')
        if selected != target or checked != target:
            return _finish(21, f'audio route selection failed: selected={selected} checked={checked} target={target}')
        if not win.vp.audio_mix.is_running() or status_channels != target:
            return _finish(22, f'audio route mix failed: status={audio_status} target={target}')
        log.info(f'mxf {mode} audio route change ok: channels={target} moved={route_moved_ms}ms')
        default_channels = _expected_default_audio_channels() or [1, 2]
        _set_checked_audio_channels(default_channels)
        win.vp._on_ch_select()
        QTimer.singleShot(900, _check_audio_route_restore)

    def _maybe_check_audio_route_change():
        source_count = _safe_int(win.vp._audio_source_count_from_info(getattr(win.vp, 'cur_info', {}) or {}), 0)
        if mode != 'smoke' or source_count < 4 or result.get('route_checked'):
            return False
        target = [3, 4]
        enabled = {
            _safe_int(ch, 0) for cb, ch in (getattr(win.vp, '_ch_checks', []) or [])
            if cb.isEnabled()
        }
        if not set(target).issubset(enabled):
            log.info(f'mxf {mode} audio route change skipped: enabled={sorted(enabled)} source_count={source_count}')
            return False
        result['route_checked'] = True
        result['route_start_ms'] = _safe_int(win.vp.player.position(), 0)
        log.info(f'mxf {mode} audio route change start: target={target} pos={result["route_start_ms"]}ms')
        _set_checked_audio_channels(target)
        win.vp._on_ch_select()
        QTimer.singleShot(1400, _check_audio_route_change)
        return True

    def _finish(code, message):
        if result.get('finished'):
            return
        result['finished'] = True
        result['code'] = _safe_int(code, 1)
        if code == 0:
            log.info(f'mxf {mode} test PASS: {message}')
        else:
            log.error(f'mxf {mode} test FAIL: {message}')
        try:
            if win.vp.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                win.vp.player.pause()
            if hasattr(win.vp, '_cancel_audio_mix'):
                win.vp._cancel_audio_mix()
        except Exception as e:
            log.debug(f'mxf {mode} test pre-close stop: {e}')

        def _close_window():
            try:
                win.hide()
                cleanup_child_processes()
            except Exception as e:
                log.debug(f'mxf {mode} test shutdown: {e}')
            app.quit()

        QTimer.singleShot(300, _close_window)

    def _check_playback(final=True):
        now_ms = _safe_int(win.vp.player.position(), 0)
        started_ms = _safe_int(result.get('started_ms'), 0)
        moved_ms = max(0, now_ms - started_ms)
        audio_expected = bool(win.vp._audio_mix_expected())
        audio_status = win.vp.audio_mix.process_status()
        audio_ok = True if not audio_expected else bool(win.vp.audio_mix.is_running())
        children = runtime_child_process_status()
        log.info(
            f'mxf smoke playback check: moved={moved_ms}ms '
            f'audio_expected={audio_expected} audio_ok={audio_ok} '
            f'audio={audio_status} children={children}'
        )
        if moved_ms < max(800, _safe_int(play_seconds * 350, 800)):
            return _finish(7, f'playback did not advance enough ({moved_ms}ms)')
        if not audio_ok:
            return _finish(8, f'audio process not running: {audio_status}')
        audio_issue = _validate_default_audio_selection('playback', require_running_channels=audio_expected)
        if audio_issue:
            return _finish(18, audio_issue)
        if _maybe_check_audio_route_change():
            return
        return _finish(0, f'cue/play/audio ok moved={moved_ms}ms')

    def _check_stability_progress():
        if result.get('finished'):
            return
        now = time.monotonic()
        now_ms = _safe_int(win.vp.player.position(), 0)
        started_ms = _safe_int(result.get('started_ms'), 0)
        prev_ms = _safe_int(result.get('last_ms'), started_ms)
        interval_moved = max(0, now_ms - prev_ms)
        total_moved = max(0, now_ms - started_ms)
        audio_expected = bool(win.vp._audio_mix_expected())
        audio_status = win.vp.audio_mix.process_status()
        audio_ok = True if not audio_expected else bool(win.vp.audio_mix.is_running())
        children = runtime_child_process_status()
        state = win.vp.player.playbackState()
        log.info(
            f'mxf stability progress: total={total_moved}ms interval={interval_moved}ms '
            f'pos={now_ms}ms audio_expected={audio_expected} audio_ok={audio_ok} '
            f'audio={audio_status} children={children}'
        )
        if not audio_ok:
            return _finish(8, f'audio process not running: {audio_status}')
        if state != QMediaPlayer.PlaybackState.PlayingState:
            return _finish(10, f'playback stopped unexpectedly: state={state}')
        if interval_moved < 300:
            result['stalled_count'] = _safe_int(result.get('stalled_count'), 0) + 1
        else:
            result['stalled_count'] = 0
        if _safe_int(result.get('stalled_count'), 0) >= 2:
            return _finish(11, f'playback stalled: pos={now_ms}ms')
        result['last_ms'] = now_ms
        if now >= _safe_float(result.get('end_at'), 0.0):
            return _check_playback(final=True)
        QTimer.singleShot(_safe_int(check_interval * 1000, 15000), _check_stability_progress)

    def _start_checked_playback():
        if result.get('finished'):
            return
        cue_ms = _safe_int(result.get('started_ms'), 0)
        now_ms = _safe_int(win.vp.player.position(), 0)
        drift_ms = max(0, now_ms - cue_ms)
        state = win.vp.player.playbackState()
        audio_running = bool(win.vp.audio_mix.is_running())
        log.info(
            f'mxf {mode} cue idle check: state={state} '
            f'pos={now_ms}ms drift={drift_ms}ms audio_running={audio_running}'
        )
        if state == QMediaPlayer.PlaybackState.PlayingState:
            return _finish(14, f'cue started playback before play request: pos={now_ms}ms')
        if audio_running:
            return _finish(15, 'cue started audio before play request')
        if drift_ms > 300:
            return _finish(16, f'cue position advanced before play request: drift={drift_ms}ms')
        audio_issue = _validate_default_audio_selection('cue')
        if audio_issue:
            return _finish(17, audio_issue)

        result['started_ms'] = now_ms
        win.vp.toggle_play()
        if mode == 'stability':
            result['last_ms'] = result['started_ms']
            result['end_at'] = time.monotonic() + play_seconds
            QTimer.singleShot(_safe_int(check_interval * 1000, 15000), _check_stability_progress)
        else:
            QTimer.singleShot(_safe_int(play_seconds * 1000, 5000), _check_playback)

    def _poll_cue():
        if not win.vp.cur_file:
            return _finish(5, 'file was not loaded')
        if win.vp.cur_file != sample:
            return _finish(5, 'loaded file changed unexpectedly')
        if not getattr(win.vp, '_loading', False) and getattr(win.vp, '_cue_ready', False) and getattr(win.vp, '_metadata_ready', False):
            result['started_ms'] = _safe_int(win.vp.player.position(), 0)
            duration_ms = _safe_int(win.vp.player.media_length(), 0)
            if mode == 'stability' and duration_ms > 0 and duration_ms < _safe_int(play_seconds * 1000, 0) + 1500:
                return _finish(12, f'sample shorter than requested: duration={duration_ms}ms play={play_seconds:.1f}s')
            log.info(f'mxf {mode} cue ready: file={path.name} pos={result["started_ms"]}ms duration={duration_ms}ms')
            QTimer.singleShot(450, _start_checked_playback)
            return
        if time.monotonic() > deadline:
            return _finish(6, 'CUE/metadata timeout')
        QTimer.singleShot(150, _poll_cue)

    def _start():
        try:
            win.vp._add_file_to_list(sample)
            win.vp._refresh_clip_list()
            win.vp.load_file(sample)
            QTimer.singleShot(150, _poll_cue)
        except Exception as e:
            _finish(9, str(e))

    QTimer.singleShot(250, _start)
    app.exec()
    try:
        cleanup_result = _as_dict_result(cleanup_child_processes(), f'mxf {mode} test cleanup')
        if cleanup_result.get('running_after'):
            log.error(f'mxf {mode} test cleanup failed: {cleanup_result}')
            if result.get('code') == 0:
                result['code'] = 13
        stray_children = _current_process_media_children()
        if stray_children:
            log.error(f'mxf {mode} test stray media children after cleanup: {stray_children}')
            if result.get('code') == 0:
                result['code'] = 26
        else:
            log.info(f'mxf {mode} test media child cleanup verified')
    except Exception:
        pass
    return result['code']

def _run_mxf_stability_test(filepath, play_seconds=1800.0, check_interval=30.0):
    return _run_mxf_smoke_test(
        filepath,
        play_seconds=play_seconds,
        max_seconds=7200.0,
        check_interval=check_interval,
        mode='stability',
    )

def _qc_media_params(path):
    try:
        from db_models import is_df_fps, probe
        info = probe(str(path))
        fps = max(1.0, _safe_float(info.get('fps'), 29.97))
        df = bool(info.get('df', is_df_fps(fps)))
        return fps, df
    except Exception as e:
        log.warning(f'qc smoke media probe fallback: {Path(path).name} {e}')
        return 29.97, True

def _run_direct_qc_thread(label, thread):
    result = {'payload': None, 'error': None, 'progress': []}
    try:
        thread.progress.connect(lambda msg: result['progress'].append(str(msg)))
        thread.finished.connect(lambda payload: result.update(payload=payload))
        thread.error.connect(lambda err: result.update(error=str(err)))
        started = time.monotonic()
        thread.run()
        result['elapsed'] = round(time.monotonic() - started, 3)
    except Exception as e:
        result['elapsed'] = result.get('elapsed', 0.0)
        result['error'] = str(e)
        log.error(f'qc smoke {label} exception: {e}')
    return result

def _run_qc_smoke_test(
    black_sample=None,
    mute_sample=None,
    freeze_sample=None,
    expect_black_min=0,
    expect_mute_min=0,
    expect_freeze_min=0,
):
    _setup_global_exception_handler()
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    cases = []
    for label, sample, expect_min in (
        ('black', black_sample, expect_black_min),
        ('mute', mute_sample, expect_mute_min),
        ('freeze', freeze_sample, expect_freeze_min),
    ):
        if not sample:
            continue
        path = Path(sample)
        if not path.exists() or not path.is_file():
            log.error(f'qc smoke test failed: {label} sample not found {sample}')
            return 2
        cases.append((label, path, max(0, _safe_int(expect_min, 0))))
    if not cases:
        log.error('qc smoke test failed: no sample paths were provided')
        return 2

    output = []
    exit_code = 0
    for label, path, expect_min in cases:
        fps, df = _qc_media_params(path)
        if label == 'black':
            thread = BlackDetectThread(str(path), fps, 98, 32, df, 0)
        elif label == 'mute':
            thread = AudioAnalyzeThread(str(path), fps, -50, 1.0, df, 0)
        else:
            thread = FreezeDetectThread(str(path), fps, -60, 1.0, df, 0)

        result = _run_direct_qc_thread(label, thread)
        payload = result.get('payload')
        if label == 'mute':
            ranges = payload.get('mutes', []) if isinstance(payload, dict) else []
            extra = {
                'basis': payload.get('channel_basis') if isinstance(payload, dict) else '',
                'cache_hit': payload.get('cache_hit') if isinstance(payload, dict) else None,
                'no_audio': payload.get('no_audio') if isinstance(payload, dict) else None,
            }
        else:
            ranges = payload if isinstance(payload, list) else []
            extra = {}
        count = len(ranges or [])
        item = {
            'test': label,
            'file': str(path),
            'elapsed': result.get('elapsed', 0.0),
            'count': count,
            'expected_min': expect_min,
            'error': result.get('error'),
            'ranges': (ranges or [])[:3],
            'last_progress': result.get('progress', [])[-3:],
        }
        item.update(extra)
        output.append(item)
        if result.get('error') or count < expect_min:
            exit_code = 7
            log.error(f'qc smoke {label} FAIL: count={count} expected_min={expect_min} error={result.get("error")}')
        else:
            log.info(f'qc smoke {label} PASS: count={count} expected_min={expect_min} elapsed={result.get("elapsed")}s')

    _safe_console_print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code

def _run_db_smoke_test():
    _setup_global_exception_handler()
    try:
        from db_models import (
            Clip, Session, engine, load_clip_metadata_hint, load_qc_status,
            qc_summary_from_status, save_clip, update_clip_qc,
        )
    except Exception as e:
        log.error(f'db smoke test failed: import error {e}')
        return 2

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = TMP_DIR / f'db_smoke_{os.getpid()}_{time.time_ns()}.mxf'
    clip_id = ''
    try:
        sample_path.write_bytes(b'MXF QC Player database smoke placeholder\n')
        stat = sample_path.stat()
        clip_id = save_clip({
            'filename': sample_path.name,
            'filepath': str(sample_path),
            'duration': 12.0,
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
            'bit_rate': 0,
            'fps': 29.97,
            'width': 1920,
            'height': 1080,
            'codec': 'SMOKE',
            'channels': 2,
            'audio_stream_count': 1,
            'timecode': '00:00:00;00',
            'format_short': 'MXF',
        })
        if not clip_id:
            log.error('db smoke test failed: save_clip returned empty id')
            return 3

        black_ranges = [{
            'start': 1.0,
            'end': 2.0,
            'duration': 1.0,
            'tc_start': '00:00:01;00',
            'tc_end': '00:00:02;00',
        }]
        mute_ranges = [{
            'start': 4.0,
            'end': 5.5,
            'duration': 1.5,
            'tc_start': '00:00:04;00',
            'tc_end': '00:00:05;15',
        }]
        expected_summary = qc_summary_from_status('found', 'found', 'ok')
        saved = update_clip_qc(
            str(sample_path),
            black='found',
            mute='found',
            freeze='ok',
            black_count=1,
            mute_count=1,
            freeze_count=0,
            black_ranges=black_ranges,
            mute_ranges=mute_ranges,
            freeze_ranges=[],
        )
        metadata_hint = load_clip_metadata_hint(str(sample_path))
        loaded = load_qc_status(str(sample_path))
        with sample_path.open('ab') as fh:
            fh.write(b'replaced media bytes\n')
        stale_metadata_hint = load_clip_metadata_hint(str(sample_path))
        stale_loaded = load_qc_status(str(sample_path))
        checks = [
            ('metadata hint present', bool(metadata_hint.get('metadata_hint'))),
            ('metadata hint dimensions', metadata_hint.get('width') == 1920 and metadata_hint.get('height') == 1080),
            ('metadata hint audio', metadata_hint.get('channels') == 2 and metadata_hint.get('audio_stream_count') == 1),
            ('black status', loaded.get('black') == 'found'),
            ('mute status', loaded.get('mute') == 'found'),
            ('freeze status', loaded.get('freeze') == 'ok'),
            ('black count', loaded.get('black_count') == 1),
            ('mute count', loaded.get('mute_count') == 1),
            ('freeze count', loaded.get('freeze_count') == 0),
            ('black ranges', len(loaded.get('black_ranges') or []) == 1),
            ('mute ranges', len(loaded.get('mute_ranges') or []) == 1),
            ('freeze ranges', loaded.get('freeze_ranges') == []),
            ('summary', loaded.get('summary') == expected_summary),
            ('saved summary', saved.get('summary') == expected_summary),
            ('stale metadata hidden after file replacement', stale_metadata_hint == {}),
            ('stale QC hidden after file replacement', stale_loaded == {}),
        ]
        failed = [name for name, ok in checks if not ok]
        output = {
            'db': str(DB_PATH),
            'file': str(sample_path),
            'clip_id': clip_id,
            'saved': saved,
            'metadata_hint': metadata_hint,
            'loaded': loaded,
            'stale_metadata_hint_after_replace': stale_metadata_hint,
            'stale_loaded_after_replace': stale_loaded,
            'failed': failed,
        }
        _safe_console_print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        if failed:
            log.error(f'db smoke test FAIL: {failed}')
            return 7
        log.info('db smoke test PASS: QC status persisted and restored')
        return 0
    except Exception as e:
        log.error(f'db smoke test failed: {e}')
        return 8
    finally:
        if clip_id:
            try:
                with Session(engine) as session:
                    clip = session.get(Clip, clip_id)
                    if clip:
                        session.delete(clip)
                        session.commit()
            except Exception:
                pass
        try:
            sample_path.unlink(missing_ok=True)
        except Exception:
            pass

def _run_ui_layout_check():
    _setup_global_exception_handler()
    app = QApplication(sys.argv)
    _configure_app_style(app)
    if not _acquire_single_instance():
        log.error('ui layout check failed: MXF QC Player is already running')
        return 3

    win = MainWindow()
    win.show()
    result = {'code': 1}

    def _fail(message):
        log.error(f'ui layout check FAIL: {message}')
        result['code'] = 7
        win.hide()
        QTimer.singleShot(100, app.quit)

    def _check_case(label, width, height):
        win.resize(width, height)
        app.processEvents()
        vp = win.vp
        rp = win.rp
        checks = [
            ('window width', win.width(), 1100),
            ('window height', win.height(), 760),
            ('video stage width', vp.video_stage.width(), 640),
            ('video view width', vp.video_view.width(), 560),
            ('video view height', vp.video_view.height(), 315),
            ('timecode width', vp.tc_main.width(), 340),
            ('transport play width', vp.btn_play.width(), 70),
            ('volume slider width', vp.vol_slider.width(), 110),
            ('right panel width', rp.width(), 260),
            ('file list height', rp.exp_list.height(), 120),
        ]
        for name, actual, minimum in checks:
            if _safe_int(actual, 0) < _safe_int(minimum, 0):
                return f'{label}: {name} too small actual={actual} min={minimum}'
        expected_left = [1, 3, 5, 7]
        expected_right = [2, 4, 6, 8]
        if list(getattr(vp.vlc_side_left, 'channel_numbers', [])) != expected_left:
            return f'{label}: left audio meter channels changed {getattr(vp.vlc_side_left, "channel_numbers", [])}'
        if list(getattr(vp.vlc_side_right, 'channel_numbers', [])) != expected_right:
            return f'{label}: right audio meter channels changed {getattr(vp.vlc_side_right, "channel_numbers", [])}'
        stage_rect = vp.video_stage.rect()
        video_rect = vp.video_view.geometry()
        for name, meter in (
            ('left audio meter', vp.vlc_side_left),
            ('right audio meter', vp.vlc_side_right),
            ('loudness meter', vp.vlc_loud_meter),
        ):
            if meter.parent() is not vp.video_stage:
                return f'{label}: {name} parent changed'
            meter_rect = meter.geometry()
            if not stage_rect.contains(meter_rect):
                return f'{label}: {name} outside video stage {meter_rect}'
            if meter_rect.intersects(video_rect):
                return f'{label}: {name} overlaps video surface {meter_rect} vs {video_rect}'
        log.info(
            f'ui layout check ok: {label} window={win.width()}x{win.height()} '
            f'video={vp.video_view.width()}x{vp.video_view.height()} '
            f'tc={vp.tc_main.width()} right={rp.width()} '
            f'meters=L{expected_left}/R{expected_right}'
        )
        return ''

    def _run():
        try:
            screen = app.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                log.info(
                    f'ui layout check screen: available={geo.width()}x{geo.height()} '
                    f'dpi={screen.logicalDotsPerInch():.1f} scale={screen.devicePixelRatio():.2f}'
                )
            cases = [
                ('minimum-safe', 1280, 800),
                ('hd-workspace', 1600, 900),
                ('full-hd', 1920, 1080),
            ]
            for label, width, height in cases:
                issue = _check_case(label, width, height)
                if issue:
                    return _fail(issue)
            result['code'] = 0
            log.info('ui layout check PASS')
            win.hide()
            cleanup_child_processes()
            QTimer.singleShot(100, app.quit)
        except Exception as e:
            _fail(str(e))

    QTimer.singleShot(300, _run)
    app.exec()
    try:
        cleanup_child_processes()
    except Exception:
        pass
    return result['code']

def main():
    import threading
    _setup_global_exception_handler()
    app = QApplication(sys.argv)
    _configure_app_style(app)
    if not _acquire_single_instance():
        sys.exit(0)
    log.info('=' * 50)
    log.info(f'MXF QC Player 시작 — Python {sys.version.split()[0]}')
    log.info(f'LOG_DIR: {LOG_DIR}')
    cleaned = cleanup_orphan_audio_processes()
    if cleaned:
        log.info(f'고아 오디오 프로세스 정리: {cleaned}개')
    _cleanup_tmp_files()
    _cleanup_old_generated_files()
    runtime = check_runtime_environment()
    if not runtime.get('ok'):
        log.warning(f"runtime check failed: {runtime.get('missing')}")
        QMessageBox.warning(
            None,
            "실행 환경 확인",
            format_runtime_startup_alert(runtime)
        )
        if 'VLC' in runtime.get('missing', []):
            log.error('VLC runtime missing; abort startup before player construction')
            sys.exit(1)
    win = MainWindow()
    win.show()
    win.show_runtime_status(runtime)
    QTimer.singleShot(700, win.start_runtime_warmup)
    ret = app.exec()
    _final_child_cleanup('app exit')
    log.info('MXF QC Player 종료')
    sys.exit(ret)

if __name__ == "__main__":
    if '--mxf-smoke-test' in sys.argv:
        sample = _arg_value('--mxf-smoke-test')
        seconds = _arg_value('--play-seconds', '5')
        sys.exit(_run_mxf_smoke_test(sample, seconds))
    if '--mxf-stability-test' in sys.argv:
        sample = _arg_value('--mxf-stability-test')
        seconds = _arg_value('--play-seconds', '1800')
        interval = _arg_value('--check-interval', '30')
        sys.exit(_run_mxf_stability_test(sample, seconds, interval))
    if '--qc-smoke-test' in sys.argv:
        sys.exit(_run_qc_smoke_test(
            black_sample=_arg_value('--black-sample'),
            mute_sample=_arg_value('--mute-sample'),
            freeze_sample=_arg_value('--freeze-sample'),
            expect_black_min=_arg_value('--expect-black-min', '0'),
            expect_mute_min=_arg_value('--expect-mute-min', '0'),
            expect_freeze_min=_arg_value('--expect-freeze-min', '0'),
        ))
    if '--db-smoke-test' in sys.argv:
        sys.exit(_run_db_smoke_test())
    if '--ui-layout-check' in sys.argv:
        sys.exit(_run_ui_layout_check())
    if '--export-diagnostics' in sys.argv:
        destination = _arg_value('--export-diagnostics') or None
        report = create_diagnostic_report(destination)
        log.info(f'diagnostic report exported: {report}')
        print(report)
        sys.exit(0)
    if '--runtime-check' in sys.argv or '--smoke-test' in sys.argv:
        strict = '--runtime-check' in sys.argv
        runtime = check_runtime_environment()
        log.info(format_runtime_environment(runtime))
        if strict:
            sys.exit(0 if runtime.get('ok') else 2)
        can_start = bool(runtime.get('can_start')) and not runtime.get('storage_issues')
        sys.exit(0 if can_start else 2)
    main()
