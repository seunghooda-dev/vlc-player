"""
right_panel.py — 오른쪽 탭 패널
RightPanel: 파일 탐색기, 블랙 검출, 오디오 분석
"""
import sys
import time
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui  import QColor
from PyQt6.QtMultimedia import QMediaPlayer

from constants   import C, VIDEO_EXTS, BASE_DIR, log, load_settings, save_settings
from db_models   import sec_to_tc
from threads     import AudioAnalyzeThread, BlackDetectThread
from meters      import mk_label

class RightPanel(QWidget):
    seek_requested = pyqtSignal(float)

    def __init__(self, video_panel):
        super().__init__()
        self.vp = video_panel
        self.cur_id = None
        self._analysis_active = None
        self._analysis_paused_playback = False
        self._analysis_paused_meters = False
        self._settings = load_settings()
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
        tb.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(6,3,6,3); tbl.setSpacing(4)
        _exp_btn_style = (
            f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-size:11px;font-weight:600;padding:0 12px;height:30px;}}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        btn_file = QPushButton("📄  파일 추가"); btn_file.setFixedHeight(32)
        btn_file.setToolTip("개별 영상 파일 추가")
        btn_file.setStyleSheet(_exp_btn_style)
        btn_file.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Space 버블링 차단
        btn_file.clicked.connect(self.vp.add_files)
        tbl.addWidget(btn_file)
        tbl.addStretch()

        # 정렬 버튼
        self._sort_key = 'name'   # 'name' | 'added' | 'size'
        self._sort_asc = True
        _sort_btn_style = (
            f"QPushButton{{background:{C['panel2']};color:{C['text2']};border:1px solid {C['border']};"
            f"border-radius:5px;font-family:Consolas;font-size:10px;font-weight:700;"
            f"padding:0 7px;height:24px;}}"
            f"QPushButton:checked{{background:rgba(90,167,255,30);color:{C['text0']};border-color:{C['blue']};}}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        self._sort_btns = {}
        for key, label, tip in [
            ('name',  '이름', '파일명 순 정렬'),
            ('size',  '크기', '파일 크기 순 정렬'),
            ('added', '추가', '추가된 순서'),
        ]:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(key == 'name')
            b.setFixedHeight(24)
            b.setToolTip(tip)
            b.setStyleSheet(_sort_btn_style)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space 버블링 차단
            def _on_sort(checked, k=key):
                if self._sort_key == k:
                    self._sort_asc = not self._sort_asc  # 같은 키 → 방향 전환
                else:
                    self._sort_key = k
                    self._sort_asc = True
                for kk, bb in self._sort_btns.items():
                    bb.setChecked(kk == self._sort_key)
                self.refresh_explorer()
            b.clicked.connect(_on_sort)
            self._sort_btns[key] = b
            tbl.addWidget(b)

        l.addWidget(tb)

        # 경로 표시
        self.exp_path = mk_label('파일을 추가하세요', C['text3'], 'Consolas', 10)
        self.exp_path.setStyleSheet(
            f"color:{C['text2']};font-family:Consolas;font-size:10px;"
            f"background:{C['panel2']};padding:4px 12px;"
            f"border-bottom:1px solid {C['border']};")
        l.addWidget(self.exp_path)

        # 파일 목록
        self.exp_list = QListWidget()
        self.exp_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.exp_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.exp_list.setStyleSheet(
            f"QListWidget{{background:{C['panel2']};border:none;outline:none;}}"
            f"QListWidget::item{{padding:9px 14px;border-bottom:1px solid {C['border']};"
            f"font-family:'맑은 고딕';font-size:12px;color:{C['text1']};}}"
            f"QListWidget::item:selected{{background:rgba(90,167,255,28);"
            f"border-left:2px solid {C['blue']};color:{C['text0']};}}"
            f"QListWidget::item:hover{{background:rgba(255,255,255,7);}}"
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
        # 우클릭 컨텍스트 메뉴
        self.exp_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.exp_list.customContextMenuRequested.connect(self._exp_context_menu)
        l.addWidget(self.exp_list, 1)

        # 메타 패널
        self.meta_panel = QWidget()
        self.meta_panel.setStyleSheet(f"background:{C['panel']};border-top:1px solid {C['border']};")
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

    def _exp_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        item = self.exp_list.itemAt(pos)
        if not item: return
        fp = item.data(Qt.ItemDataRole.UserRole)
        if not fp: return
        menu = QMenu(self.exp_list)
        menu.setStyleSheet(
            f"QMenu{{background:{C['panel']};color:{C['text1']};border:1px solid {C['border2']};"
            "font-family:'맑은 고딕';font-size:13px;padding:5px 0;border-radius:6px;}"
            "QMenu::item{padding:6px 20px;}"
            f"QMenu::item:selected{{background:rgba(90,167,255,35);color:{C['text0']};}}"
            f"QMenu::separator{{height:1px;background:{C['border']};margin:3px 0;}}"
        )
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

    def refresh_explorer(self):
        # info 없어도 파일 목록만 갱신 (파일 추가/제거 시 호출)
        self.exp_list.clear()
        files = self.vp._files
        cue_fp = self.vp.cur_file

        # 경로 표시: CUE 파일 기준, 없으면 첫 번째 파일 기준
        base_fp = cue_fp or (files[0]["filepath"] if files else "")
        self.exp_path.setText(f"📁 {Path(base_fp).parent}" if base_fp else "파일을 추가하세요")

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
            prefix = "▶  " if is_cue else "    "
            item = QListWidgetItem(f"{prefix}{f['name']}")
            item.setData(Qt.ItemDataRole.UserRole, f["filepath"])
            if is_cue:
                item.setForeground(QColor(C['green']))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setForeground(QColor(C['text1']))
            self.exp_list.addItem(item)
            if is_cue:
                self.exp_list.setCurrentItem(item)

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
        self.meta_labels["duration"].setText(sec_to_tc(info.get("duration",0),info.get("fps",29.97)))
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
                f"color:{C['yellow']};font-family:Consolas;font-size:12px;padding:2px 6px;")

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
            f"font-family:Consolas;font-size:11px;}}"
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

    def _analysis_thread_running(self):
        for name in ('_black_thread', '_audio_thread'):
            thread = getattr(self, name, None)
            try:
                if thread and thread.isRunning():
                    return True
            except Exception:
                pass
        return False

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
            if hasattr(self.vp, 'status_changed'):
                self.vp.status_changed.emit(f"  ⏸ {label} 중 — 재생/오디오 미터 일시정지")
        except Exception as e:
            log.debug(f'analysis mode begin: {e}')
        return True

    def _finish_analysis_mode(self):
        self._set_transport_enabled(True)
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

    def _run_black_detect(self):
        if not self.vp.cur_file:
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
        try:
            self.vp.btn_black.setEnabled(False)
            self.vp.prog_ai.show()
            self.vp.ai_lbl.setText("⬛ 블랙 프레임 검출 중...")
        except Exception as e:
            log.debug(f'black ai state: {e}')

        self._black_thread = BlackDetectThread(self.vp.cur_file, self.vp.fps, amount, threshold)
        self._black_thread.progress.connect(lambda m: self.black_status.setText(f"  ⏳ {m}"))
        self._black_thread.finished.connect(self._on_black_done)
        self._black_thread.error.connect(self._on_black_error)
        self._black_thread.start()

    def _on_black_done(self, ranges):
        self.btn_run_black.setEnabled(True)
        try:
            self.vp.btn_black.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"✓ 블랙 검출 완료 — {len(ranges)}구간")
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

    def _on_black_error(self, err):
        self.black_status.setText(f"  ⚠ 오류: {err}")
        self.btn_run_black.setEnabled(True)
        try:
            self.vp.btn_black.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"블랙 오류: {err}")
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
                f"color:{C['teal']};font-family:Consolas;font-size:12px;padding:2px 6px;")

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
            f"font-family:Consolas;font-size:11px;gridline-color:{C['border']};}}"
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
            f"font-family:Consolas;font-size:11px;}}"
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

        self._audio_thread = AudioAnalyzeThread(self.vp.cur_file, self.vp.fps, thr, dur)
        self._audio_thread.progress.connect(lambda m: self.audio_status.setText(f"  ⏳ {m}"))
        self._audio_thread.finished.connect(self._on_audio_done)
        self._audio_thread.error.connect(self._on_audio_error)
        self._audio_thread.start()

    def _on_audio_done(self, result):
        self.btn_run_audio.setEnabled(True)
        mutes    = result.get('mutes', [])
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

    def _on_audio_error(self, err):
        self.audio_status.setText(f"  ⚠ 오류: {err}")
        self.btn_run_audio.setEnabled(True)
        try:
            self.vp.btn_audio.setEnabled(True)
            self.vp.prog_ai.hide()
            self.vp.ai_lbl.setText(f"뮤트 오류: {err}")
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
