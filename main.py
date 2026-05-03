"""
main.py — 진입점
MainWindow + 전역 예외 처리 + 앱 실행
"""
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSplitter, QDialog, QPushButton
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QColor, QPalette

from constants    import C, STYLE, LOG_DIR, TMP_DIR, BASE_DIR, log
from video_panel  import VideoPanel
from right_panel  import RightPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Archive Tagger — MXF Player v2.0")
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
        tb = QWidget(); tb.setFixedHeight(36)
        tb.setStyleSheet(f"background:#161616;border-bottom:1px solid #0d0d0d;")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,0,8,0); tbl.setSpacing(6)
        for col in ['#FF5F57','#FFBD2E','#28C941']:
            d=QLabel('⬤'); d.setStyleSheet(f"color:{col};font-size:11px;"); tbl.addWidget(d)
        tbl.addSpacing(8)
        ttl = QLabel("ARCHIVE  TAGGER")
        ttl.setStyleSheet(f"color:{C['text2']};font-family:Consolas;font-size:16px;letter-spacing:1px;")
        ttl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tbl.addWidget(ttl,1)
        ver = QLabel("MXF  v2.0"); ver.setStyleSheet("color:#2e2e2e;font-family:Consolas;font-size:10px;letter-spacing:1px;")
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
        splitter.setSizes([980, 420])
        root.addWidget(splitter, 1)
        self._splitter = splitter

        def _keep_ratio(pos=None, idx=None):
            total = splitter.width() - splitter.handleWidth()
            splitter.setSizes([int(total * 0.7), int(total * 0.3)])
        self._keep_ratio = _keep_ratio
        splitter.splitterMoved.connect(_keep_ratio)

        # 상태 바
        self.vp.status_changed.connect(self.statusBar().showMessage)
        self.statusBar().showMessage("  ● READY   |   Archive Tagger v2.0   |   GPU: NVIDIA")

        self.vp.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.vp.setFocus()

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
            f"font-family:'맑은 고딕';font-size:13px;"
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
                "background:#2a2a2a;color:#cccccc;font-family:Consolas;"
                "font-size:12px;padding:2px 10px;border-radius:4px;"
                f"border:1px solid {C['border']};")
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rl.addWidget(act_lbl); rl.addStretch(); rl.addWidget(key_lbl)
            lay.addWidget(row)
        lay.addSpacing(16)
        close_btn = QPushButton('닫기')
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(
            "QPushButton{background:#222;color:#aaa;border:1px solid #333;"
            "border-radius:4px;font-size:12px;}"
            "QPushButton:hover{background:#2a2a2a;color:#eee;}"
        )
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)
        dlg.exec()

    def closeEvent(self, e):
        """창 닫을 때 모든 스레드/프로세스 안전 종료"""
        log.info('closeEvent — 종료 시작')
        try:
            vp = self.vp
            rp = self.rp

            # 트랜스코드 스레드
            vp._retire_tc()

            # dead_threads (abort된 스레드 보관)
            for t in getattr(vp, '_dead_threads', []):
                try: t.abort()
                except Exception as e: log.debug(f'dead_thread abort: {e}')

            # preconvert 스레드
            for t in getattr(vp, '_preconvert_threads', []):
                try: t.abort()
                except Exception as e: log.debug(f'preconvert abort: {e}')

            # 오디오 분석 스레드 — abort 플래그 → quit → wait
            if getattr(rp, '_audio_thread', None) and rp._audio_thread.isRunning():
                try:
                    if hasattr(rp._audio_thread, 'abort'):
                        rp._audio_thread.abort()
                    rp._audio_thread.quit()
                    if not rp._audio_thread.wait(3000):
                        log.warning('audio_thread 3초 내 미종료 — 강제 종료')
                        rp._audio_thread.terminate()
                    log.info('audio_thread 종료')
                except Exception as e: log.debug(f'audio_thread quit: {e}')

            # 블랙 검출 스레드 — FFmpeg 프로세스 포함 정리
            if getattr(rp, '_black_thread', None) and rp._black_thread.isRunning():
                try:
                    if hasattr(rp._black_thread, 'abort'):
                        rp._black_thread.abort()
                    rp._black_thread.quit()
                    if not rp._black_thread.wait(3000):
                        log.warning('black_thread 3초 내 미종료 — 강제 종료')
                        rp._black_thread.terminate()
                    log.info('black_thread 종료')
                except Exception as e: log.debug(f'black_thread quit: {e}')

            # 미터 스레드
            if hasattr(vp, 'meter_ctrl'):
                try: vp.meter_ctrl.set_playing(False)
                except Exception as e: log.debug(f'meter stop: {e}')

            # 플레이어 정지
            try:
                if hasattr(vp, 'audio_mix'):
                    vp.audio_mix.stop()
            except Exception as e: log.debug(f'audio_mix stop: {e}')
            try: vp.player.stop()
            except Exception as e: log.debug(f'player stop: {e}')

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
    log.info('=' * 50)
    log.info(f'Archive Tagger 시작 — Python {sys.version.split()[0]}')
    log.info(f'LOG_DIR: {LOG_DIR}')
    _cleanup_tmp_files()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
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
    win = MainWindow()
    win.show()
    ret = app.exec()
    log.info('Archive Tagger 종료')
    sys.exit(ret)

if __name__ == "__main__":
    main()
