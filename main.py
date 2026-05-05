"""
main.py — 진입점
MainWindow + 전역 예외 처리 + 앱 실행
"""
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSplitter, QDialog, QPushButton, QMessageBox, QPlainTextEdit,
    QComboBox,
)
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QColor, QPalette, QFont

from constants    import (
    C, STYLE, LOG_DIR, TMP_DIR, BASE_DIR, log, APP_FONT_QT,
    check_runtime_environment, format_runtime_environment,
    cleanup_child_processes, load_settings, save_settings,
)
from video_panel  import VideoPanel
from right_panel  import RightPanel


APP_WINDOW_TITLE = "MXF QC Player V.1.0"
APP_MUTEX_NAME = r"Local\MXF_QC_Player_V1_SingleInstance"
_single_instance_handle = None


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
        handle = kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
        err = ctypes.get_last_error()
        if not handle:
            log.warning(f'single instance mutex creation failed: {err}')
            return True
        if err == 183:  # ERROR_ALREADY_EXISTS
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            _activate_existing_window()
            log.info('중복 실행 차단 — 기존 창 활성화')
            return False
        _single_instance_handle = handle
        return True
    except Exception as e:
        log.warning(f'single instance check failed: {e}')
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._settings = load_settings()
        self._runtime = None
        self.setWindowTitle(APP_WINDOW_TITLE)
        size = self._settings.get('window_size', [1400, 980])
        try:
            self.resize(int(size[0]), int(size[1]))
        except Exception:
            self.resize(1400, 980)
        self.setMinimumSize(1100, 760)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # 타이틀 바
        tb = QWidget(); tb.setFixedHeight(38)
        tb.setStyleSheet(f"background:#101218;border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(10,0,10,0); tbl.setSpacing(6)
        for col in ['#FF5F57','#FFBD2E','#28C941']:
            d=QLabel('⬤'); d.setStyleSheet(f"color:{col};font-size:11px;"); tbl.addWidget(d)
        tbl.addSpacing(8)
        ttl = QLabel("MXF  QC  PLAYER")
        ttl.setStyleSheet(f"color:{C['text1']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:15px;font-weight:700;")
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.addWidget(ttl,1)
        env_btn = QPushButton("ENV")
        env_btn.setFixedHeight(24)
        env_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        env_btn.setToolTip("VLC / FFmpeg 실행 환경 확인")
        env_btn.setStyleSheet(
            f"QPushButton{{background:{C['panel3']};color:{C['text2']};border:1px solid {C['border']};"
            "border-radius:5px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;"
            "padding:0 8px;}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        env_btn.clicked.connect(self._show_runtime_dialog)
        tbl.addWidget(env_btn)
        log_btn = QPushButton("LOG")
        log_btn.setFixedHeight(24)
        log_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_btn.setToolTip("최근 오류 로그 보기")
        log_btn.setStyleSheet(
            f"QPushButton{{background:{C['panel3']};color:{C['text2']};border:1px solid {C['border']};"
            "border-radius:5px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;"
            "padding:0 8px;}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        log_btn.clicked.connect(self._show_error_log)
        tbl.addWidget(log_btn)
        ver = QLabel("V.1.0"); ver.setStyleSheet(f"color:{C['text3']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;")
        tbl.addWidget(ver)
        root.addWidget(tb)

        # 스플리터
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.vp = VideoPanel()
        self.rp = RightPanel(self.vp)
        self.vp._right_panel = self.rp   # Explorer 연동
        splitter.addWidget(self.vp)
        splitter.addWidget(self.rp)
        splitter.setHandleWidth(2)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter_sizes = self._settings.get('splitter_sizes', [980, 420])
        try:
            splitter.setSizes([int(splitter_sizes[0]), int(splitter_sizes[1])])
        except Exception:
            splitter.setSizes([980, 420])
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

    def show_runtime_status(self, runtime):
        self._runtime = runtime
        for item in runtime.get('items', []):
            level = log.info if item.get('ok') else log.warning
            level(f"runtime {item.get('name')}: {item.get('message')}")
        for item in runtime.get('storage', []):
            level = log.info if item.get('ok') else log.warning
            level(f"storage {item.get('name')}: {item.get('message')}")
        if runtime.get('ok'):
            msg = "  ● READY   |   VLC / FFmpeg / FFprobe / FFplay / 저장 위치 OK   |   MXF QC Player V.1.0"
            self.statusBar().showMessage(msg)
            try:
                self.vp.ai_lbl.setText("✓ 실행 환경 확인 완료 — VLC / FFmpeg / FFprobe / FFplay / 저장 위치 OK")
            except Exception as e:
                log.debug(f'runtime ai label: {e}')
            return
        problems = ', '.join(runtime.get('problems', []))
        msg = f"  ⚠ 실행 환경 확인 필요: {problems}"
        self.statusBar().showMessage(msg)
        try:
            self.vp.ai_lbl.setText(f"⚠ 실행 환경 확인 필요: {problems}")
        except Exception as e:
            log.debug(f'runtime warning label: {e}')

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
        refresh_btn = QPushButton('새로고침')
        log_btn = QPushButton('로그 보기')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, refresh_btn, log_btn, close_btn):
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
        refresh_btn.clicked.connect(_refresh_runtime)
        log_btn.clicked.connect(self._show_error_log)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(log_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def _recent_error_log_text(self, max_lines=300, mode='warn'):
        log_path = LOG_DIR / 'player.log'
        try:
            if not log_path.exists():
                return f"로그 파일이 아직 없습니다.\n\n{log_path}"
            lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            modes = {
                'all':   ('ALL', None),
                'warn':  ('WARNING / ERROR / CRITICAL', ('] WARNING', '] ERROR', '] CRITICAL')),
                'error': ('ERROR / CRITICAL', ('] ERROR', '] CRITICAL')),
            }
            label, levels = modes.get(mode, modes['warn'])
            if levels is None:
                picked = lines[-max_lines:]
            else:
                picked = [line for line in lines if any(level in line for level in levels)][-max_lines:]
            header = f"LOG FILE: {log_path}\nFILTER : {label}\nLINES  : {len(picked)} / {len(lines)}\n"
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
            text.setPlainText(self._recent_error_log_text(mode=mode))
            title.setText('오류 로그')

        filter_combo.currentIndexChanged.connect(_refresh_log)
        _refresh_log()

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.addStretch()
        copy_btn = QPushButton('복사')
        refresh_btn = QPushButton('새로고침')
        close_btn = QPushButton('닫기')
        for btn in (copy_btn, refresh_btn, close_btn):
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
        refresh_btn.clicked.connect(_refresh_log)
        close_btn.clicked.connect(dlg.accept)
        rl.addWidget(copy_btn)
        rl.addWidget(refresh_btn)
        rl.addWidget(close_btn)
        lay.addWidget(row)
        dlg.exec()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()

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
            ('정지',           'S'),
            ('IN 설정',        'I'),
            ('OUT 설정',       'O'),
            ('앞 프레임',      '→'),
            ('뒤 프레임',      '←'),
            ('10초 앞으로',    'Shift + →'),
            ('10초 뒤로',      'Shift + ←'),
            ('처음으로',       'Home'),
            ('끝으로',         'End'),
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
            try:
                self._settings = save_settings(
                    window_size=[self.width(), self.height()],
                    splitter_sizes=self._splitter.sizes()
                )
            except Exception as ex:
                log.debug(f'save window settings: {ex}')

            # 트랜스코드 스레드
            vp._retire_tc()

            # 작업 스레드 — abort 플래그 → quit → wait → 필요 시 terminate
            worker_threads = []
            worker_threads.extend((t, 'transcode_thread') for t in list(getattr(vp, '_dead_threads', [])))
            worker_threads.extend((t, 'preconvert_thread') for t in list(getattr(vp, '_preconvert_threads', [])))
            if getattr(rp, '_audio_thread', None):
                worker_threads.append((rp._audio_thread, 'audio_thread'))
            if getattr(rp, '_black_thread', None):
                worker_threads.append((rp._black_thread, 'black_thread'))
            for thread, label in worker_threads:
                self._shutdown_worker_thread(thread, label)
            try:
                vp._dead_threads.clear()
                vp._preconvert_threads.clear()
                vp._preconvert_jobs.clear()
                rp._audio_thread = None
                rp._black_thread = None
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
            try:
                cleanup_child_processes()
            except Exception as e:
                log.debug(f'cleanup child processes: {e}')

            # tmp 파일 정리
            _cleanup_tmp_files()
            log.info('closeEvent — 정상 종료')
        except Exception as e:
            log.error(f'closeEvent 오류: {e}')
        e.accept()

def _setup_global_exception_handler():
    import traceback, threading

    def _handle(exc_type, exc_val, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_val, exc_tb)
            return
        msg = ''.join(traceback.format_exception(exc_type, exc_val, exc_tb))
        log.critical(f'[UNHANDLED EXCEPTION]\n{msg}')  # logs/player.log 기록
        print(f'[EXCEPTION — 프로그램 유지]\n{msg}')

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
    try:
        TMP_DIR.mkdir(exist_ok=True)
        # BASE_DIR에 남아있는 구버전 tmp 파일도 TMP_DIR로 이동
        for old_f in BASE_DIR.glob('_tmp_*.mp4'):
            try:
                new_f = TMP_DIR / old_f.name.lstrip('_tmp_')
                old_f.rename(TMP_DIR / old_f.name)
                log.info(f'구버전 tmp 이동: {old_f.name} → tmp/')
            except Exception as e: log.debug(f'tmp 이동 실패: {e}')
        # TMP_DIR 현황
        tmp_files = sorted(TMP_DIR.glob('*.mp4'),
                           key=lambda p: p.stat().st_mtime)
        total_mb = sum(p.stat().st_size for p in tmp_files) / 1024**2
        log.info(f'TMP_DIR: {len(tmp_files)}개 파일, {total_mb:.1f}MB')
        # 2GB 초과 시 오래된 것부터 삭제
        while total_mb > 2048 and tmp_files:
            victim = tmp_files.pop(0)
            sz = victim.stat().st_size / 1024**2
            try:
                victim.unlink(missing_ok=True)
                total_mb -= sz
                log.info(f'tmp 정리: {victim.name} ({sz:.1f}MB)')
            except Exception as e: log.debug(f'cleanup unlink: {e}')
    except Exception as e: log.warning(f'cleanup_tmp 외곽: {e}')

def main():
    import threading
    _setup_global_exception_handler()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont(APP_FONT_QT, 10))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(C['bg']))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Base,            QColor(C['input']))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(C['panel']))
    palette.setColor(QPalette.ColorRole.Text,            QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Button,          QColor('#3a3a3a'))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(C['text0']))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor('#1a4a8a'))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C['text0']))
    app.setPalette(palette)
    if not _acquire_single_instance():
        sys.exit(0)
    log.info('=' * 50)
    log.info(f'MXF QC Player 시작 — Python {sys.version.split()[0]}')
    log.info(f'LOG_DIR: {LOG_DIR}')
    _cleanup_tmp_files()
    runtime = check_runtime_environment()
    if not runtime.get('ok'):
        details = format_runtime_environment(runtime)
        log.warning(f"runtime check failed: {runtime.get('missing')}")
        QMessageBox.warning(
            None,
            "실행 환경 확인",
            "실행 환경을 확인했습니다.\n\n"
            f"{details}\n\n"
            "VLC가 없으면 MXF 영상 재생이 불가능하고, "
            "FFmpeg/FFplay가 없으면 오디오 믹스와 검출 기능이 제한됩니다. "
            "저장 위치 쓰기 권한이 없으면 설정, 로그, 분석 캐시가 제한됩니다."
        )
        if 'VLC' in runtime.get('missing', []):
            log.error('VLC runtime missing; abort startup before player construction')
            sys.exit(1)
    win = MainWindow()
    win.show()
    win.show_runtime_status(runtime)
    ret = app.exec()
    cleanup_child_processes()
    log.info('MXF QC Player 종료')
    sys.exit(ret)

if __name__ == "__main__":
    main()
