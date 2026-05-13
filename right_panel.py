"""
right_panel.py — 오른쪽 탭 패널
RightPanel: 파일 탐색기, 블랙 검출, 오디오 분석
"""
import csv
import sys
import time
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMenu, QMessageBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QRect
from PyQt6.QtGui  import QColor, QFontMetrics
from PyQt6.QtMultimedia import QMediaPlayer

from constants   import (
    C, VIDEO_EXTS, BASE_DIR, REPORT_DIR, log, load_settings, save_settings,
    friendly_error_title, format_missing_runtime_tools, heavy_analysis_status,
    format_bytes, record_state_event,
)
from db_models   import probe, sec_to_tc, tc_to_frames
from threads     import AudioAnalyzeThread, BlackDetectThread
from meters      import mk_label

class RightPanel(QWidget):
    seek_requested = pyqtSignal(float)

    def __init__(self, video_panel):
        super().__init__()
        self.vp = video_panel
        self.cur_id = None
        self._analysis_active = None
        self._analysis_seq = 0
        self._analysis_seq_kind = None
        self._analysis_seq_file = None
        self._analysis_paused_playback = False
        self._analysis_paused_meters = False
        self._analysis_timeout_kind = None
        self._analysis_timeout_label = ''
        self._analysis_timeout_seq = None
        self._batch_active = False
        self._batch_queue = []
        self._batch_total = 0
        self._batch_current = None
        self._batch_current_info = {}
        self._batch_started_at = 0.0
        self._analysis_timeout_timer = QTimer(self)
        self._analysis_timeout_timer.setSingleShot(True)
        self._analysis_timeout_timer.timeout.connect(self._on_analysis_timeout)
        self._settings = load_settings()
        self._filter_key = str(self._settings.get('file_filter', 'all') or 'all')
        if self._filter_key not in ('all', 'done', 'issues'):
            self._filter_key = 'all'
        self._analysis_presets = {
            'broadcast': {
                'label': '방송 QC',
                'black_amount': '98',
                'black_threshold': '32',
                'mute_threshold': '-50',
                'mute_duration': '1.0',
            },
            'strict': {
                'label': '엄격',
                'black_amount': '99',
                'black_threshold': '24',
                'mute_threshold': '-55',
                'mute_duration': '1.0',
            },
            'fast': {
                'label': '빠른 검수',
                'black_amount': '95',
                'black_threshold': '40',
                'mute_threshold': '-45',
                'mute_duration': '0.7',
            },
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_explorer(),  "📁 파일")
        self.tabs.addTab(self._build_black(),      "⬛ 블랙")
        self.tabs.addTab(self._build_audio(),      "🔇 오디오")

        # 탭 색상 커스텀
        tab_colors = [C['blue'], C['yellow'], C['teal']]
        for i,col in enumerate(tab_colors):
            self.tabs.tabBar().setTabTextColor(i, QColor(C['text2']))

        self.seek_requested.connect(video_panel.seek_to)
        video_panel.file_loaded.connect(self._on_file_loaded)

    # ── EXPLORER ─────────────────────────────────────────
    def _build_explorer(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(0)

        # 툴바
        tb = QWidget(); tb.setFixedHeight(46)
        tb.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #141821,stop:1 #10131a);"
            f"border-bottom:1px solid {C['border']};"
        )
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(6,3,6,3); tbl.setSpacing(4)
        _exp_btn_style = (
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #222734,stop:1 #171b24);"
            f"color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:7px;font-size:11px;font-weight:700;padding:0 12px;height:30px;}}"
            f"QPushButton:hover{{background:#2a3142;color:{C['text0']};border-color:{C['blue']};}}"
        )
        self.btn_file = QPushButton("📄  파일 추가"); self.btn_file.setFixedHeight(32)
        self.btn_file.setToolTip("개별 영상 파일 추가")
        self.btn_file.setStyleSheet(_exp_btn_style)
        self.btn_file.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Space 버블링 차단
        self.btn_file.clicked.connect(self.vp.add_files)
        tbl.addWidget(self.btn_file)
        self.btn_recent = QPushButton("↺  최근"); self.btn_recent.setFixedHeight(32)
        self.btn_recent.setToolTip("최근 파일 / 최근 폴더")
        self.btn_recent.setStyleSheet(_exp_btn_style)
        self.btn_recent.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_recent.clicked.connect(self._show_recent_menu)
        tbl.addWidget(self.btn_recent)
        tbl.addStretch()

        # 파일 목록은 내부 기본 정렬만 유지하고, 상단은 실행 버튼 위주로 단순화
        self._sort_key = 'name'   # 'name' | 'added' | 'size'
        self._sort_asc = True
        _sort_btn_style = (
            "QPushButton{background:#0f131b;"
            f"color:{C['text2']};border:1px solid {C['border']};"
            f"border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;"
            f"padding:0 7px;height:24px;}}"
            f"QPushButton:checked{{background:rgba(90,167,255,30);color:{C['text0']};border-color:{C['blue']};}}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['blue']};}}"
        )
        self._sort_btns = {}

        self.btn_batch = QPushButton("일괄")
        self.btn_batch.setFixedHeight(24)
        self.btn_batch.setToolTip("파일 목록 전체를 블랙/뮤트 순서로 일괄 검수")
        self.btn_batch.setStyleSheet(_sort_btn_style)
        self.btn_batch.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_batch.setEnabled(False)
        self.btn_batch.clicked.connect(self._run_batch_qc)
        tbl.addWidget(self.btn_batch)

        self.btn_batch_cancel = QPushButton("취소")
        self.btn_batch_cancel.setFixedHeight(24)
        self.btn_batch_cancel.setToolTip("진행 중인 일괄 검수를 중단")
        self.btn_batch_cancel.setStyleSheet(
            _sort_btn_style.replace(f"color:{C['text2']};", f"color:{C['red']};")
        )
        self.btn_batch_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_batch_cancel.setEnabled(False)
        self.btn_batch_cancel.clicked.connect(self._cancel_batch_qc)
        tbl.addWidget(self.btn_batch_cancel)

        self.chk_auto_report = QCheckBox("자동저장")
        self.chk_auto_report.setToolTip("일괄 검수 완료 후 QC CSV 리포트를 reports 폴더에 자동 저장")
        self.chk_auto_report.setChecked(bool(self._settings.get('batch_auto_report', True)))
        self.chk_auto_report.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk_auto_report.setStyleSheet(
            f"QCheckBox{{color:{C['text2']};font-size:10px;font-weight:700;background:transparent;spacing:4px;}}"
            f"QCheckBox::indicator{{width:12px;height:12px;border:1px solid {C['border2']};border-radius:3px;background:#0f131b;}}"
            f"QCheckBox::indicator:checked{{background:{C['teal']};border-color:{C['teal']};}}"
        )
        self.chk_auto_report.stateChanged.connect(
            lambda _=None: self._save_file_tab_settings()
        )
        tbl.addWidget(self.chk_auto_report)

        l.addWidget(tb)

        # 경로 표시
        self.exp_path = mk_label('파일을 추가하세요', C['text3'], 'Consolas', 10)
        self.exp_path.setStyleSheet(
            f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #07090D,stop:1 #101722);padding:5px 12px;"
            f"border-bottom:1px solid {C['border']};")
        l.addWidget(self.exp_path)

        # 필터 표시
        filter_bar = QWidget()
        filter_bar.setFixedHeight(30)
        filter_bar.setStyleSheet(
            "background:#090D14;"
            f"border-bottom:1px solid {C['border']};"
        )
        fbl = QHBoxLayout(filter_bar)
        fbl.setContentsMargins(8,3,8,3)
        fbl.setSpacing(5)
        self._filter_btns = {}
        for key, label, tip in [
            ('all', '전체', '모든 파일 보기'),
            ('done', '완료', '블랙/뮤트 검수가 완료된 파일만 보기'),
            ('issues', '문제', '블랙/무음/검사 오류가 있는 파일만 보기'),
        ]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == self._filter_key)
            b.setFixedHeight(22)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(_sort_btn_style)
            b.clicked.connect(lambda checked=False, k=key: self._set_file_filter(k))
            self._filter_btns[key] = b
            fbl.addWidget(b)
        fbl.addStretch()
        l.addWidget(filter_bar)

        # 파일 목록
        self.exp_list = QListWidget()
        self.exp_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.exp_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.exp_list.setWordWrap(True)
        self.exp_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.exp_list.setUniformItemSizes(False)
        self.exp_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.exp_list.setStyleSheet(
            "QListWidget{background:#07090D;border:none;outline:none;}"
            f"QListWidget::item{{padding:9px 14px;border-bottom:1px solid #1D2635;"
            f"font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:12px;color:{C['text1']};}}"
            f"QListWidget::item:selected{{background:rgba(90,167,255,28);"
            f"border-left:2px solid {C['blue']};color:{C['text0']};}}"
            f"QListWidget::item:hover{{background:rgba(255,255,255,9);}}"
        )
        # 단일 클릭은 선택만, 더블클릭은 CUE
        self.exp_list.itemClicked.connect(self._on_exp_clicked)
        self.exp_list.itemDoubleClicked.connect(self._cue_exp_item)
        # Space 키 차단 (Player 전용)
        def _exp_key(evt):
            if evt.key() == Qt.Key.Key_Space:
                evt.ignore()   # Space 무시
                return
            QListWidget.keyPressEvent(self.exp_list, evt)
        self.exp_list.keyPressEvent = _exp_key
        def _exp_resize(evt):
            QListWidget.resizeEvent(self.exp_list, evt)
            QTimer.singleShot(0, self._update_file_item_size_hints)
        self.exp_list.resizeEvent = _exp_resize
        # 우클릭 컨텍스트 메뉴
        self.exp_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.exp_list.customContextMenuRequested.connect(self._exp_context_menu)
        l.addWidget(self.exp_list, 1)

        # 메타 패널
        self.meta_panel = QWidget()
        self.meta_panel.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #141821,stop:1 #10131a);"
            f"border-top:1px solid {C['border']};"
        )
        self.meta_panel.hide()
        ml = QGridLayout(self.meta_panel); ml.setContentsMargins(8,6,8,6); ml.setSpacing(3)
        self.meta_labels = {}
        for row,(k,key) in enumerate([("파일명","filename"),("포맷","format_short"),("코덱","codec"),
                                       ("해상도","res"),("FPS","fps"),("채널","channels"),
                                       ("길이","duration"),("타임코드","timecode"),("크기","size")]):
            kl=mk_label(k,C['text3'],"Consolas",11); kl.setFixedWidth(81)
            vl=mk_label("—",C['text0'],"Consolas",11)
            vl.setWordWrap(True)
            self.meta_labels[key]=vl
            ml.addWidget(kl,row//2,row%2*2); ml.addWidget(vl,row//2,row%2*2+1)
        l.addWidget(self.meta_panel)
        return w

    def _menu_style(self):
        return (
            f"QMenu{{background:#141821;color:{C['text1']};border:1px solid {C['border2']};"
            "font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:13px;padding:5px 0;border-radius:7px;}"
            "QMenu::item{padding:6px 20px;}"
            f"QMenu::item:selected{{background:rgba(90,167,255,35);color:{C['text0']};}}"
            f"QMenu::item:disabled{{color:{C['text3']};}}"
            f"QMenu::separator{{height:1px;background:{C['border']};margin:3px 0;}}"
        )

    def _save_file_tab_settings(self):
        try:
            self._settings = save_settings(
                file_filter=self._filter_key,
                batch_auto_report=bool(getattr(self, 'chk_auto_report', None) and self.chk_auto_report.isChecked()),
            )
            self.vp._settings = load_settings()
        except Exception as e:
            log.debug(f'file tab settings save: {e}')

    def _set_file_filter(self, key):
        if key not in ('all', 'done', 'issues'):
            key = 'all'
        self._filter_key = key
        for kk, btn in getattr(self, '_filter_btns', {}).items():
            btn.setChecked(kk == key)
        self._save_file_tab_settings()
        self.refresh_explorer()

    def _show_recent_menu(self):
        settings = load_settings()
        recent_files = []
        for fp in settings.get('recent_files', []):
            try:
                p = Path(fp)
                if p.exists() and p.suffix.lower() in VIDEO_EXTS and str(p) not in recent_files:
                    recent_files.append(str(p))
            except Exception:
                pass
        recent_dirs = []
        for folder in settings.get('recent_dirs', []):
            try:
                p = Path(folder)
                if p.exists() and p.is_dir() and str(p) not in recent_dirs:
                    recent_dirs.append(str(p))
            except Exception:
                pass
        if recent_files != settings.get('recent_files', []) or recent_dirs != settings.get('recent_dirs', []):
            self._settings = save_settings(recent_files=recent_files, recent_dirs=recent_dirs)
            self.vp._settings = load_settings()

        menu = QMenu(self)
        menu.setStyleSheet(self._menu_style())
        if recent_files:
            file_header = menu.addAction("최근 파일")
            file_header.setEnabled(False)
            for fp in recent_files[:8]:
                act = menu.addAction(f"  {Path(fp).name}")
                act.setToolTip(fp)
                act.setData(("file", fp))
        else:
            empty = menu.addAction("최근 파일 없음")
            empty.setEnabled(False)

        menu.addSeparator()
        if recent_dirs:
            dir_header = menu.addAction("최근 폴더")
            dir_header.setEnabled(False)
            for folder in recent_dirs[:6]:
                act = menu.addAction(f"  {Path(folder).name or folder}")
                act.setToolTip(folder)
                act.setData(("dir", folder))
        else:
            empty = menu.addAction("최근 폴더 없음")
            empty.setEnabled(False)

        menu.addSeparator()
        clear_act = menu.addAction("최근 목록 비우기")
        clear_act.setData(("clear", ""))
        sender = self.sender()
        popup_pos = sender.mapToGlobal(sender.rect().bottomLeft()) if sender else self.mapToGlobal(self.rect().topLeft())
        action = menu.exec(popup_pos)
        if not action:
            return
        data = action.data()
        if not data:
            return
        kind, value = data
        if kind == "file":
            self.vp.add_recent_file(value, cue=True)
        elif kind == "dir":
            self.vp.add_files(value)
        elif kind == "clear":
            self._settings = save_settings(recent_files=[], recent_dirs=[])
            self.vp._settings = load_settings()
            self.vp.status_changed.emit("  ↺ 최근 파일 / 폴더 목록을 비웠습니다")

    def _on_exp_clicked(self, item):
        fp = item.data(Qt.ItemDataRole.UserRole)
        if not fp:
            return
        self.vp.status_changed.emit(
            f"  📄 {Path(fp).name}  —  더블클릭하면 CUE 후 첫 프레임을 표시합니다")

    def _cue_exp_item(self, item):
        fp = item.data(Qt.ItemDataRole.UserRole)
        if fp:
            self.vp.load_file(fp)

    def _qc_status_text(self, value, kind):
        value = str(value or '').lower()
        if value == 'ok':
            return '정상'
        if value == 'found':
            return '있음'
        if value == 'error':
            return '오류'
        return '미분석'

    def _file_status_badge(self, f, is_cue=False):
        analysis = f.get("analysis")
        if analysis == "black":
            return "블랙 검사중", C['yellow']
        if analysis == "mute":
            return "뮤트 검사중", C['teal']
        if f.get("black") == "error" or f.get("mute") == "error":
            return "검사 오류", C['red']
        if f.get("black") == "found" and f.get("mute") == "found":
            return "블랙/무음", C['orange']
        if f.get("black") == "found":
            return "블랙 있음", C['yellow']
        if f.get("mute") == "found":
            return "무음 있음", C['teal']
        if f.get("black") == "ok" and f.get("mute") == "ok":
            return "정상", C['green']
        if f.get("playing"):
            return "재생중", C['green']
        if is_cue or f.get("cue"):
            return "CUE", C['blue']
        return "미분석", C['text2']

    def _file_status_detail(self, f):
        black_count = int(f.get("black_count", 0) or 0)
        mute_count = int(f.get("mute_count", 0) or 0)
        black = self._qc_status_text(f.get("black"), "black")
        mute = self._qc_status_text(f.get("mute"), "mute")
        return f"블랙 {black} {black_count} / 무음 {mute} {mute_count}"

    def _file_matches_filter(self, f):
        key = getattr(self, '_filter_key', 'all')
        if key == 'all':
            return True
        black = str(f.get('black') or '').lower()
        mute = str(f.get('mute') or '').lower()
        if key == 'done':
            return black in ('ok', 'found') and mute in ('ok', 'found')
        if key == 'issues':
            return black in ('found', 'error') or mute in ('found', 'error')
        return True

    def _filter_label(self):
        return {
            'all': '전체',
            'done': '완료',
            'issues': '문제',
        }.get(getattr(self, '_filter_key', 'all'), '전체')

    def _status_summary_text(self, files):
        counts = {
            "미분석": 0,
            "정상": 0,
            "블랙 있음": 0,
            "무음 있음": 0,
            "블랙/무음": 0,
            "검사 오류": 0,
            "검사중": 0,
        }
        for f in files:
            badge, _ = self._file_status_badge(f, f.get("filepath") == self.vp.cur_file)
            if "검사중" in badge:
                counts["검사중"] += 1
            elif badge in counts:
                counts[badge] += 1
            elif badge in ("CUE", "재생중"):
                counts["미분석"] += 1
        parts = [f"파일 {len(files)}"]
        for key in ("정상", "블랙 있음", "무음 있음", "블랙/무음", "검사 오류", "검사중", "미분석"):
            if counts.get(key):
                parts.append(f"{key} {counts[key]}")
        return " | ".join(parts)

    def _iter_report_files(self):
        files = list(getattr(self.vp, '_files', []) or [])
        sort_key = getattr(self, '_sort_key', 'name')
        sort_asc = getattr(self, '_sort_asc', True)
        if sort_key == 'name':
            files = sorted(files, key=lambda x: x.get('name', '').lower(), reverse=not sort_asc)
        elif sort_key == 'size':
            files = sorted(files, key=lambda x: x.get('size', 0), reverse=not sort_asc)
        elif sort_key == 'added' and not sort_asc:
            files = list(reversed(files))
        return files

    def _qc_report_rows(self):
        rows = []
        for f in self._iter_report_files():
            fp = f.get('filepath', '')
            p = Path(fp)
            badge, _ = self._file_status_badge(f, fp == self.vp.cur_file)
            size = int(f.get('size', 0) or 0)
            if not size:
                try:
                    size = p.stat().st_size
                except Exception:
                    size = 0
            info = {}
            try:
                if Path(fp).exists():
                    info = probe(fp) or {}
            except Exception as e:
                log.debug(f'qc report probe skipped file={p.name}: {e}')
            fps = float(info.get('fps', 0) or 0)
            duration = float(info.get('duration', 0) or 0)
            width = int(info.get('width', 0) or 0)
            height = int(info.get('height', 0) or 0)
            rows.append({
                '검수시각': datetime.now().isoformat(timespec='seconds'),
                'QC상태': badge,
                '파일명': f.get('name') or p.name,
                '경로': fp,
                '확장자': f.get('ext') or p.suffix.upper().lstrip('.'),
                '포맷': info.get('format_short', ''),
                '코덱': info.get('codec', ''),
                '해상도': f'{width}x{height}' if width and height else '',
                'FPS': f'{fps:.3f}' if fps else '',
                'DF': 'Y' if info.get('df') else 'N',
                '길이_TC': sec_to_tc(duration, fps or 29.97, info.get('df')) if duration else '',
                '길이_sec': f'{duration:.3f}' if duration else '',
                '오디오채널': str(int(info.get('channels', 0) or 0)),
                '오디오스트림': str(int(info.get('audio_stream_count', 0) or 0)),
                '소스타임코드': info.get('timecode', '') or '',
                '비트레이트': str(info.get('bit_rate', '') or ''),
                '크기': format_bytes(size) if size else '-',
                '크기_bytes': str(size or ''),
                '블랙상태': self._qc_status_text(f.get('black'), 'black'),
                '블랙구간': str(int(f.get('black_count', 0) or 0)),
                '무음상태': self._qc_status_text(f.get('mute'), 'mute'),
                '무음구간': str(int(f.get('mute_count', 0) or 0)),
                'QC요약': f.get('qc_summary') or badge,
                '갱신시각': str(f.get('qc_updated_at') or ''),
            })
        return rows

    def _write_qc_report_txt(self, path, rows):
        lines = []
        lines.append('MXF QC Player V.1.0 - QC 결과 리포트')
        lines.append('=' * 64)
        lines.append(f'생성시각: {datetime.now().isoformat(timespec="seconds")}')
        lines.append(f'파일수  : {len(rows)}')
        lines.append('')
        for idx, row in enumerate(rows, 1):
            lines.append(f"{idx:03d}. {row['파일명']}")
            lines.append(f"     상태: {row['QC상태']} / {row['QC요약']}")
            lines.append(f"     미디어: {row.get('해상도') or '-'} / {row.get('FPS') or '-'}fps / {row.get('오디오채널') or '-'}CH / {row.get('길이_TC') or '-'}")
            if row.get('소스타임코드'):
                lines.append(f"     소스TC: {row['소스타임코드']}")
            lines.append(f"     블랙: {row['블랙상태']} {row['블랙구간']}구간")
            lines.append(f"     무음: {row['무음상태']} {row['무음구간']}구간")
            lines.append(f"     크기: {row['크기']}")
            lines.append(f"     갱신: {row['갱신시각'] or '-'}")
            lines.append(f"     경로: {row['경로']}")
            lines.append('')
        Path(path).write_text('\n'.join(lines), encoding='utf-8')

    def _write_qc_report_csv(self, path, rows):
        with Path(path).open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _auto_save_qc_report(self, prefix='batch-qc'):
        rows = self._qc_report_rows()
        if not rows:
            return None
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORT_DIR / f"{prefix}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self._write_qc_report_csv(out, rows)
        log.info(f'qc report auto-exported: {out}')
        record_state_event('qc-report', 'auto exported', path=str(out), files=len(rows))
        return out

    def _export_qc_report(self):
        rows = self._qc_report_rows()
        if not rows:
            QMessageBox.information(self, 'QC 리포트', '파일 목록에 리포트로 저장할 MXF가 없습니다.')
            return
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        default = REPORT_DIR / f"qc-report-{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, selected = QFileDialog.getSaveFileName(
            self,
            'QC 결과 리포트 저장',
            str(default),
            'CSV 파일 (*.csv);;텍스트 파일 (*.txt)'
        )
        if not path:
            return
        try:
            out = Path(path)
            if selected.startswith('텍스트') or out.suffix.lower() == '.txt':
                if out.suffix.lower() != '.txt':
                    out = out.with_suffix('.txt')
                self._write_qc_report_txt(out, rows)
            else:
                if out.suffix.lower() != '.csv':
                    out = out.with_suffix('.csv')
                self._write_qc_report_csv(out, rows)
            log.info(f'qc report exported: {out}')
            record_state_event('qc-report', 'exported', path=str(out), files=len(rows))
            QMessageBox.information(self, 'QC 리포트 저장 완료', f'QC 리포트를 저장했습니다.\n\n{out}')
        except Exception as e:
            log.error(f'qc report export failed: {e}')
            QMessageBox.warning(self, 'QC 리포트 저장 실패', str(e))

    def _exp_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        item = self.exp_list.itemAt(pos)
        if not item: return
        fp = item.data(Qt.ItemDataRole.UserRole)
        if not fp: return
        menu = QMenu(self.exp_list)
        menu.setStyleSheet(self._menu_style())
        act_cue = menu.addAction("▶   CUE  —  화면에 올리기")
        menu.addSeparator()
        act_del = menu.addAction("✕   목록에서 제거")
        action = menu.exec(self.exp_list.mapToGlobal(pos))
        if action is None:
            return
        elif action == act_cue:
            self.vp.load_file(fp)
        elif action == act_del:
            self.vp._files = [f for f in self.vp._files if f["filepath"] != fp]
            if self.vp.cur_file == fp:
                self.vp.eject_clip()
            self.vp._refresh_clip_list()
            self._update_explorer(self.vp.cur_info, self.vp.cur_id or "")

    def _file_item_height(self, text):
        width = max(170, self.exp_list.viewport().width() - 34)
        flags = (
            Qt.TextFlag.TextWordWrap.value
            | Qt.TextFlag.TextWrapAnywhere.value
            | Qt.AlignmentFlag.AlignLeft.value
        )
        rect = QFontMetrics(self.exp_list.font()).boundingRect(
            QRect(0, 0, width, 2000), flags, text
        )
        return max(52, min(176, rect.height() + 30))

    def _update_file_item_size_hints(self):
        if not hasattr(self, 'exp_list'):
            return
        for i in range(self.exp_list.count()):
            item = self.exp_list.item(i)
            item.setSizeHint(QSize(0, self._file_item_height(item.text())))

    def refresh_explorer(self):
        # info 없어도 파일 목록만 갱신 (파일 추가/제거 시 호출)
        self.exp_list.clear()
        all_files = list(self.vp._files)
        files = [f for f in all_files if self._file_matches_filter(f)]
        cue_fp = self.vp.cur_file
        can_use_files = bool(all_files) and not bool(getattr(self.vp, '_loading', False)) and not bool(getattr(self, '_analysis_active', None))
        if hasattr(self, 'btn_batch'):
            self.btn_batch.setEnabled(can_use_files)
        if hasattr(self, 'btn_export'):
            self.btn_export.setEnabled(bool(all_files) and not bool(getattr(self, '_analysis_active', None)))
        if hasattr(self, 'btn_batch_cancel'):
            self.btn_batch_cancel.setEnabled(bool(getattr(self, '_batch_active', False)))
        for key, btn in getattr(self, '_filter_btns', {}).items():
            btn.setChecked(key == getattr(self, '_filter_key', 'all'))

        # 경로 표시: CUE 파일 기준, 없으면 첫 번째 파일 기준
        base_fp = cue_fp or (all_files[0]["filepath"] if all_files else "")
        summary = self._status_summary_text(all_files)
        if base_fp:
            self.exp_path.setText(
                f"📁 {Path(base_fp).parent}    QC {summary}    표시 {len(files)}/{len(all_files)} ({self._filter_label()})"
            )
        else:
            self.exp_path.setText("파일을 추가하세요")

        # 정렬 적용
        sort_key = getattr(self, '_sort_key', 'name')
        sort_asc = getattr(self, '_sort_asc', True)
        if sort_key == 'name':
            files = sorted(files, key=lambda x: x['name'].lower(), reverse=not sort_asc)
        elif sort_key == 'size':
            files = sorted(files, key=lambda x: x.get('size', 0), reverse=not sort_asc)
        # 'added' 는 원래 순서 유지 (reverse만 적용)
        elif sort_key == 'added':
            files = files if sort_asc else list(reversed(files))

        for f in files:
            is_cue = (f["filepath"] == cue_fp)
            prefix = "▶  " if is_cue else ""
            badge, badge_color = self._file_status_badge(f, is_cue)
            detail = self._file_status_detail(f)
            item_text = f"{prefix}{f['name']}\nQC: {badge}    {detail}"
            item = QListWidgetItem(item_text)
            item.setSizeHint(QSize(0, self._file_item_height(item_text)))
            item.setData(Qt.ItemDataRole.UserRole, f["filepath"])
            updated = f.get("qc_updated_at") or "-"
            item.setToolTip(
                f"{Path(f['filepath']).name}\n"
                f"QC 상태: {badge}\n{detail}\n갱신: {updated}\n{f['filepath']}"
            )
            if is_cue and badge not in ("블랙 있음", "무음 있음", "블랙/무음", "검사 오류"):
                item.setForeground(QColor(badge_color))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setForeground(QColor(badge_color if badge != "미분석" else C['text1']))
            self.exp_list.addItem(item)
            if is_cue:
                self.exp_list.setCurrentItem(item)
        self._update_file_item_size_hints()

    def _update_explorer(self, info, clip_id):
        # 파일 목록 갱신
        self.refresh_explorer()
        # 메타 패널: CUE된 파일 정보 표시
        if not info:
            self.meta_panel.hide()
            return
        self.meta_panel.show()
        self.meta_labels["filename"].setText(info.get("filename","—"))
        self.meta_labels["format_short"].setText(info.get("format_short","—"))
        self.meta_labels["codec"].setText(info.get("codec","—"))
        w=info.get("width",0); h=info.get("height",0)
        self.meta_labels["res"].setText(f"{w}×{h}" if w else "—")
        self.meta_labels["fps"].setText(f"{info.get('fps',0):.3f}")
        self.meta_labels["channels"].setText(f"{info.get('channels',0)}CH")
        self.meta_labels["duration"].setText(
            sec_to_tc(info.get("duration",0), info.get("fps",29.97), info.get("df"))
        )
        self.meta_labels["timecode"].setText(info.get("timecode","—") or "—")
        sz = info.get("size",0)
        self.meta_labels["size"].setText(f"{sz/1024/1024:.1f} MB" if sz else "—")

    def _build_black(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(0)

        tb = QWidget(); tb.setFixedHeight(46)
        tb.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,4,8,4); tbl.setSpacing(6)

        _inp = (f"background:{C['input']};border:1px solid {C['border']};border-radius:5px;"
                f"color:{C['yellow']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:12px;padding:2px 6px;")

        lbl_amt = QLabel("검정%")
        lbl_amt.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        self.black_amount = QLineEdit(str(self._settings.get('black_amount', '98')))
        self.black_amount.setFixedWidth(42); self.black_amount.setFixedHeight(26)
        self.black_amount.setStyleSheet(_inp)
        self.black_amount.setToolTip("화면 중 검정으로 판단할 최소 비율. 기본 98%")

        lbl_thr = QLabel("밝기")
        lbl_thr.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        self.black_threshold = QLineEdit(str(self._settings.get('black_threshold', '32')))
        self.black_threshold.setFixedWidth(42); self.black_threshold.setFixedHeight(26)
        self.black_threshold.setStyleSheet(_inp)
        self.black_threshold.setToolTip("검정 픽셀 밝기 기준. 낮을수록 엄격합니다. 기본 32")

        self.black_preset = QComboBox()
        self.black_preset.setFixedHeight(26)
        self.black_preset.setToolTip("블랙/뮤트 분석 기준 프리셋")
        for key, data in self._analysis_presets.items():
            self.black_preset.addItem(data['label'], key)
        self.black_preset.setStyleSheet(self._preset_combo_style())
        self.black_preset.currentIndexChanged.connect(
            lambda _: self._apply_analysis_preset(self.black_preset.currentData())
        )

        self.btn_run_black = QPushButton("⬛  블랙 검출")
        self.btn_run_black.setFixedHeight(30); self.btn_run_black.setEnabled(False)
        self.btn_run_black.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_run_black.setStyleSheet(
            f"QPushButton{{background:rgba(255,209,102,30);color:{C['yellow']};"
            f"border:1px solid rgba(255,209,102,95);border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{background:rgba(255,209,102,45);border-color:{C['yellow']};}}"
            f"QPushButton:disabled{{background:#101218;color:#4a4020;border-color:#242010;}}"
        )
        self.btn_run_black.clicked.connect(self._run_black_detect)
        self.black_amount.editingFinished.connect(self._save_detection_settings)
        self.black_threshold.editingFinished.connect(self._save_detection_settings)

        lbl_pre = QLabel("프리셋")
        lbl_pre.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        tbl.addWidget(lbl_pre); tbl.addWidget(self.black_preset)
        tbl.addSpacing(6)
        tbl.addWidget(lbl_amt); tbl.addWidget(self.black_amount)
        tbl.addSpacing(6)
        tbl.addWidget(lbl_thr); tbl.addWidget(self.black_threshold)
        tbl.addStretch(); tbl.addWidget(self.btn_run_black)
        l.addWidget(tb)

        self.black_status = QLabel("  파일을 로드하고 블랙 검출 버튼을 누르세요")
        self.black_status.setStyleSheet(
            f"color:{C['text2']};font-size:11px;background:{C['panel2']};"
            f"padding:5px 12px;border-bottom:1px solid {C['border']};")
        l.addWidget(self.black_status)

        hdr = QLabel("  블랙 구간 — 클릭하면 해당 프레임으로 이동")
        hdr.setStyleSheet(
            f"color:{C['text2']};font-size:11px;font-weight:600;"
            f"background:{C['panel']};padding:4px 12px;border-bottom:1px solid {C['border']};")
        l.addWidget(hdr)

        self.black_list = QListWidget()
        self.black_list.setStyleSheet(
            f"QListWidget{{background:{C['panel2']};color:{C['text1']};}}"
            f"QListWidget::item{{padding:8px 14px;border-bottom:1px solid {C['border']};"
            f"font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;}}"
            f"QListWidget::item:selected{{background:rgba(255,209,102,28);"
            f"border-left:2px solid {C['yellow']};}}"
            f"QListWidget::item:hover{{background:rgba(255,255,255,7);}}")
        self.black_list.itemClicked.connect(
            lambda i: self.seek_requested.emit(i.data(Qt.ItemDataRole.UserRole) or 0))
        l.addWidget(self.black_list, 1)
        return w

    def _reset_black_tab(self):
        try:
            self.btn_run_black.setEnabled(bool(self.vp.cur_file))
            self.black_status.setText("  1프레임 이상 / 화면 98% 이상 검정 기준")
            self.black_list.clear()
        except Exception as e: log.warning(f'black tab reset: {e}')

    def _save_detection_settings(self):
        try:
            self._settings = save_settings(
                black_amount=self.black_amount.text().strip() or '98',
                black_threshold=self.black_threshold.text().strip() or '32',
                mute_threshold=self.spin_threshold.text().strip() or '-50',
                mute_duration=self.spin_duration.text().strip() or '1.0',
            )
        except Exception as e:
            log.debug(f'detection settings save: {e}')

    def _preset_combo_style(self):
        return (
            f"QComboBox{{background:{C['input']};color:{C['text1']};border:1px solid {C['border']};"
            "border-radius:5px;font-size:11px;padding:0 8px;min-width:82px;}}"
            f"QComboBox:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            f"QComboBox QAbstractItemView{{background:{C['panel']};color:{C['text1']};"
            f"selection-background-color:rgba(90,167,255,35);border:1px solid {C['border2']};}}"
        )

    def _apply_analysis_preset(self, key):
        preset = self._analysis_presets.get(key)
        if not preset:
            return
        try:
            if hasattr(self, 'black_amount'):
                self.black_amount.setText(preset['black_amount'])
            if hasattr(self, 'black_threshold'):
                self.black_threshold.setText(preset['black_threshold'])
            if hasattr(self, 'spin_threshold'):
                self.spin_threshold.setText(preset['mute_threshold'])
            if hasattr(self, 'spin_duration'):
                self.spin_duration.setText(preset['mute_duration'])
            if hasattr(self, 'black_preset') and self.black_preset.currentData() != key:
                idx = self.black_preset.findData(key)
                if idx >= 0:
                    self.black_preset.setCurrentIndex(idx)
            if hasattr(self, 'audio_preset') and self.audio_preset.currentData() != key:
                idx = self.audio_preset.findData(key)
                if idx >= 0:
                    self.audio_preset.setCurrentIndex(idx)
            self._save_detection_settings()
            label = preset.get('label', key)
            if hasattr(self, 'black_status'):
                self.black_status.setText(f"  ✓ 프리셋 적용 — {label}")
            if hasattr(self, 'audio_status'):
                self.audio_status.setText(f"  ✓ 프리셋 적용 — {label}")
        except Exception as e:
            log.debug(f'analysis preset apply: {e}')

    def _analysis_thread_running(self):
        if getattr(self, '_batch_active', False):
            return True
        for name in ('_black_thread', '_audio_thread'):
            thread = getattr(self, name, None)
            try:
                if thread and thread.isRunning():
                    return True
            except Exception:
                pass
        return False

    def _analysis_timeout_seconds(self, duration=None):
        try:
            if duration is None:
                duration = float(getattr(self.vp, 'duration', 0) or self.vp.cur_info.get('duration', 0) or 0)
            else:
                duration = float(duration or 0)
        except Exception:
            duration = 0
        return int(max(120, min(3600, duration * 4 + 60)))

    def _next_analysis_seq(self, kind, filepath):
        self._analysis_seq += 1
        self._analysis_seq_kind = kind
        self._analysis_seq_file = filepath
        return self._analysis_seq

    def _analysis_matches(self, kind, seq, filepath=None):
        if seq is None:
            return True
        if seq != self._analysis_seq or kind != self._analysis_seq_kind:
            return False
        if filepath and filepath != self._analysis_seq_file:
            return False
        return True

    def _log_stale_analysis(self, kind, seq, where):
        log.debug(
            f'stale analysis callback ignored kind={kind} seq={seq} '
            f'current={self._analysis_seq}/{self._analysis_seq_kind} where={where}'
        )

    def _start_analysis_timeout(self, kind, label, seq, seconds=None):
        seconds = self._analysis_timeout_seconds() if seconds is None else int(seconds)
        self._analysis_timeout_kind = kind
        self._analysis_timeout_label = label
        self._analysis_timeout_seq = seq
        self._analysis_timeout_timer.start(seconds * 1000)
        log.info(f'analysis timeout armed kind={kind} seq={seq} seconds={seconds}')

    def _stop_analysis_timeout(self):
        self._analysis_timeout_timer.stop()
        self._analysis_timeout_kind = None
        self._analysis_timeout_label = ''
        self._analysis_timeout_seq = None

    def _on_analysis_timeout(self):
        kind = self._analysis_timeout_kind
        seq = self._analysis_timeout_seq
        label = self._analysis_timeout_label or '분석'
        self._analysis_timeout_kind = None
        self._analysis_timeout_label = ''
        self._analysis_timeout_seq = None
        if not self._analysis_matches(kind, seq):
            self._log_stale_analysis(kind, seq, 'timeout')
            return
        msg = f'{label} 시간 초과 — FFmpeg 작업을 중단했습니다'
        log.warning(f'analysis timeout fired kind={kind} seq={seq}')
        if kind == 'black':
            thread = getattr(self, '_black_thread', None)
            try:
                if thread and thread.isRunning():
                    thread.abort()
            except Exception as e:
                log.debug(f'black timeout abort: {e}')
            if getattr(self, '_batch_active', False):
                self._on_batch_black_error(msg, seq=seq)
                return
            self._on_black_error(msg, seq=seq)
        elif kind == 'audio':
            thread = getattr(self, '_audio_thread', None)
            try:
                if thread and thread.isRunning():
                    thread.abort()
            except Exception as e:
                log.debug(f'audio timeout abort: {e}')
            if getattr(self, '_batch_active', False):
                self._on_batch_audio_error(msg, seq=seq)
                return
            self._on_audio_error(msg, seq=seq)

    def cancel_active_analysis(self, reason='작업 취소', wait_ms=700):
        """Abort running analysis threads and invalidate their queued UI callbacks."""
        had_work = False
        active_kind = getattr(self, '_analysis_active', None)
        self._analysis_seq += 1
        self._analysis_seq_kind = None
        self._analysis_seq_file = None
        self._stop_analysis_timeout()

        for attr, label in (('_black_thread', '블랙 검출'), ('_audio_thread', '뮤트 검출')):
            thread = getattr(self, attr, None)
            if not thread:
                continue
            try:
                running = thread.isRunning()
            except Exception:
                running = False
            if running:
                had_work = True
                try:
                    thread.abort()
                except Exception as e:
                    log.debug(f'{label} cancel abort: {e}')
                finished = False
                try:
                    finished = bool(thread.wait(int(wait_ms)))
                except Exception as e:
                    log.debug(f'{label} cancel wait: {e}')
                if not finished:
                    log.warning(f'{label} cancel wait timeout — force terminating thread')
                    try:
                        thread.terminate()
                        thread.wait(800)
                    except Exception as e:
                        log.debug(f'{label} force terminate: {e}')
            try:
                if not thread.isRunning():
                    setattr(self, attr, None)
                else:
                    log.warning(f'{label} thread still running after cancel')
            except Exception:
                setattr(self, attr, None)

        if active_kind == 'black' or had_work:
            try:
                self.black_status.setText(f"  ⏹ {reason} — 블랙 검출 중단")
            except Exception:
                pass
        if active_kind == 'audio' or had_work:
            try:
                self.audio_status.setText(f"  ⏹ {reason} — 뮤트 검출 중단")
            except Exception:
                pass
        if had_work:
            try:
                self.vp.ai_lbl.setText(f"⏹ {reason} — 분석 작업 중단")
            except Exception:
                pass
            log.info(f'analysis cancelled: {reason}')
        if getattr(self, '_batch_active', False):
            self._batch_active = False
            self._batch_queue = []
            self._batch_current = None
            self._batch_current_info = {}
            try:
                self.exp_path.setText(f"⏹ {reason} — 일괄 검수 중단")
            except Exception:
                pass
            if hasattr(self, 'btn_batch_cancel'):
                self.btn_batch_cancel.setEnabled(False)
            log.info(f'batch qc cancelled: {reason}')
        self._finish_analysis_mode()
        return had_work

    def set_loading_state(self, loading):
        enabled = not bool(loading)
        for name in ('btn_file', 'btn_recent', 'btn_batch', 'btn_export'):
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled)
        for btn in getattr(self, '_sort_btns', {}).values():
            btn.setEnabled(enabled)
        if hasattr(self, 'exp_list'):
            self.exp_list.setEnabled(enabled)
        if getattr(self, '_analysis_active', None):
            return
        has_file = bool(getattr(self.vp, 'cur_file', None))
        if hasattr(self, 'btn_run_black'):
            self.btn_run_black.setEnabled(enabled and has_file)
        if hasattr(self, 'btn_run_audio'):
            self.btn_run_audio.setEnabled(enabled and has_file)

    def _set_analysis_buttons_busy(self, kind=None, busy=False):
        has_file = bool(getattr(self.vp, 'cur_file', None))
        loading = bool(getattr(self.vp, '_loading', False))
        black = getattr(self, 'btn_run_black', None)
        audio = getattr(self, 'btn_run_audio', None)
        batch = getattr(self, 'btn_batch', None)
        export = getattr(self, 'btn_export', None)
        if black:
            black.setText("⬛  분석 중..." if busy and kind == 'black' else "⬛  블랙 검출")
            black.setEnabled(False if busy else (has_file and not loading))
        if audio:
            audio.setText("🔇  분석 중..." if busy and kind == 'audio' else "🔇  뮤트 검출")
            audio.setEnabled(False if busy else (has_file and not loading))
        if batch:
            batch.setText("진행중" if busy and kind == 'batch' else "일괄")
            batch.setEnabled(False if busy else (bool(getattr(self.vp, '_files', [])) and not loading))
        cancel = getattr(self, 'btn_batch_cancel', None)
        if cancel:
            cancel.setEnabled(bool(busy and kind == 'batch'))
        if export:
            export.setEnabled(False if busy else bool(getattr(self.vp, '_files', [])))

    def _set_transport_enabled(self, enabled):
        for name in (
            'btn_folder', 'btn_m1', 'btn_gos', 'btn_rew', 'btn_play',
            'btn_stop', 'btn_fwd', 'btn_goe', 'btn_p1', 'btn_cue',
        ):
            btn = getattr(self.vp, name, None)
            if btn:
                try:
                    btn.setEnabled(enabled)
                except Exception:
                    pass

    def _begin_analysis_mode(self, kind, label):
        if self._analysis_thread_running():
            return False
        try:
            if hasattr(self.vp, '_retire_loudness_analysis'):
                self.vp._retire_loudness_analysis()
        except Exception as e:
            log.debug(f'analysis mode retire loudness: {e}')
        heavy = heavy_analysis_status()
        if heavy.get('running'):
            owner = heavy.get('owner') or '분석'
            elapsed = float(heavy.get('elapsed') or 0.0)
            if hasattr(self.vp, 'status_changed'):
                self.vp.status_changed.emit(f"  ⏳ {owner} 정리 중 — {elapsed:.1f}s")
            return False
        self._analysis_active = kind
        self._analysis_paused_playback = False
        self._analysis_paused_meters = False
        try:
            if self.vp.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._analysis_paused_playback = True
                self.vp.player.pause()
            if hasattr(self.vp, '_cancel_audio_mix'):
                self.vp._cancel_audio_mix()
            if hasattr(self.vp, 'meter_ctrl'):
                self.vp.meter_ctrl.set_playing(False)
                self._analysis_paused_meters = True
            self._set_transport_enabled(False)
            self._set_analysis_buttons_busy(kind, True)
            if hasattr(self.vp, 'status_changed'):
                self.vp.status_changed.emit(f"  ⏸ {label} 중 — 재생/오디오 미터 일시정지")
        except Exception as e:
            log.debug(f'analysis mode begin: {e}')
        return True

    def _finish_analysis_mode(self):
        self._set_transport_enabled(True)
        self._set_analysis_buttons_busy(None, False)
        if self.vp.cur_file:
            try:
                self.btn_run_black.setEnabled(True)
                self.btn_run_audio.setEnabled(True)
                self.vp.btn_black.setEnabled(True)
                self.vp.btn_audio.setEnabled(True)
            except Exception as e:
                log.debug(f'analysis buttons restore: {e}')
        try:
            if self._analysis_paused_meters and self.vp.cur_file:
                ch_count = self.vp.cur_info.get('channels', 2)
                self.vp.meter_ctrl.start_file(
                    self.vp.cur_file, ch_count, self.vp.player, (1, 2),
                    self.vp.cur_info.get('audio_stream_count', 0))
            if self._analysis_paused_playback and hasattr(self.vp, 'status_changed'):
                self.vp.status_changed.emit("  ⏸ 분석 완료 — 재생 버튼을 눌러 이어서 확인하세요")
        except Exception as e:
            log.debug(f'analysis mode finish: {e}')
        finally:
            self._analysis_active = None
            self._analysis_paused_playback = False
            self._analysis_paused_meters = False
            if hasattr(self, 'btn_batch_cancel'):
                self.btn_batch_cancel.setEnabled(False)

    def _cancel_batch_qc(self):
        if not getattr(self, '_batch_active', False):
            return
        self.cancel_active_analysis('일괄 검수 취소')
        self.refresh_explorer()
        try:
            self.vp.ai_lbl.setText('⏹ 일괄 검수 취소됨')
        except Exception:
            pass

    def _parse_detection_values(self):
        amount = int(float(self.black_amount.text()))
        threshold = int(float(self.black_threshold.text()))
        amount = max(1, min(100, amount))
        threshold = max(0, min(255, threshold))
        thr = float(self.spin_threshold.text())
        dur = float(self.spin_duration.text())
        self.black_amount.setText(str(amount))
        self.black_threshold.setText(str(threshold))
        self.spin_threshold.setText(f'{thr:g}')
        self.spin_duration.setText(f'{dur:g}')
        self._save_detection_settings()
        return amount, threshold, thr, dur

    def _batch_timeout_seconds(self):
        duration = 0.0
        try:
            duration = float((self._batch_current_info or {}).get('duration', 0) or 0)
        except Exception:
            duration = 0.0
        return self._analysis_timeout_seconds(duration)

    def _batch_tc_offset_frames(self, info):
        try:
            return tc_to_frames(info.get('timecode', ''), info.get('fps', 29.97), info.get('df'))
        except Exception:
            try:
                return int(round(float(info.get('tc_offset', 0.0) or 0.0) * float(info.get('fps', 29.97) or 29.97)))
            except Exception:
                return 0

    def _run_batch_qc(self):
        files = [f for f in getattr(self.vp, '_files', []) if f.get('filepath')]
        if not files:
            QMessageBox.information(self, '일괄 검수', '파일 목록에 검수할 MXF가 없습니다.')
            return
        missing = format_missing_runtime_tools(['FFmpeg', 'FFprobe'])
        if missing:
            title = missing.splitlines()[0]
            self.exp_path.setText(f"⚠ {title}")
            self.vp.ai_lbl.setText(f"⚠ {title}")
            log.warning(f'batch qc blocked: {missing}')
            return
        if self._analysis_thread_running():
            self.exp_path.setText("⏳ 다른 분석 작업이 진행 중입니다")
            return
        try:
            self._batch_amount, self._batch_threshold, self._batch_mute_thr, self._batch_mute_dur = self._parse_detection_values()
        except ValueError:
            QMessageBox.warning(self, '일괄 검수', '블랙/뮤트 분석 기준 값을 숫자로 입력하세요.')
            return
        if not self._begin_analysis_mode('batch', '일괄 검수'):
            self.exp_path.setText("⏳ 다른 분석 작업이 진행 중입니다")
            return

        self._batch_active = True
        self._batch_queue = [f.get('filepath') for f in files]
        self._batch_total = len(self._batch_queue)
        self._batch_current = None
        self._batch_current_info = {}
        self._batch_started_at = time.monotonic()
        self.tabs.setCurrentIndex(0)
        log.info(f'batch qc started files={self._batch_total}')
        record_state_event('batch-qc', 'started', files=self._batch_total)
        self._start_next_batch_file()

    def _start_next_batch_file(self):
        if not getattr(self, '_batch_active', False):
            return
        if not self._batch_queue:
            self._finish_batch_qc()
            return
        fp = self._batch_queue.pop(0)
        self._batch_current = fp
        idx = self._batch_total - len(self._batch_queue)
        file_name = Path(fp).name
        if not Path(fp).exists():
            if hasattr(self.vp, '_set_file_status'):
                self.vp._set_file_status(fp, analysis=None, black='error', black_count=0, mute='error', mute_count=0)
            log.warning(f'batch qc skipped missing file: {fp}')
            QTimer.singleShot(50, self._start_next_batch_file)
            return
        try:
            self._batch_current_info = probe(fp) or {}
        except Exception as e:
            self._batch_current_info = {}
            log.warning(f'batch qc probe failed file={file_name}: {e}')
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis='black')
        self.exp_path.setText(f"⏳ 일괄 검수 {idx}/{self._batch_total} — 블랙: {file_name}")
        self.vp.ai_lbl.setText(f"⬛ 일괄 검수 {idx}/{self._batch_total} — {file_name}")
        fps = self._batch_current_info.get('fps', 29.97)
        df = self._batch_current_info.get('df', None)
        offset = self._batch_tc_offset_frames(self._batch_current_info)
        seq = self._next_analysis_seq('black', fp)
        self._black_thread = BlackDetectThread(fp, fps, self._batch_amount, self._batch_threshold, df, offset)
        self._black_thread.progress.connect(lambda m, s=seq: self._on_batch_progress('black', s, m))
        self._black_thread.finished.connect(lambda ranges, s=seq: self._on_batch_black_done(ranges, seq=s))
        self._black_thread.error.connect(lambda err, s=seq: self._on_batch_black_error(err, seq=s))
        self._black_thread.start()
        self._start_analysis_timeout('black', '일괄 블랙 검출', seq, seconds=self._batch_timeout_seconds())

    def _on_batch_progress(self, kind, seq, message):
        if not getattr(self, '_batch_active', False):
            return
        if not self._analysis_matches(kind, seq, self._batch_current):
            return
        idx = self._batch_total - len(self._batch_queue)
        file_name = Path(self._batch_current or '').name
        label = '블랙' if kind == 'black' else '뮤트'
        self.exp_path.setText(f"⏳ 일괄 검수 {idx}/{self._batch_total} — {label}: {file_name}")
        if kind == 'black':
            self.black_status.setText(f"  ⏳ {message}")
        else:
            self.audio_status.setText(f"  ⏳ {message}")

    def _on_batch_black_done(self, ranges, seq=None):
        if not getattr(self, '_batch_active', False):
            return
        fp = self._batch_current
        if not self._analysis_matches('black', seq, fp):
            self._log_stale_analysis('black', seq, 'batch black done')
            return
        self._stop_analysis_timeout()
        if getattr(self, '_black_thread', None) and not self._black_thread.isRunning():
            self._black_thread = None
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis='mute', black='found' if ranges else 'ok', black_count=len(ranges))
        log.info(f'batch qc black done file={Path(fp).name} ranges={len(ranges)}')
        self._start_batch_audio()

    def _on_batch_black_error(self, err, seq=None):
        if not getattr(self, '_batch_active', False):
            return
        fp = self._batch_current
        if seq is not None and not self._analysis_matches('black', seq, fp):
            self._log_stale_analysis('black', seq, 'batch black error')
            return
        self._stop_analysis_timeout()
        if getattr(self, '_black_thread', None) and not self._black_thread.isRunning():
            self._black_thread = None
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis='mute', black='error', black_count=0)
        log.error(f'batch qc black error file={Path(fp or "").name}: {err}')
        self._start_batch_audio()

    def _start_batch_audio(self):
        if not getattr(self, '_batch_active', False):
            return
        fp = self._batch_current
        idx = self._batch_total - len(self._batch_queue)
        file_name = Path(fp).name
        self.exp_path.setText(f"⏳ 일괄 검수 {idx}/{self._batch_total} — 뮤트: {file_name}")
        self.vp.ai_lbl.setText(f"🔇 일괄 검수 {idx}/{self._batch_total} — {file_name}")
        fps = self._batch_current_info.get('fps', 29.97)
        df = self._batch_current_info.get('df', None)
        offset = self._batch_tc_offset_frames(self._batch_current_info)
        seq = self._next_analysis_seq('audio', fp)
        self._audio_thread = AudioAnalyzeThread(fp, fps, self._batch_mute_thr, self._batch_mute_dur, df, offset)
        self._audio_thread.progress.connect(lambda m, s=seq: self._on_batch_progress('audio', s, m))
        self._audio_thread.finished.connect(lambda result, s=seq: self._on_batch_audio_done(result, seq=s))
        self._audio_thread.error.connect(lambda err, s=seq: self._on_batch_audio_error(err, seq=s))
        self._audio_thread.start()
        self._start_analysis_timeout('audio', '일괄 뮤트 검출', seq, seconds=self._batch_timeout_seconds())

    def _on_batch_audio_done(self, result, seq=None):
        if not getattr(self, '_batch_active', False):
            return
        fp = self._batch_current
        if not self._analysis_matches('audio', seq, fp):
            self._log_stale_analysis('audio', seq, 'batch audio done')
            return
        self._stop_analysis_timeout()
        if getattr(self, '_audio_thread', None) and not self._audio_thread.isRunning():
            self._audio_thread = None
        mutes = result.get('mutes', []) if isinstance(result, dict) else []
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis=None, mute='found' if mutes else 'ok', mute_count=len(mutes))
        log.info(f'batch qc audio done file={Path(fp).name} mutes={len(mutes)}')
        QTimer.singleShot(80, self._start_next_batch_file)

    def _on_batch_audio_error(self, err, seq=None):
        if not getattr(self, '_batch_active', False):
            return
        fp = self._batch_current
        if seq is not None and not self._analysis_matches('audio', seq, fp):
            self._log_stale_analysis('audio', seq, 'batch audio error')
            return
        self._stop_analysis_timeout()
        if getattr(self, '_audio_thread', None) and not self._audio_thread.isRunning():
            self._audio_thread = None
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis=None, mute='error', mute_count=0)
        log.error(f'batch qc audio error file={Path(fp or "").name}: {err}')
        QTimer.singleShot(80, self._start_next_batch_file)

    def _finish_batch_qc(self):
        elapsed = time.monotonic() - float(self._batch_started_at or time.monotonic())
        total = int(self._batch_total or 0)
        self._batch_active = False
        self._batch_queue = []
        self._batch_current = None
        self._batch_current_info = {}
        self._stop_analysis_timeout()
        self._finish_analysis_mode()
        self.refresh_explorer()
        report = None
        if bool(getattr(self, 'chk_auto_report', None) and self.chk_auto_report.isChecked()):
            try:
                report = self._auto_save_qc_report('batch-qc-report')
            except Exception as e:
                log.warning(f'batch qc auto report failed: {e}')
        suffix = f" / 리포트 {Path(report).name}" if report else ""
        self.exp_path.setText(f"✓ 일괄 검수 완료 — {total}개 파일 / {elapsed:.1f}초{suffix}")
        self.vp.ai_lbl.setText(f"✓ 일괄 검수 완료 — {total}개 파일{suffix}")
        log.info(f'batch qc finished files={total} elapsed={elapsed:.1f}s')
        record_state_event('batch-qc', 'finished', files=total, elapsed=f'{elapsed:.1f}s', report=str(report or ''))

    def _run_black_detect(self):
        if not self.vp.cur_file:
            return
        missing = format_missing_runtime_tools(['FFmpeg'])
        if missing:
            self.tabs.setCurrentWidget(self.black_list.parentWidget())
            title = missing.splitlines()[0]
            self.black_status.setText(f"  ⚠ {title}")
            self.vp.ai_lbl.setText(f"⚠ {title}")
            log.warning(f'black detect blocked: {missing}')
            return
        if getattr(self, '_black_thread', None) and self._black_thread.isRunning():
            self.tabs.setCurrentWidget(self.black_list.parentWidget())
            self.black_status.setText("  ⏳ 블랙 검출이 이미 진행 중입니다")
            return
        if not self._begin_analysis_mode('black', '블랙 검출'):
            self.tabs.setCurrentWidget(self.black_list.parentWidget())
            self.black_status.setText("  ⏳ 다른 분석이 진행 중입니다")
            return
        try:
            amount = int(float(self.black_amount.text()))
            threshold = int(float(self.black_threshold.text()))
            amount = max(1, min(100, amount))
            threshold = max(0, min(255, threshold))
            self.black_amount.setText(str(amount))
            self.black_threshold.setText(str(threshold))
            self._save_detection_settings()
        except ValueError:
            self.black_status.setText("  ⚠ 검정%/밝기 값을 숫자로 입력하세요")
            self._finish_analysis_mode()
            return

        self.tabs.setCurrentWidget(self.black_list.parentWidget())
        self.btn_run_black.setEnabled(False)
        self.black_list.clear()
        self.black_status.setText("  ⏳ 블랙 프레임 검출 중...")
        self._black_file = self.vp.cur_file
        seq = self._next_analysis_seq('black', self._black_file)
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(self._black_file, analysis="black")
        try:
            self.vp.btn_black.setEnabled(False)
            self.vp.prog_ai.show()
            self.vp.ai_lbl.setText("⬛ 블랙 프레임 검출 중...")
            self._start_black_elapsed_timer()
        except Exception as e:
            log.debug(f'black ai state: {e}')

        self._black_thread = BlackDetectThread(
            self.vp.cur_file,
            self.vp.fps,
            amount,
            threshold,
            getattr(self.vp, 'df', None),
            getattr(self.vp, '_tc_offset_frames', 0),
        )
        self._black_thread.progress.connect(
            lambda m, s=seq: self._on_analysis_progress('black', s, m)
        )
        self._black_thread.finished.connect(lambda ranges, s=seq: self._on_black_done(ranges, seq=s))
        self._black_thread.error.connect(lambda err, s=seq: self._on_black_error(err, seq=s))
        self._black_thread.start()
        self._start_analysis_timeout('black', '블랙 검출', seq)

    def _on_analysis_progress(self, kind, seq, message):
        if not self._analysis_matches(kind, seq):
            return
        if kind == 'black':
            self.black_status.setText(f"  ⏳ {message}")
        elif kind == 'audio':
            self.audio_status.setText(f"  ⏳ {message}")

    def _on_black_done(self, ranges, seq=None):
        if not self._analysis_matches('black', seq, getattr(self, '_black_file', None)):
            self._log_stale_analysis('black', seq, 'done')
            return
        self._stop_analysis_timeout()
        self.btn_run_black.setEnabled(True)
        if getattr(self, '_black_thread', None) and not self._black_thread.isRunning():
            self._black_thread = None
        if hasattr(self.vp, '_set_file_status'):
            fp = getattr(self, '_black_file', self.vp.cur_file)
            self.vp._set_file_status(
                fp,
                analysis=None,
                black="found" if ranges else "ok",
                black_count=len(ranges),
            )
        try:
            self.vp.btn_black.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"✓ 블랙 검출 완료 — {len(ranges)}구간")
            self._finish_black_elapsed_timer()
        except Exception as e:
            log.debug(f'black ai done state: {e}')
        self.black_list.clear()
        if not ranges:
            item = QListWidgetItem("  블랙 구간 없음")
            item.setForeground(QColor(C['text3']))
            self.black_list.addItem(item)
        else:
            for idx, r in enumerate(ranges, 1):
                frames = int(r.get('frames', 1))
                dur_s = float(r.get('duration', 0))
                label = (f"  #{idx:03d}  {r['tc_start']}  →  {r['tc_end']}"
                         f"   ({frames}f / {dur_s:.3f}초)")
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, r['start'])
                item.setForeground(QColor(C['yellow'] if frames == 1 else C['orange']))
                self.black_list.addItem(item)
        self.black_status.setText(f"  ✓ 완료 — 블랙 {len(ranges)}구간")
        self._finish_analysis_mode()

    def _on_black_error(self, err, seq=None):
        if not self._analysis_matches('black', seq, getattr(self, '_black_file', None)):
            self._log_stale_analysis('black', seq, 'error')
            return
        self._stop_analysis_timeout()
        fp = getattr(self, '_black_file', self.vp.cur_file)
        title = friendly_error_title('black', err, fp)
        self.black_status.setText(f"  ⚠ {title}")
        self.btn_run_black.setEnabled(True)
        if getattr(self, '_black_thread', None) and not self._black_thread.isRunning():
            self._black_thread = None
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis=None, black="error", black_count=0)
        try:
            self.vp.btn_black.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"블랙: {title}")
            self._finish_black_elapsed_timer(prefix='BLACK ERR')
        except Exception as e:
            log.debug(f'black ai error state: {e}')
        self._finish_analysis_mode()
        log.error(f'BlackDetect UI error: {err}')


    def _build_audio(self):
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(0,0,0,0); l.setSpacing(0)

        # ── 툴바 ──
        tb = QWidget(); tb.setFixedHeight(46)
        tb.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,4,8,4); tbl.setSpacing(6)

        _inp = (f"background:{C['input']};border:1px solid {C['border']};border-radius:5px;"
                f"color:{C['teal']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:12px;padding:2px 6px;")

        lbl_thr = QLabel("임계값")
        lbl_thr.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        self.spin_threshold = QLineEdit(str(self._settings.get('mute_threshold', '-50')))
        self.spin_threshold.setFixedWidth(48); self.spin_threshold.setFixedHeight(26)
        self.spin_threshold.setStyleSheet(_inp)
        self.spin_threshold.setToolTip("뮤트 감지 임계값 (dB). 예: -50")

        lbl_dur = QLabel("최소(초)")
        lbl_dur.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        self.spin_duration = QLineEdit(str(self._settings.get('mute_duration', '1.0')))
        self.spin_duration.setFixedWidth(40); self.spin_duration.setFixedHeight(26)
        self.spin_duration.setStyleSheet(_inp)
        self.spin_duration.setToolTip("뮤트 최소 지속 시간 (초). 기본 1초")

        self.audio_preset = QComboBox()
        self.audio_preset.setFixedHeight(26)
        self.audio_preset.setToolTip("블랙/뮤트 분석 기준 프리셋")
        for key, data in self._analysis_presets.items():
            self.audio_preset.addItem(data['label'], key)
        self.audio_preset.setStyleSheet(self._preset_combo_style())
        self.audio_preset.currentIndexChanged.connect(
            lambda _: self._apply_analysis_preset(self.audio_preset.currentData())
        )

        self.btn_run_audio = QPushButton("🔇  뮤트 검출")
        self.btn_run_audio.setFixedHeight(30); self.btn_run_audio.setEnabled(False)
        self.btn_run_audio.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_run_audio.setStyleSheet(
            f"QPushButton{{background:rgba(45,212,191,35);color:{C['teal']};"
            f"border:1px solid rgba(45,212,191,105);border-radius:6px;"
            f"font-size:11px;font-weight:600;padding:0 12px;}}"
            f"QPushButton:hover{{background:rgba(45,212,191,52);border-color:{C['teal']};}}"
            f"QPushButton:disabled{{background:#101218;color:#2a4a4a;border-color:#1a2a2a;}}"
        )
        self.btn_run_audio.clicked.connect(self._run_audio_analyze)
        self.spin_threshold.editingFinished.connect(self._save_detection_settings)
        self.spin_duration.editingFinished.connect(self._save_detection_settings)

        lbl_pre = QLabel("프리셋")
        lbl_pre.setStyleSheet(f"color:{C['text2']};font-size:11px;")
        tbl.addWidget(lbl_pre); tbl.addWidget(self.audio_preset)
        tbl.addSpacing(6)
        tbl.addWidget(lbl_thr); tbl.addWidget(self.spin_threshold)
        tbl.addSpacing(6)
        tbl.addWidget(lbl_dur); tbl.addWidget(self.spin_duration)
        tbl.addStretch(); tbl.addWidget(self.btn_run_audio)
        l.addWidget(tb)

        # ── 상태 라벨 ──
        self.audio_status = QLabel("  파일을 로드하고 뮤트 검출 버튼을 누르세요")
        self.audio_status.setStyleSheet(
            f"color:{C['text2']};font-size:11px;background:{C['panel2']};"
            f"padding:5px 12px;border-bottom:1px solid {C['border']};")
        l.addWidget(self.audio_status)

        # ── 채널 피크 테이블 ──
        peak_hdr = QLabel("  빠른 뮤트 검출 모드")
        peak_hdr.setStyleSheet(
            f"color:{C['text2']};font-size:11px;font-weight:600;"
            f"background:{C['panel']};padding:4px 12px;border-bottom:1px solid {C['border']};")
        l.addWidget(peak_hdr)

        self.peak_table = QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["기준", "처리", "피크/RMS"])
        self.peak_table.setFixedHeight(58)
        self.peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.peak_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.peak_table.setStyleSheet(
            f"QTableWidget{{background:{C['panel2']};color:{C['text1']};"
            f"font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;gridline-color:{C['border']};}}"
            f"QHeaderView::section{{background:{C['panel']};color:{C['text2']};"
            f"font-size:10px;padding:3px;border:none;border-bottom:1px solid {C['border']};}}")
        l.addWidget(self.peak_table)

        # ── 뮤트 구간 목록 ──
        mute_hdr = QLabel("  뮤트 구간")
        mute_hdr.setStyleSheet(
            f"color:{C['text2']};font-size:11px;font-weight:600;"
            f"background:{C['panel']};padding:4px 12px;border-bottom:1px solid {C['border']};")
        l.addWidget(mute_hdr)

        self.mute_list = QListWidget()
        self.mute_list.setStyleSheet(
            f"QListWidget{{background:{C['panel2']};color:{C['text1']};}}"
            f"QListWidget::item{{padding:8px 14px;border-bottom:1px solid {C['border']};"
            f"font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;}}"
            f"QListWidget::item:hover{{background:rgba(255,255,255,7);}}")
        self.mute_list.itemClicked.connect(
            lambda i: self.seek_requested.emit(i.data(Qt.ItemDataRole.UserRole) or 0))
        l.addWidget(self.mute_list, 1)
        return w

    def _reset_audio_tab(self):
        try:
            self.btn_run_audio.setEnabled(bool(self.vp.cur_file))
            self.audio_status.setText("  1/2CH 100ms 레벨 인덱스 캐시로 무음 구간을 검출합니다")
            self.mute_list.clear(); self.peak_table.setRowCount(0)
            if hasattr(self.vp, 'ai_time_lbl'):
                self.vp.ai_time_lbl.hide()
                self.vp.ai_time_lbl.setText('')
        except Exception as e: log.warning(f'audio tab reset: {e}')

    def _run_audio_analyze(self):
        if not self.vp.cur_file: return
        missing = format_missing_runtime_tools(['FFmpeg', 'FFprobe'])
        if missing:
            self.tabs.setCurrentWidget(self.mute_list.parentWidget())
            title = missing.splitlines()[0]
            self.audio_status.setText(f"  ⚠ {title}")
            self.vp.ai_lbl.setText(f"⚠ {title}")
            log.warning(f'audio analyze blocked: {missing}')
            return
        if getattr(self, '_audio_thread', None) and self._audio_thread.isRunning():
            self.tabs.setCurrentWidget(self.mute_list.parentWidget())
            self.audio_status.setText("  ⏳ 뮤트 검출이 이미 진행 중입니다")
            return
        try:
            thr = float(self.spin_threshold.text())
            dur = float(self.spin_duration.text())
            self.spin_threshold.setText(f'{thr:g}')
            self.spin_duration.setText(f'{dur:g}')
            self._save_detection_settings()
        except ValueError:
            self.audio_status.setText("  ⚠ 임계값/최소지속시간을 숫자로 입력하세요"); return
        if not self._begin_analysis_mode('audio', '뮤트 검출'):
            self.tabs.setCurrentWidget(self.mute_list.parentWidget())
            self.audio_status.setText("  ⏳ 다른 분석이 진행 중입니다")
            return

        self.btn_run_audio.setEnabled(False)
        self.mute_list.clear(); self.peak_table.setRowCount(0)
        self.audio_status.setText(f"  ⏳ 1/2CH 레벨 인덱스 확인 중... ({dur:.1f}초 이상)")
        self._audio_file = self.vp.cur_file
        seq = self._next_analysis_seq('audio', self._audio_file)
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(self._audio_file, analysis="mute")
        self.peak_table.setRowCount(1)
        for col, val in enumerate(["1/2CH", "100ms 레벨 캐시", "자동 저장"]):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(C['text2'] if col < 2 else C['yellow']))
            self.peak_table.setItem(0, col, item)
        try:
            self.vp.btn_audio.setEnabled(False)
            self.vp.prog_ai.show()
            self.vp.ai_lbl.setText(f"🔇 1/2CH 레벨 인덱스 확인 중...")
            self._start_audio_elapsed_timer()
        except Exception as e:
            log.debug(f'audio ai state: {e}')

        self._audio_thread = AudioAnalyzeThread(
            self.vp.cur_file,
            self.vp.fps,
            thr,
            dur,
            getattr(self.vp, 'df', None),
            getattr(self.vp, '_tc_offset_frames', 0),
        )
        self._audio_thread.progress.connect(
            lambda m, s=seq: self._on_analysis_progress('audio', s, m)
        )
        self._audio_thread.finished.connect(lambda result, s=seq: self._on_audio_done(result, seq=s))
        self._audio_thread.error.connect(lambda err, s=seq: self._on_audio_error(err, seq=s))
        self._audio_thread.start()
        self._start_analysis_timeout('audio', '뮤트 검출', seq)

    def _on_audio_done(self, result, seq=None):
        if not self._analysis_matches('audio', seq, getattr(self, '_audio_file', None)):
            self._log_stale_analysis('audio', seq, 'done')
            return
        self._stop_analysis_timeout()
        self.btn_run_audio.setEnabled(True)
        if getattr(self, '_audio_thread', None) and not self._audio_thread.isRunning():
            self._audio_thread = None
        mutes    = result.get('mutes', [])
        if hasattr(self.vp, '_set_file_status'):
            fp = getattr(self, '_audio_file', self.vp.cur_file)
            self.vp._set_file_status(
                fp,
                analysis=None,
                mute="found" if mutes else "ok",
                mute_count=len(mutes),
            )
        peaks    = result.get('peaks', {})
        rms_vals = result.get('rms', {})
        ch_count = result.get('ch_count', 0)
        source_ch_count = result.get('source_ch_count', ch_count)
        basis = result.get('channel_basis', f'{ch_count}CH')
        cache_hit = result.get('cache_hit', False)
        mode = "캐시 사용" if cache_hit else "인덱스 생성"

        # 빠른 모드에서는 속도를 위해 피크/RMS 계산을 생략한다.
        self.peak_table.setRowCount(0)
        self.peak_table.insertRow(0)
        for col, val in enumerate([basis, "100ms 레벨 캐시", mode]):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(C['text1'] if col < 2 else C['yellow']))
            self.peak_table.setItem(0, col, item)

        # 뮤트 구간 목록
        self.mute_list.clear()
        if not mutes:
            item = QListWidgetItem("  뮤트 구간 없음")
            item.setForeground(QColor(C['text3']))
            self.mute_list.addItem(item)
        else:
            for m in mutes:
                dur_s = m.get('duration', 0)
                label = (f"  {m['tc_start']}  →  {m['tc_end']}"
                         f"   ({dur_s:.1f}초)")
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, m['start'])
                item.setForeground(QColor(C['teal']))
                self.mute_list.addItem(item)

        self.audio_status.setText(
            f"  ✓ 완료 — 뮤트 {len(mutes)}구간 | {source_ch_count}ch 파일 / {basis} / {mode}")
        try:
            self.vp.btn_audio.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"✓ 뮤트 검출 완료 — {len(mutes)}구간")
            self._finish_audio_elapsed_timer()
        except Exception as e:
            log.debug(f'audio ai done state: {e}')
        self._finish_analysis_mode()

    def _on_audio_error(self, err, seq=None):
        if not self._analysis_matches('audio', seq, getattr(self, '_audio_file', None)):
            self._log_stale_analysis('audio', seq, 'error')
            return
        self._stop_analysis_timeout()
        fp = getattr(self, '_audio_file', self.vp.cur_file)
        title = friendly_error_title('audio', err, fp)
        self.audio_status.setText(f"  ⚠ {title}")
        self.btn_run_audio.setEnabled(True)
        if getattr(self, '_audio_thread', None) and not self._audio_thread.isRunning():
            self._audio_thread = None
        if hasattr(self.vp, '_set_file_status'):
            self.vp._set_file_status(fp, analysis=None, mute="error", mute_count=0)
        try:
            self.vp.btn_audio.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"뮤트: {title}")
            self._finish_audio_elapsed_timer(prefix='MUTE ERR')
        except Exception as e:
            log.debug(f'audio ai error state: {e}')
        self._finish_analysis_mode()
        log.error(f'AudioAnalyze UI error: {err}')

    def _format_elapsed(self, elapsed):
        elapsed = max(0, int(elapsed))
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        if h:
            return f'{h:02d}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def _start_black_elapsed_timer(self):
        self._black_elapsed_start = time.monotonic()
        if not hasattr(self, '_black_elapsed_timer'):
            self._black_elapsed_timer = QTimer(self)
            self._black_elapsed_timer.setInterval(250)
            self._black_elapsed_timer.timeout.connect(self._update_black_elapsed_timer)
        self._update_black_elapsed_timer()
        self._black_elapsed_timer.start()

    def _update_black_elapsed_timer(self):
        start = getattr(self, '_black_elapsed_start', None)
        if start is None:
            return
        elapsed = time.monotonic() - start
        try:
            self.vp.ai_time_lbl.setText(f"BLACK {self._format_elapsed(elapsed)}")
            self.vp.ai_time_lbl.show()
        except Exception as e:
            log.debug(f'black elapsed update: {e}')

    def _finish_black_elapsed_timer(self, prefix='BLACK'):
        start = getattr(self, '_black_elapsed_start', None)
        if hasattr(self, '_black_elapsed_timer'):
            self._black_elapsed_timer.stop()
        if start is None:
            return
        elapsed = time.monotonic() - start
        try:
            self.vp.ai_time_lbl.setText(f"{prefix} {self._format_elapsed(elapsed)}")
            self.vp.ai_time_lbl.show()
        except Exception as e:
            log.debug(f'black elapsed finish: {e}')

    def _start_audio_elapsed_timer(self):
        self._audio_elapsed_start = time.monotonic()
        if not hasattr(self, '_audio_elapsed_timer'):
            self._audio_elapsed_timer = QTimer(self)
            self._audio_elapsed_timer.setInterval(250)
            self._audio_elapsed_timer.timeout.connect(self._update_audio_elapsed_timer)
        self._update_audio_elapsed_timer()
        self._audio_elapsed_timer.start()

    def _update_audio_elapsed_timer(self):
        start = getattr(self, '_audio_elapsed_start', None)
        if start is None:
            return
        elapsed = time.monotonic() - start
        try:
            self.vp.ai_time_lbl.setText(f"MUTE {self._format_elapsed(elapsed)}")
            self.vp.ai_time_lbl.show()
        except Exception as e:
            log.debug(f'audio elapsed update: {e}')

    def _finish_audio_elapsed_timer(self, prefix='MUTE'):
        start = getattr(self, '_audio_elapsed_start', None)
        if hasattr(self, '_audio_elapsed_timer'):
            self._audio_elapsed_timer.stop()
        if start is None:
            return
        elapsed = time.monotonic() - start
        try:
            self.vp.ai_time_lbl.setText(f"{prefix} {self._format_elapsed(elapsed)}")
            self.vp.ai_time_lbl.show()
        except Exception as e:
            log.debug(f'audio elapsed finish: {e}')

    # ── 공통 이벤트 ──────────────────────────────────────
    def _on_file_loaded(self, info, clip_id):
        self.cur_id = clip_id
        self._update_explorer(info, clip_id)
        self._reset_black_tab()
        self._reset_audio_tab()

# ══════════════════════════════════════════════════════════
# 메인 윈도우
# ══════════════════════════════════════════════════════════
