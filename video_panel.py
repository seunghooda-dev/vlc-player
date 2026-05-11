"""
video_panel.py — 메인 비디오 플레이어 패널
VideoPanel: 재생/타임코드/트랜스코드/IN-OUT/블랙검출/오디오미터
"""
import sys, os, json, hashlib, subprocess, time
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication,
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QFrame, QSizePolicy,
    QLabel, QSlider, QPushButton, QProgressBar, QCheckBox, QButtonGroup,
    QLineEdit, QTextEdit, QScrollBar, QTabBar, QTabWidget,
    QAbstractButton, QAbstractSpinBox,
    QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem,
    QAbstractItemView,
    QGraphicsView, QGraphicsScene, QGraphicsProxyWidget,
)
from PyQt6.QtCore import (
    Qt, QTimer, QUrl, pyqtSignal, QSize, QSizeF, QRectF, QObject
)
from PyQt6.QtGui   import QColor, QFont, QDragEnterEvent, QDropEvent
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem

from constants  import (
    C, FFMPEG, FFPROBE, FFPLAY, VLC_DIR, VIDEO_EXTS, TMP_DIR, BASE_DIR, log,
    register_child_process, terminate_child_process, load_settings, save_settings,
    friendly_error_text, friendly_error_title,
    format_missing_runtime_tools,
)
from db_models  import probe, save_clip, frames_to_tc, tc_to_frames
from threads    import ProbeThread, TranscodeThread, LoudnessAnalyzeThread
from meters     import SideMeter, LoudnessMeter, MeterController, mk_btn, mk_label, separator


class VlcAudioAdapter:
    def __init__(self, player):
        self.player = player

    def setVolume(self, value):
        try:
            self.player.audio_set_volume(int(max(0.0, min(1.0, value)) * 100))
        except Exception as e:
            log.debug(f'vlc volume: {e}')


class AudioMixPlayer(QObject):
    """FFmpeg mixes checked MXF mono channels; ffplay outputs the audio only."""
    def __init__(self):
        super().__init__()
        self.filepath = None
        self.channels = [1, 2]
        self.volume = 0.8
        self.rate = 1.0
        self.audio_stream_count = 0
        self.channel_count = 2
        self._ffmpeg = None
        self._ffplay = None
        self._playing = False
        self.last_error = ''
        # FFmpeg/ffplay has a small startup/buffer delay after VLC video starts.
        # Seeking the external audio slightly ahead keeps MXF playback closer.
        self.start_lead_sec = 0.20

    def set_file(self, filepath, audio_stream_count=0, channel_count=2):
        self.filepath = filepath
        self.audio_stream_count = int(audio_stream_count or 0)
        self.channel_count = max(1, int(channel_count or 2))

    def set_channels(self, channels):
        cleaned = []
        for ch in channels or [1, 2]:
            try:
                n = int(ch)
            except Exception:
                continue
            if 1 <= n <= 8 and n not in cleaned:
                cleaned.append(n)
        self.channels = cleaned or [1, 2]

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, float(value)))

    def set_rate(self, rate):
        try:
            self.rate = max(0.5, min(2.0, float(rate)))
        except Exception:
            self.rate = 1.0

    def stop(self):
        self._playing = False
        for proc in (self._ffplay, self._ffmpeg):
            terminate_child_process(proc, 'audio mix')
        self._ffplay = None
        self._ffmpeg = None

    def _proc_state(self, proc):
        if proc is None:
            return 'missing'
        rc = proc.poll()
        return 'running' if rc is None else f'exited({rc})'

    def process_status(self):
        return {
            'playing': bool(self._playing),
            'ffmpeg': self._proc_state(self._ffmpeg),
            'ffplay': self._proc_state(self._ffplay),
        }

    def is_running(self):
        status = self.process_status()
        return (
            status['playing']
            and status['ffmpeg'] == 'running'
            and status['ffplay'] == 'running'
        )

    def restart(self, pos_sec=0.0, lead_sec=None):
        self.stop()
        return self.play(pos_sec, lead_sec=lead_sec)

    def play(self, pos_sec=0.0, lead_sec=None):
        if not self.filepath or not Path(self.filepath).exists():
            self.last_error = '오디오 출력 파일을 찾을 수 없습니다.'
            return False
        self.stop()
        self.last_error = ''
        missing = format_missing_runtime_tools(['FFmpeg', 'FFplay'])
        if missing:
            self.last_error = missing
            log.warning(f'audio mix blocked: {missing}')
            return False
        fc = self._build_filter()
        lead = self.start_lead_sec if lead_sec is None else max(0.0, float(lead_sec))
        start_sec = max(0.0, float(pos_sec) + lead)
        ffmpeg_cmd = [
            FFMPEG, '-hide_banner', '-loglevel', 'error',
            '-ss', f'{start_sec:.3f}',
            '-i', self.filepath,
            '-filter_complex', fc,
            '-map', '[aout]',
            '-vn',
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
            '-ar', '48000',
            '-ac', '2',
            'pipe:1',
        ]
        ffplay_cmd = [
            FFPLAY,
            '-nodisp',
            '-autoexit',
            '-loglevel', 'quiet',
            '-fflags', 'nobuffer',
            '-flags', 'low_delay',
            '-probesize', '32',
            '-analyzeduration', '0',
            '-f', 's16le',
            '-sample_rate', '48000',
            '-ch_layout', 'stereo',
            '-volume', str(int(self.volume * 100)),
            '-i', '-',
        ]
        try:
            self._ffmpeg = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000
            )
            register_child_process(self._ffmpeg, 'audio mix ffmpeg')
            self._ffplay = subprocess.Popen(
                ffplay_cmd,
                stdin=self._ffmpeg.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000
            )
            register_child_process(self._ffplay, 'audio mix ffplay')
            if self._ffmpeg.stdout:
                self._ffmpeg.stdout.close()
            self._playing = True
            log.info(
                'audio mix started '
                f'ffmpeg={self._ffmpeg.pid} ffplay={self._ffplay.pid} '
                f'ch={self.channels} start={start_sec:.3f}s rate={self.rate:.3f}'
            )
        except Exception as e:
            self.last_error = friendly_error_text('audio_mix', e, self.filepath)
            log.error(f'audio mix start failed: {e}')
            self.stop()
            return False
        return True

    def _source_for_channel(self, ch, idx):
        ch = max(1, min(8, int(ch)))
        if self.audio_stream_count > 1:
            return f'0:a:{ch - 1}', ''
        label = f'mono{idx}'
        return label, f'[0:a]pan=mono|c0=c{ch - 1}[{label}]'

    def _tail_filters(self):
        filters = []
        if abs(self.rate - 1.0) > 0.001:
            filters.append(f'atempo={self.rate:.3f}')
        return ','.join(filters) if filters else 'anull'

    def _build_filter(self):
        channels = self.channels or [1, 2]
        setup = []
        if len(channels) == 1:
            src, prep = self._source_for_channel(channels[0], 0)
            if prep:
                setup.append(prep)
            tail = self._tail_filters()
            return ';'.join(setup + [f'[{src}]pan=stereo|c0=c0|c1=c0,{tail}[aout]'])

        stereo_labels = []
        for i, ch in enumerate(channels):
            src, prep = self._source_for_channel(ch, i)
            if prep:
                setup.append(prep)
            out = f'sel{i}'
            if ch % 2:
                pan = f'[{src}]pan=stereo|c0=c0|c1=0*c0[{out}]'
            else:
                pan = f'[{src}]pan=stereo|c0=0*c0|c1=c0[{out}]'
            setup.append(pan)
            stereo_labels.append(f'[{out}]')
        tail = self._tail_filters()
        mix = ''.join(stereo_labels) + f'amix=inputs={len(stereo_labels)}:normalize=0,{tail}[aout]'
        return ';'.join(setup + [mix])


class VlcPlayerAdapter(QObject):
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    playbackStateChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object, str)
    mediaStatusChanged = pyqtSignal(object)

    def __init__(self, video_widget):
        super().__init__()
        vlc_dir = VLC_DIR or Path(r'C:\Program Files\VideoLAN\VLC')
        if hasattr(os, 'add_dll_directory') and Path(vlc_dir).exists():
            os.add_dll_directory(str(vlc_dir))
        import vlc
        self._vlc = vlc
        self._instance = vlc.Instance('--no-video-title-show', '--quiet')
        self._player = self._instance.media_player_new()
        self._video_widget = video_widget
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self._selected_audio_channel = 1
        self._audio_apply_attempts = 0
        self._op_seq = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def _next_op(self):
        self._op_seq += 1
        return self._op_seq

    def _is_current_op(self, seq):
        return seq is None or seq == self._op_seq

    def _bind_hwnd(self):
        try:
            hwnd = int(self._video_widget.winId())
            self._player.set_hwnd(hwnd)
        except Exception as e:
            log.error(f'vlc set_hwnd failed: {e}')

    def setSource(self, url):
        self.stop()
        if not url or not url.isValid():
            return
        path = url.toLocalFile()
        if not path:
            return
        seq = self._next_op()
        self._bind_hwnd()
        media = self._instance.media_new(path)
        self._player.set_media(media)
        self._audio_apply_attempts = 0
        self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        QTimer.singleShot(300, lambda s=seq: self._emit_duration(s))
        QTimer.singleShot(500, lambda s=seq: self._apply_audio_channel(s))

    def _emit_duration(self, seq=None):
        if not self._is_current_op(seq):
            return
        length = self._player.get_length()
        if length and length > 0:
            self.durationChanged.emit(length)

    def play(self):
        seq = self._next_op()
        self._bind_hwnd()
        rc = self._player.play()
        if rc == -1:
            self.errorOccurred.emit(QMediaPlayer.Error.FormatError, 'VLC could not play this file')
            return
        self._state = QMediaPlayer.PlaybackState.PlayingState
        self.playbackStateChanged.emit(self._state)
        self._timer.start()
        QTimer.singleShot(500, lambda s=seq: self._emit_duration(s))
        self._audio_apply_attempts = 0
        QTimer.singleShot(200, lambda s=seq: self._apply_audio_channel(s))
        QTimer.singleShot(700, lambda s=seq: self._apply_audio_channel(s))
        QTimer.singleShot(1200, lambda s=seq: self._apply_audio_channel(s))

    def pause(self):
        self._player.pause()
        self._state = QMediaPlayer.PlaybackState.PausedState
        self.playbackStateChanged.emit(self._state)

    def show_first_frame(self, ms=0):
        target = max(0, int(ms))
        seq = self._next_op()
        try:
            self._bind_hwnd()
            self._player.audio_set_volume(0)
            rc = self._player.play()
            if rc == -1:
                self.errorOccurred.emit(QMediaPlayer.Error.FormatError, 'VLC could not preroll this file')
                return
        except Exception as e:
            log.debug(f'vlc preroll play: {e}')
            return

        def _freeze():
            if not self._is_current_op(seq):
                return
            try:
                self._player.set_time(target)
                self._player.pause()
            except Exception as e:
                log.debug(f'vlc preroll freeze: {e}')
            self._state = QMediaPlayer.PlaybackState.PausedState
            self.positionChanged.emit(target)
            self.playbackStateChanged.emit(self._state)
            self._emit_duration(seq)

        QTimer.singleShot(160, _freeze)
        QTimer.singleShot(
            420,
            lambda s=seq: self.setPosition(target) if self._is_current_op(s) else None
        )

    def stop(self):
        self._next_op()
        self._timer.stop()
        try:
            self._player.stop()
        except Exception:
            pass
        self._state = QMediaPlayer.PlaybackState.StoppedState
        self.playbackStateChanged.emit(self._state)
        self.positionChanged.emit(0)

    def setPosition(self, ms):
        try:
            self._player.set_time(int(ms))
            self.positionChanged.emit(max(0, int(ms)))
        except Exception as e:
            log.debug(f'vlc setPosition: {e}')

    def position(self):
        try:
            return max(0, int(self._player.get_time()))
        except Exception:
            return 0

    def media_length(self):
        try:
            return max(0, int(self._player.get_length()))
        except Exception:
            return 0

    def playbackState(self):
        return self._state

    def setPlaybackRate(self, rate):
        try:
            self._player.set_rate(float(rate))
        except Exception as e:
            log.debug(f'vlc set rate: {e}')

    def audio_set_volume(self, value):
        self._player.audio_set_volume(value)

    def set_audio_channel(self, channel_no):
        try:
            self._selected_audio_channel = max(1, min(8, int(channel_no)))
        except Exception:
            self._selected_audio_channel = 1
        self._audio_apply_attempts = 0
        self._apply_audio_channel(self._op_seq)

    def _iter_audio_track_ids(self):
        tracks = []
        try:
            desc = self._player.audio_get_track_description()
            if isinstance(desc, list):
                for item in desc:
                    if isinstance(item, tuple) and item:
                        tid = int(item[0])
                        if tid >= 0:
                            tracks.append(tid)
                return tracks
            node = desc
            guard = 0
            while node is not None and guard < 64:
                tid = None
                for attr in ('id', 'i_id'):
                    if hasattr(node, attr):
                        tid = getattr(node, attr)
                        break
                if tid is not None and int(tid) >= 0:
                    tracks.append(int(tid))
                node = getattr(node, 'next', None)
                guard += 1
        except Exception as e:
            log.debug(f'vlc audio tracks: {e}')
        return tracks

    def _apply_audio_channel(self, seq=None):
        if not self._is_current_op(seq):
            return
        try:
            tracks = self._iter_audio_track_ids()
            if tracks:
                idx = min(max(self._selected_audio_channel - 1, 0), len(tracks) - 1)
                target = tracks[idx]
                self._player.audio_set_track(target)
                current = self._player.audio_get_track()
                if current != target and self._audio_apply_attempts < 6:
                    self._audio_apply_attempts += 1
                    QTimer.singleShot(250, lambda s=seq: self._apply_audio_channel(s))
            else:
                self._player.audio_set_track(self._selected_audio_channel)
        except Exception as e:
            log.debug(f'vlc set audio channel: {e}')

    def _tick(self):
        pos = self.position()
        self.positionChanged.emit(pos)
        length = self._player.get_length()
        if length and length > 0:
            self.durationChanged.emit(length)
        state = self._player.get_state()
        if state in (self._vlc.State.Ended, self._vlc.State.Stopped):
            if self._state != QMediaPlayer.PlaybackState.StoppedState:
                self._state = QMediaPlayer.PlaybackState.StoppedState
                self.playbackStateChanged.emit(self._state)
                self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
                self._timer.stop()

class VideoPanel(QWidget):
    file_loaded   = pyqtSignal(dict, str)   # info, clip_id
    status_changed= pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.fps=29.97; self.df=False; self.tc_offset=0.0; self.duration=0.0
        self._tc_offset_frames = 0
        self._display_frame = 0
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._source_duration = 0.0
        self._using_preview = False
        self._selected_chs = [1, 2]
        self.in_pt=None; self.out_pt=None
        self._loop=False
        self.cur_file=None; self.cur_info={}; self.cur_id=None
        self._seeking=False
        self._settings = load_settings()
        self._prune_recent_entries()
        self._first_audio_start_after_cue = False
        self._tc_thread=None
        self._probe_thread = None
        self._probe_seq = 0
        self._metadata_ready = False
        self._cue_ready = False
        self._file_loaded_emitted = False
        self._loudness_thread = None
        self._loudness_cache = {}
        self._loudness_seq = 0
        self._dead_threads = []   # abort된 스레드 보관 (GC 소멸 방지)
        self._tc_cache = {}
        self._tc_cache_order = []
        self._preconvert_threads = []
        self._preconvert_jobs = {}
        self._routing_gen  = 0    # 라우팅 세대 ID (stale 시그널 무시용)
        self._play_watchdog_seq = 0
        self._audio_start_gate_seq = 0
        self._audio_start_gate_active = False
        self._cue_ready_seq = 0
        self._audio_recovery_attempts = 0
        self._audio_recovery_max_attempts = 3
        self._audio_recovery_cooldown_until = 0.0
        self._audio_recovery_limit_logged = False
        self._transport_guard_until = 0.0
        self._transport_guard_action = ''
        self.setAcceptDrops(True)
        self._frame_display_timer = QTimer(self)
        self._frame_display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_display_timer.setInterval(8)
        self._frame_display_timer.timeout.connect(self._tick_frame_display)
        self._build_ui()

    def _same_path(self, a, b):
        if not a or not b:
            return False
        try:
            return Path(a).resolve() == Path(b).resolve()
        except Exception:
            return str(a).lower() == str(b).lower()

    def _is_busy_loading(self):
        return bool(getattr(self, '_loading', False))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)

        # INFO BAR
        ib = QWidget(); ib.setFixedHeight(28)
        ib.setStyleSheet(f"background:{C['panel2']};border-bottom:1px solid {C['border']};")
        ibl = QHBoxLayout(ib); ibl.setContentsMargins(12,0,12,0); ibl.setSpacing(0)

        # 재생 LED (깜빡임)
        self.led = QLabel("●")
        self.led.setFixedWidth(18)
        self.led.setStyleSheet(f"color:{C['text3']};font-size:10px;background:transparent;")
        self.led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ibl.addWidget(self.led)
        ibl.addSpacing(6)
        self._led_timer = QTimer(); self._led_timer.setInterval(600)
        self._led_on = False
        def _blink():
            self._led_on = not self._led_on
            self.led.setStyleSheet(
                f"color:{C['green']};font-size:10px;background:transparent;"
                if self._led_on else
                f"color:transparent;font-size:10px;background:transparent;"
            )
        self._led_timer.timeout.connect(_blink)

        def _sep_dot():
            l = mk_label("·", C['text3'], "Consolas", 10)
            l.setContentsMargins(6,0,6,0)
            return l

        self.lbl_fmt  = mk_label("—", C['text2'], "Consolas", 11)
        self.lbl_cod  = mk_label("—", C['text2'], "Consolas", 11)
        self.lbl_res  = mk_label("—", C['text2'], "Consolas", 11)
        self.lbl_fps  = mk_label("—", C['orange'], "Consolas", 11, bold=True)
        self.lbl_df   = mk_label("",  C['teal'],   "Consolas", 10)
        self.lbl_ch   = mk_label("—", C['text2'],  "Consolas", 11)
        for i,l in enumerate([self.lbl_fmt, self.lbl_cod, self.lbl_res,
                               self.lbl_fps, self.lbl_df, self.lbl_ch]):
            if i > 0: ibl.addWidget(_sep_dot())
            ibl.addWidget(l)
        ibl.addStretch()
        self.lbl_dbsaved = mk_label("", C['green'], "Consolas", 11)
        ibl.addWidget(self.lbl_dbsaved)
        layout.addWidget(ib)

        # ── 비디오 + 미터 오버레이 ──
        # QGraphicsView 방식: HWND 없는 순수 Qt 렌더링 → z-order 완전 제어 가능
        # QGraphicsVideoItem(비디오) 위에 QGraphicsProxyWidget(미터)를 scene에 추가

        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(QColor('#000'))

        # 비디오 아이템 — IgnoreAspectRatio로 뷰어에 꽉 차게
        from PyQt6.QtCore import Qt as _Qt
        self._video_item = QGraphicsVideoItem()
        self._video_item.setAspectRatioMode(_Qt.AspectRatioMode.KeepAspectRatio)
        self._scene.addItem(self._video_item)

        # 빈화면 라벨 (비디오 없을 때)
        self.empty_label = QLabel("▶\n\nMXF 파일을 열어주세요\n\n⏏ 파일을 드래그하거나 CUE 버튼을 누르세요")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:14px;background:#000;")
        self._empty_proxy = self._scene.addWidget(self.empty_label)
        self._empty_proxy.setZValue(1)

        # 미터 위젯 → GraphicsProxy로 scene에 추가 (z-order 완전 제어)
        self.side_left  = SideMeter(left=True)
        self.side_right = SideMeter(left=False)
        self.loud_meter = LoudnessMeter()

        self._proxy_left  = self._scene.addWidget(self.side_left)
        self._proxy_right = self._scene.addWidget(self.side_right)
        self._proxy_loud  = self._scene.addWidget(self.loud_meter)
        self._proxy_left.setZValue(10)
        self._proxy_right.setZValue(10)
        self._proxy_loud.setZValue(10)

        # 해상도 오버레이 텍스트 (좌측 하단)
        from PyQt6.QtGui import QFont as _QFont
        self._res_text = self._scene.addText("")
        self._res_text.setDefaultTextColor(QColor(255, 255, 255, 160))
        self._res_text.setFont(_QFont("Cascadia Mono", 9, _QFont.Weight.Bold))
        self._res_text.setZValue(15)

        # QGraphicsView
        self.video_view = QGraphicsView(self._scene)
        self.video_view.setMinimumSize(320, 180)
        self.video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.video_view.setStyleSheet("background:#000; border:none;")
        self.video_view.setFrameShape(QFrame.Shape.NoFrame)
        self.video_view.viewport().setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.video_view.mousePressEvent = lambda e: self.toggle_play()

        # VLC renders into a native HWND. Keep meters outside the video surface
        # as stable broadcast rails so playback cannot cover or move them.
        self.vlc_side_left  = SideMeter(left=True, channel_numbers=[1,3,5,7])
        self.vlc_side_right = SideMeter(left=False, channel_numbers=[2,4,6,8])
        self.vlc_loud_meter = LoudnessMeter()
        self.vlc_side_left.setFixedWidth(116)
        self.vlc_side_right.setFixedWidth(116)
        self.vlc_side_left.setFixedHeight(74)
        self.vlc_side_right.setFixedHeight(74)
        self.vlc_loud_meter.setFixedWidth(70)
        self.vlc_loud_meter.setFixedHeight(208)
        for w in (self.vlc_side_left, self.vlc_side_right, self.vlc_loud_meter):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            w.show()
        self._proxy_left.hide()
        self._proxy_right.hide()
        self._proxy_loud.hide()

        # video_view resizeEvent
        def _calc_video_rect(W, H):
            # 16:9 비율 유지 — 실제 영상 콘텐츠 영역 계산
            ns = self._video_item.nativeSize()
            if ns.width() > 0 and ns.height() > 0:
                vr = ns.width() / ns.height()
            else:
                vr = 16 / 9
            wr = W / H if H > 0 else vr
            if wr > vr:
                vh = H; vw = H * vr
                ox = (W - vw) / 2; oy = 0
            else:
                vw = W; vh = W / vr
                ox = 0; oy = (H - vh) / 2
            return vw, vh, ox, oy

        def _place_meters(W, H):
            from PyQt6.QtCore import QRectF
            vw, vh, ox, oy = _calc_video_rect(W, H)
            self._proxy_left.setPos(ox, oy)
            self._proxy_right.setPos(ox + vw - self.side_right.width(), oy)
            self._proxy_loud.setPos(ox + vw - self.loud_meter.width(), oy + vh - self.loud_meter.height())
            # 해상도 텍스트 좌측 하단
            rth = self._res_text.boundingRect().height()
            self._res_text.setPos(8, H - rth - 6)

        def _on_view_resize(evt):
            from PyQt6.QtCore import QSizeF, QRectF
            QGraphicsView.resizeEvent(self.video_view, evt)
            W = evt.size().width()
            H = evt.size().height()
            self._scene.setSceneRect(0, 0, W, H)
            self._video_item.setSize(QSizeF(W, H))
            self._empty_proxy.setGeometry(QRectF(0, 0, W, H))
            _place_meters(W, H)

        self._place_meters = _place_meters
        self.video_view.resizeEvent = _on_view_resize
        # 영상 로드 후 nativeSize 확정 시 미터 위치 재계산
        self._video_item.nativeSizeChanged.connect(
            lambda s: _place_meters(self.video_view.width(), self.video_view.height()))

        self.video_widget = self.video_view
        self.video_shell = QWidget()
        self.video_shell.setStyleSheet("background:#000;")
        shell_grid = QGridLayout(self.video_shell)
        shell_grid.setContentsMargins(0,0,0,0)
        shell_grid.setHorizontalSpacing(0)
        shell_grid.setVerticalSpacing(0)

        self.video_stage = QWidget()
        self.video_stage.setStyleSheet("background:#000;")
        self.video_view.setParent(self.video_stage)
        self.video_overlay = QWidget(self.video_view.viewport())
        self.video_overlay.setStyleSheet("background:transparent;")
        self.video_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.video_overlay.hide()
        self.vlc_side_left.setParent(self.video_stage)
        self.vlc_side_right.setParent(self.video_stage)
        self.vlc_loud_meter.setParent(self.video_stage)

        shell_grid.addWidget(self.video_stage, 0, 0, Qt.AlignmentFlag.AlignCenter)
        def _resize_video_stage(evt):
            QWidget.resizeEvent(self.video_shell, evt)
            W = max(1, evt.size().width())
            H = max(1, evt.size().height())
            left_w = self.vlc_side_left.width()
            right_w = self.vlc_side_right.width()
            loud_w = self.vlc_loud_meter.width()
            left_gap = 4
            right_gap = 6
            right_col_w = max(right_w, loud_w) + right_gap
            left_col_w = left_w + left_gap
            top_pad = 0
            bottom_pad = 0
            shell_left, _, shell_right, _ = shell_grid.getContentsMargins()
            max_video_w = max(320, W - shell_left - shell_right - left_col_w - right_col_w)
            max_video_h = max(180, H - top_pad - bottom_pad)
            video_h = min(max_video_h, int(max_video_w * 9 / 16))
            video_w = int(video_h * 16 / 9)
            if video_w > max_video_w:
                video_w = max_video_w
                video_h = int(video_w * 9 / 16)
            stage_h = max(video_h, self.vlc_loud_meter.height() + 16)
            stage_w = video_w + left_col_w + right_col_w
            self.video_stage.setFixedSize(stage_w, stage_h)
            video_y = max(0, (stage_h - video_h) // 2)
            video_x = left_col_w
            self.video_view.setGeometry(video_x, video_y, video_w, video_h)

            audio_y = video_y + 2
            left_x = 0
            right_x = video_x + video_w + 2
            loud_x = video_x + video_w + (right_col_w - loud_w) // 2
            loud_y = stage_h - self.vlc_loud_meter.height() - 2

            self.vlc_side_left.move(left_x, audio_y)
            self.vlc_side_right.move(right_x, audio_y)
            self.vlc_loud_meter.move(loud_x, loud_y)
            self.vlc_side_left.raise_()
            self.vlc_side_right.raise_()
            self.vlc_loud_meter.raise_()
        self.video_shell.resizeEvent = _resize_video_stage
        layout.addWidget(self.video_shell, 3)   # stretch 3: 화면 크게

        # 미터 컨트롤러
        self.meter_ctrl = MeterController(self.vlc_side_left, self.vlc_side_right, self.vlc_loud_meter)
        self.audio_mix = AudioMixPlayer()
        try:
            self._playback_rate = float(self._settings.get('playback_rate', 1.0))
        except Exception:
            self._playback_rate = 1.0
        self._audio_mix_seq = 0
        self._audio_recovery_timer = QTimer(self)
        self._audio_recovery_timer.setInterval(900)
        self._audio_recovery_timer.timeout.connect(self._check_audio_mix_recovery)

        # MEDIA PLAYER
        self.player = VlcPlayerAdapter(self.video_view.viewport())
        self.player.audio_set_volume(0)
        self.player.setPlaybackRate(self._playback_rate)
        volume = max(0, min(100, int(self._settings.get('volume', 80))))
        self.audio_mix.set_volume(volume / 100.0)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        # TIMECODE DISPLAY
        tc_w = QWidget(); tc_w.setFixedHeight(88)
        tc_w.setStyleSheet(f"background:{C['panel2']};border-top:1px solid {C['border']};border-bottom:1px solid {C['border']};")
        tcl = QHBoxLayout(tc_w); tcl.setContentsMargins(16,6,16,6); tcl.setSpacing(0)
        self.tc_main = QLabel('00:00:00;00')
        self.tc_main.setStyleSheet(f"color:{C['yellow']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:38px;font-weight:500;background:transparent;")
        self.tc_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tcl.addWidget(self.tc_main, 3)
        div = QFrame(); div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f"color:{C['border']};"); tcl.addWidget(div)
        tcl.addSpacing(14)
        sg = QGridLayout(); sg.setSpacing(1); sg.setContentsMargins(0,0,0,0)
        sg.setColumnMinimumWidth(0, 36); sg.setColumnMinimumWidth(1, 128)
        self.tc_dur  = QLabel('——:——:——;——')
        self.tc_rem  = QLabel('——:——:——;——')
        self.tc_in_l = QLabel('——:——:——;——')
        self.tc_out_l= QLabel('——:——:——;——')
        for row,(k,v,c) in enumerate([
            ('DUR',  self.tc_dur,   C['text1']),
            ('REM',  self.tc_rem,   C['text1']),
            ('IN',   self.tc_in_l,  C['teal']),
            ('OUT',  self.tc_out_l, C['orange']),
        ]):
            kl = mk_label(k, C['text3'], 'Consolas', 10, bold=True); kl.setFixedWidth(36)
            v.setStyleSheet(f"color:{c};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:14px;background:transparent;")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sg.addWidget(kl, row, 0); sg.addWidget(v, row, 1)
        tcl.addLayout(sg, 2)
        layout.addWidget(tc_w)

        # PROGRESS SLIDER
        pw = QWidget(); pw.setFixedHeight(18)
        pw.setStyleSheet(f"background:{C['panel2']};")
        pbl = QHBoxLayout(pw); pbl.setContentsMargins(0,0,0,0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0,1000)
        self.slider.setStyleSheet(
            f"QSlider::groove:horizontal{{height:4px;background:#242936;border-radius:2px;}}"
            f"QSlider::sub-page:horizontal{{background:{C['blue']};border-radius:2px;}}"
            f"QSlider::handle:horizontal{{width:14px;height:14px;margin:-5px 0;background:{C['text0']};"
            f"border:1px solid {C['blue']};border-radius:7px;}}"
            "QSlider::handle:horizontal:hover{background:#ffffff;}"
        )
        self.slider.sliderPressed.connect(lambda: setattr(self,'_seeking',True))
        self.slider.sliderReleased.connect(self._on_slider_release)
        # 클릭 위치로 즉시 점프 (드래그 없이 클릭만 해도 이동)
        def _slider_click(e):
            if e.button() == Qt.MouseButton.LeftButton:
                ratio = e.position().x() / self.slider.width()
                val   = int(ratio * self.slider.maximum())
                self.slider.setValue(val)
                self._seeking = True
                self._on_slider_release()
            QSlider.mousePressEvent(self.slider, e)
        self.slider.mousePressEvent = _slider_click
        pbl.addWidget(self.slider)
        layout.addWidget(pw)

        # TRANSPORT
        tr = QWidget(); tr.setFixedHeight(72)
        tr.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        trl = QHBoxLayout(tr); trl.setContentsMargins(10,8,10,8); trl.setSpacing(4)

        BTN_W  = 50
        BTN_H  = 52
        PLAY_W = 62

        TR_STYLE = (
            f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            f"border-radius:6px;font-size:18px;font-weight:400;min-width:{BTN_W}px;}}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            f"QPushButton:pressed{{background:{C['panel2']};padding-top:2px;}}"
        )

        # ⏏ EJECT
        self.btn_folder = QPushButton("EJECT")
        self.btn_folder.setFixedSize(BTN_W+10, BTN_H)
        self.btn_folder.setToolTip("EJECT — 현재 파일을 화면에서 내립니다")
        self.btn_folder.setStyleSheet(TR_STYLE + "QPushButton{font-size:11px;font-family:'Cascadia Mono','Consolas','D2Coding';font-weight:700;letter-spacing:1px;}")

        # 순수 ASCII 심볼 — 이모지 컬러 렌더링 없음
        self.btn_m1  = QPushButton("-1");    self.btn_m1.setFixedSize(BTN_W, BTN_H); self.btn_m1.setToolTip("-1 프레임  (← 방향키)")
        self.btn_gos = QPushButton("|<<");   self.btn_gos.setFixedSize(BTN_W, BTN_H); self.btn_gos.setToolTip("처음으로  (Home)")
        self.btn_rew = QPushButton("<<");    self.btn_rew.setFixedSize(BTN_W, BTN_H); self.btn_rew.setToolTip("10초 뒤로")
        self.btn_play= QPushButton("▶");     self.btn_play.setFixedSize(PLAY_W, BTN_H); self.btn_play.setToolTip("재생 / 일시정지  (Space)")
        self.btn_stop= QPushButton("■");     self.btn_stop.setFixedSize(BTN_W, BTN_H); self.btn_stop.setToolTip("정지")
        self.btn_fwd = QPushButton(">>");    self.btn_fwd.setFixedSize(BTN_W, BTN_H); self.btn_fwd.setToolTip("10초 앞으로")
        self.btn_goe = QPushButton(">>|");   self.btn_goe.setFixedSize(BTN_W, BTN_H); self.btn_goe.setToolTip("끝으로  (End)")
        self.btn_p1  = QPushButton("+1");    self.btn_p1.setFixedSize(BTN_W, BTN_H); self.btn_p1.setToolTip("+1 프레임  (→ 방향키)")

        _mono = "font-family:'Cascadia Mono','Consolas','D2Coding';font-size:14px;font-weight:700;"
        for b in [self.btn_m1,self.btn_gos,self.btn_rew,self.btn_stop,
                  self.btn_fwd,self.btn_goe,self.btn_p1]:
            b.setStyleSheet(TR_STYLE + f"QPushButton{{{_mono}}}")

        self.btn_stop.setStyleSheet(
            TR_STYLE
            + f"QPushButton{{color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';"
            "font-size:24px;font-weight:700;}}"
        )

        self.btn_play.setStyleSheet(
            TR_STYLE
            + f"QPushButton{{color:{C['text0']};font-size:24px;background:#202632;border-color:{C['blue']};}}"
            + f"QPushButton:hover{{background:#273044;border-color:{C['blue']};}}"
        )

        self.btn_cue = QPushButton('CUE')
        self.btn_cue.setFixedHeight(BTN_H)
        self.btn_cue.setToolTip('CUE\n선택한 파일을 플레이어에 올립니다\n이미 로드된 파일이면 IN 포인트로 이동합니다')
        self.btn_cue.setStyleSheet(
            f"QPushButton{{background:rgba(255,209,102,28);color:{C['yellow']};border:1px solid rgba(255,209,102,95);"
            "border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-weight:700;font-size:14px;"
            "padding:0 22px;}"
            f"QPushButton:hover{{background:rgba(255,209,102,45);border-color:{C['yellow']};color:#ffffff;}}"
            "QPushButton:pressed{padding-top:2px;background:#181818;}"
        )

        self.btn_folder.clicked.connect(self.eject_clip)
        self.btn_m1.clicked.connect(lambda: self._step(-1))
        self.btn_p1.clicked.connect(lambda: self._step(1))
        self.btn_gos.clicked.connect(lambda: self._set_position(0))
        self.btn_goe.clicked.connect(lambda: self._set_position(max(0,int(self.duration*1000)-100)))
        self.btn_rew.clicked.connect(lambda: self._set_position(max(0,self.player.position()-10000)))
        self.btn_fwd.clicked.connect(lambda: self._set_position(min(int(self.duration*1000),self.player.position()+10000)))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_cue.clicked.connect(self._cue)

        for w in [self.btn_folder,separator(),self.btn_m1,self.btn_gos,self.btn_rew,
                  self.btn_play,self.btn_stop,self.btn_fwd,self.btn_goe,self.btn_p1]:
            trl.addWidget(w)
        trl.addStretch()

        # 볼륨 슬라이더
        vol_lbl = QLabel('VOL')
        vol_lbl.setStyleSheet(f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        volume = max(0, min(100, int(self._settings.get('volume', 80))))
        self.vol_slider.setValue(volume)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setFixedHeight(BTN_H)
        self.vol_slider.setToolTip('볼륨 조절 (0~100%)')
        self.vol_slider.setStyleSheet(
            f"QSlider::groove:horizontal{{height:3px;background:#242936;border-radius:2px;}}"
            f"QSlider::sub-page:horizontal{{background:{C['text1']};border-radius:2px;}}"
            'QSlider::handle:horizontal{width:12px;height:12px;margin:-5px 0;'
            f"background:{C['text0']};border-radius:6px;}}"
            'QSlider::handle:horizontal:hover{background:#ffffff;}'
        )
        self.vol_pct = QLabel(f'{volume}%')
        self.vol_pct.setStyleSheet(f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;min-width:30px;")
        self.vol_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        def _on_vol(v):
            self.player.audio_set_volume(0)
            self.audio_mix.set_volume(v / 100.0)
            if self.cur_file and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._schedule_audio_mix(delay_ms=120, restart=True)
            self.vol_pct.setText(f'{v}%')
            self._settings = save_settings(volume=int(v))
        self.vol_slider.valueChanged.connect(_on_vol)

        trl.addSpacing(8)
        trl.addWidget(vol_lbl)
        trl.addSpacing(4)
        trl.addWidget(self.vol_slider)
        trl.addWidget(self.vol_pct)
        trl.addSpacing(12)
        trl.addWidget(self.btn_cue)
        layout.addWidget(tr)

        # AUDIO CHANNEL SELECT BAR
        ch_bar = QWidget(); ch_bar.setFixedHeight(34)
        ch_bar.setStyleSheet(f"background:{C['panel2']};border-bottom:1px solid {C['border']};")
        chl = QHBoxLayout(ch_bar); chl.setContentsMargins(12,4,12,4); chl.setSpacing(6)
        ch_lbl = QLabel("CH"); ch_lbl.setStyleSheet(f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;")
        ch_lbl.setFixedWidth(20)
        chl.addWidget(ch_lbl)

        self._ch_checks = []   # (checkbox, channel_no) list
        self._ch_group  = QButtonGroup(self); self._ch_group.setExclusive(False)
        default_channels = [1, 2]

        CH_STYLE = (
            f"QCheckBox{{color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;spacing:5px;}}"
            f"QCheckBox:checked{{color:{C['teal']};font-weight:bold;}}"
            f"QCheckBox::indicator{{width:12px;height:12px;border:1px solid {C['border']};border-radius:3px;background:{C['panel']};}}"
            f"QCheckBox::indicator:checked{{background:{C['teal']};border-color:{C['teal']};}}"
            f"QCheckBox::indicator:hover{{border-color:{C['border2']};}}"
        )
        for i in range(8):
            ch_no = i + 1
            cb = QCheckBox(f"{ch_no}")
            cb.setStyleSheet(CH_STYLE)
            cb.setChecked(ch_no in default_channels)
            self._ch_checks.append((cb, ch_no))
            self._ch_group.addButton(cb)
            chl.addWidget(cb)
        # 각 체크박스에 직접 연결 (단일 선택)
        for cb, _ in self._ch_checks:
            cb.clicked.connect(self._on_ch_select)
            cb.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space 토글 방지
        chl.addStretch()
        layout.addWidget(ch_bar)

        # AI BAR
        ai = QWidget(); ai.setFixedHeight(46)
        ai.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        ail = QHBoxLayout(ai); ail.setContentsMargins(10,6,10,6); ail.setSpacing(6)

        def _ai_btn(label, tooltip):
            b = QPushButton(label); b.setFixedHeight(30); b.setEnabled(False)
            b.setToolTip(tooltip)
            b.setStyleSheet(
                f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:11px;font-weight:600;padding:0 12px;}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
                f"QPushButton:enabled{{color:{C['text1']};}}"
                f"QPushButton:disabled{{color:{C['text3']};border-color:#1c2029;background:#101218;}}"
            )
            return b

        self.btn_black = _ai_btn('⬛  블랙', '1프레임 이상 검정 화면 구간 검출')
        self.btn_audio = _ai_btn('🔇  뮤트', '1초 이상 무음 구간 수동 검출 + 피크 측정')

        self.prog_ai = QProgressBar()
        self.prog_ai.setFixedHeight(4); self.prog_ai.setRange(0,0); self.prog_ai.hide()
        self.prog_ai.setStyleSheet(
            f"QProgressBar{{background:#242936;border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{C['blue']};border-radius:2px;}}"
        )
        self.ai_lbl = mk_label('파일을 열면 AI 분석을 시작할 수 있습니다', C['text3'], 'Consolas', 10)
        self.ai_time_lbl = mk_label('', C['yellow'], 'Consolas', 10, bold=True)
        self.ai_time_lbl.setFixedWidth(104)
        self.ai_time_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.ai_time_lbl.hide()

        self.btn_black.clicked.connect(self.start_black_detect)
        self.btn_audio.clicked.connect(self.start_audio_analyze)
        ail.addWidget(self.btn_black); ail.addWidget(self.btn_audio)
        ail.addSpacing(8)
        ail.addWidget(self.prog_ai)
        ail.addWidget(self.ai_lbl)
        ail.addWidget(self.ai_time_lbl)
        ail.addStretch()

        # 배속 버튼
        spd_lbl = QLabel('SPEED')
        spd_lbl.setStyleSheet(f"color:{C['text2']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:10px;font-weight:700;")
        ail.addWidget(spd_lbl)
        ail.addSpacing(4)
        self._speed_btns = {}
        saved_rate = min((0.5, 1.0, 1.5, 2.0), key=lambda x: abs(x - self._playback_rate))
        self._playback_rate = saved_rate
        for rate, label in [(0.5,'0.5×'), (1.0,'1×'), (1.5,'1.5×'), (2.0,'2×')]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setCheckable(True)
            b.setChecked(rate == saved_rate)
            b.setStyleSheet(
                f"QPushButton{{background:{C['panel2']};color:{C['text2']};border:1px solid {C['border']};"
                "border-radius:5px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;font-weight:700;padding:0 8px;}"
                f"QPushButton:checked{{background:rgba(90,167,255,35);color:{C['text0']};border-color:{C['blue']};}}"
                f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            )
            def _set_speed(checked, r=rate):
                if not checked: return
                self._playback_rate = r
                self.player.setPlaybackRate(r)
                if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._sync_frame_clock(self.player.position())
                self.audio_mix.set_rate(r)
                if self.cur_file and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._schedule_audio_mix(delay_ms=120, restart=True)
                self._settings = save_settings(playback_rate=r)
                for rr, bb in self._speed_btns.items():
                    bb.setChecked(rr == r)
            b.clicked.connect(_set_speed)
            self._speed_btns[rate] = b
            ail.addWidget(b)
        layout.addWidget(ai)

        # IN/OUT BAR
        io = QWidget(); io.setFixedHeight(36)
        io.setStyleSheet(f"background:{C['panel']};border-bottom:1px solid {C['border']};")
        iol = QHBoxLayout(io); iol.setContentsMargins(10,3,10,3); iol.setSpacing(4)
        _io_style = (
            f"QPushButton{{background:{C['panel3']};color:{C['text1']};border:1px solid {C['border']};"
            "border-radius:6px;font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';font-size:11px;padding:0 10px;height:28px;}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
            "QPushButton:pressed{padding-top:1px;background:#101218;}"
        )
        _io_in_style  = _io_style
        _io_out_style = _io_style
        for txt,cb,tip,st in [
            ('[ I ]  IN', self._set_in, 'IN 포인트 설정  (I 키)', _io_in_style),
            ('[ O ]  OUT', self._set_out, 'OUT 포인트 설정  (O 키)', _io_out_style),
            ('IN 해제', self._clr_in, 'IN 포인트 해제', _io_style),
            ('OUT 해제', self._clr_out, 'OUT 포인트 해제', _io_style),
            ('IN → 재생', self._cue, 'IN 포인트로 이동 후 재생', _io_style),
        ]:
            b = QPushButton(txt); b.setFixedHeight(28)
            b.setStyleSheet(st); b.setToolTip(tip)
            b.clicked.connect(cb); iol.addWidget(b)
        # 루프 버튼
        self.btn_loop = QPushButton('LOOP')
        self.btn_loop.setFixedHeight(28)
        self.btn_loop.setCheckable(True)
        self.btn_loop.setToolTip('IN→OUT 구간 반복 재생  (IN/OUT 설정 후 활성화)')
        self.btn_loop.setStyleSheet(
            f"QPushButton{{background:{C['panel3']};color:{C['text2']};border:1px solid {C['border']};"
            "border-radius:6px;font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;font-weight:700;"
            "padding:0 12px;height:28px;}"
            f"QPushButton:checked{{background:rgba(45,212,191,34);color:{C['teal']};border-color:{C['teal']};}}"
            f"QPushButton:hover{{background:#222734;color:{C['text0']};border-color:{C['border2']};}}"
        )
        def _toggle_loop(checked):
            self._loop = checked
            if checked and self.in_pt is not None:
                self._set_position(int(self.in_pt * 1000))
                self.player.play()
        self.btn_loop.clicked.connect(_toggle_loop)
        iol.addWidget(self.btn_loop)
        iol.addStretch()
        layout.addWidget(io)

        # 클립 목록 (숨김 — Explorer 탭에서 관리)
        self.clip_list = QListWidget()   # 내부 호환용 (화면 미표시)
        self._files = []

    def _raise_vlc_meters(self):
        self.video_overlay.raise_()
        for w in (self.vlc_side_left, self.vlc_side_right, self.vlc_loud_meter):
            w.show()
            w.raise_()

    # ── 프레임 정확 표시 ─────────────────────────────────
    def _media_fps(self):
        try:
            fps = float(self.fps or 29.97)
        except Exception:
            fps = 29.97
        return max(1.0, fps)

    def _nominal_fps(self):
        return max(1, int(round(self._media_fps())))

    def _drop_frame_enabled(self):
        nom = self._nominal_fps()
        if nom not in (30, 60):
            return False
        return bool(self.df) and abs(self._media_fps() - nom) > 0.01

    def _drop_frames_per_minute(self):
        if not self._drop_frame_enabled():
            return 0
        return 2 if self._nominal_fps() == 30 else 4

    def _duration_frames(self):
        if self.duration <= 0:
            return 0
        return max(0, int(round(self.duration * self._media_fps())))

    def _sec_to_frame(self, sec):
        return max(0, int(round(max(0.0, float(sec)) * self._media_fps())))

    def _ms_to_frame(self, ms):
        return self._sec_to_frame(max(0, int(ms)) / 1000.0)

    def _frame_to_ms(self, frame):
        return int(round(max(0, int(frame)) / self._media_fps() * 1000))

    def _tc_include_offset(self):
        return False

    def _parse_tc_offset_frames(self, tc):
        if tc:
            return tc_to_frames(tc, self._media_fps(), self._drop_frame_enabled())
        return int(round(float(self.tc_offset or 0.0) * self._media_fps()))

    def _frames_to_tc(self, frame, include_offset=False):
        offset = getattr(self, '_tc_offset_frames', 0) if include_offset else 0
        return frames_to_tc(frame, self._media_fps(), self._drop_frame_enabled(), offset)

    def _set_display_frame(self, frame, update_slider=True):
        dur_frames = self._duration_frames()
        if dur_frames > 0:
            frame = max(0, min(dur_frames, int(frame)))
        else:
            frame = max(0, int(frame))
        self._display_frame = frame
        self.tc_main.setText(self._frames_to_tc(frame, include_offset=self._tc_include_offset()))
        rem_frames = max(0, dur_frames - frame)
        self.tc_rem.setText(self._frames_to_tc(rem_frames, include_offset=False))
        if update_slider and self.duration > 0 and not self._seeking:
            pos_sec = frame / self._media_fps()
            self.slider.setValue(max(0, min(1000, int(pos_sec / self.duration * 1000))))

    def _set_display_position_ms(self, ms, update_slider=True):
        self._set_display_frame(self._ms_to_frame(ms), update_slider=update_slider)

    def _sync_frame_clock(self, ms=None):
        if ms is None:
            ms = self.player.position()
        frame = self._ms_to_frame(ms)
        self._clock_anchor_frame = frame
        self._clock_anchor_time = time.perf_counter()
        self._set_display_frame(frame)

    def _tick_frame_display(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._frame_clock_active = False
            self._frame_display_timer.stop()
            return
        elapsed = max(0.0, time.perf_counter() - self._clock_anchor_time)
        rate = max(0.1, float(getattr(self, '_playback_rate', 1.0) or 1.0))
        frame = self._clock_anchor_frame + int(elapsed * self._media_fps() * rate)
        self._set_display_frame(frame)

    # ── 파일 열기 ────────────────────────────────────────
    def _existing_dir(self, value):
        try:
            if not value or not isinstance(value, (str, os.PathLike)):
                return ''
            p = Path(value)
            if p.exists() and p.is_file():
                p = p.parent
            if p.exists() and p.is_dir():
                return str(p)
        except Exception:
            pass
        return ''

    def _file_dialog_start_dir(self, start_dir=None):
        explicit = self._existing_dir(start_dir)
        if explicit:
            return explicit
        return self._load_last_dir()

    def _load_last_dir(self):
        try:
            settings = load_settings()
            for fp in settings.get('recent_files', []):
                try:
                    p = Path(fp)
                    if p.exists() and p.is_file():
                        return str(p.parent)
                except Exception:
                    pass
            last_dir = self._existing_dir(settings.get('last_dir'))
            if last_dir:
                return last_dir
            for folder in settings.get('recent_dirs', []):
                recent_dir = self._existing_dir(folder)
                if recent_dir:
                    return recent_dir
        except Exception:
            pass
        try:
            import json as _j
            p = BASE_DIR / 'last_dir.json'
            legacy_dir = self._existing_dir(_j.loads(p.read_text()).get('folder', ''))
            return legacy_dir or 'C:/'
        except: return 'C:/'

    def _save_last_dir(self, folder):
        try:
            self._remember_recent_dir(folder)
        except Exception as e: log.warning(f'last_dir 저장 실패: {e}')

    def _prune_recent_entries(self):
        try:
            recent_files = []
            for fp in self._settings.get('recent_files', []):
                try:
                    p = Path(fp)
                    if p.exists() and p.is_file() and p.suffix.lower() in VIDEO_EXTS and str(p) not in recent_files:
                        recent_files.append(str(p))
                except Exception:
                    pass
            recent_dirs = []
            for folder in self._settings.get('recent_dirs', []):
                try:
                    p = Path(folder)
                    if p.exists() and p.is_dir() and str(p) not in recent_dirs:
                        recent_dirs.append(str(p))
                except Exception:
                    pass
            if (
                recent_files != self._settings.get('recent_files', [])
                or recent_dirs != self._settings.get('recent_dirs', [])
            ):
                self._settings = save_settings(recent_files=recent_files[:12], recent_dirs=recent_dirs[:8])
                log.info(
                    f'recent entries pruned files={len(recent_files)} dirs={len(recent_dirs)}'
                )
        except Exception as e:
            log.debug(f'recent entries prune: {e}')

    def _remember_recent_dir(self, folder, limit=8):
        try:
            if not folder:
                return
            p = Path(folder)
            if not p.exists() or not p.is_dir():
                return
            folder = str(p)
            recent_dirs = [d for d in self._settings.get('recent_dirs', []) if d and d != folder]
            recent_dirs.insert(0, folder)
            self._settings = save_settings(last_dir=folder, recent_dirs=recent_dirs[:limit])
        except Exception as e:
            log.debug(f'recent dir save: {e}')

    def _remember_recent_file(self, filepath, limit=12):
        try:
            if not filepath:
                return
            p = Path(filepath)
            if not p.exists() or p.suffix.lower() not in VIDEO_EXTS:
                return
            fp = str(p)
            recent_files = [f for f in self._settings.get('recent_files', []) if f and f != fp]
            recent_files.insert(0, fp)
            recent_files = [f for f in recent_files if Path(f).exists()][:limit]
            self._settings = save_settings(recent_files=recent_files)
            self._remember_recent_dir(str(p.parent))
        except Exception as e:
            log.debug(f'recent file save: {e}')

    def _add_file_to_list(self, filepath):
        if not filepath or not Path(filepath).exists():
            return False
        if filepath not in [x["filepath"] for x in self._files]:
            self._files.append(self._new_file_record(filepath))
            self._remember_recent_file(filepath)
            return True
        self._remember_recent_file(filepath)
        return False

    def _new_file_record(self, filepath):
        p = Path(filepath)
        return {
            "name": p.name,
            "filepath": filepath,
            "size": p.stat().st_size,
            "ext": p.suffix.upper().lstrip("."),
            "cue": False,
            "playing": False,
            "black": None,   # None | ok | found | error
            "mute": None,    # None | ok | found | error
            "analysis": None,
        }

    def _file_entry(self, filepath):
        for item in self._files:
            if item.get("filepath") == filepath:
                item.setdefault("cue", False)
                item.setdefault("playing", False)
                item.setdefault("black", None)
                item.setdefault("mute", None)
                item.setdefault("analysis", None)
                return item
        return None

    def _set_file_status(self, filepath, **changes):
        entry = self._file_entry(filepath)
        if not entry:
            return
        entry.update(changes)
        if hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

    def _set_all_files_not_playing(self):
        changed = False
        for item in self._files:
            if item.get("playing"):
                item["playing"] = False
                changed = True
        if changed and hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

    def _on_clip_selected(self, item):
        """클립 단일클릭 — 상태바에 파일명 표시, 아직 CUE 안 함"""
        fp = item.data(Qt.ItemDataRole.UserRole)
        name = Path(fp).name if fp else ""
        self.status_changed.emit(f"  📄 {name}  —  CUE 버튼으로 화면에 올리세요  |  더블클릭으로 바로 CUE")

    def eject_clip(self):
        """⏏ 현재 파일 초기화 — 재생 중지, IN/OUT 해제, 타임코드 리셋"""
        self._stop_all()
        self.cur_file = None
        self.cur_id   = None
        self.cur_info = {}
        self._metadata_ready = False
        self._cue_ready = False
        self._file_loaded_emitted = False
        self._set_loading_state(False)
        self.fps=29.97; self.df=False; self.tc_offset=0.0
        self._tc_offset_frames = 0
        self._display_frame = 0
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self.duration = 0.0
        self._source_duration = 0.0
        self._using_preview = False
        self.in_pt    = None
        self.out_pt   = None
        self._loop    = False
        if hasattr(self,'btn_loop'): self.btn_loop.setChecked(False)

        # 타임코드 초기화
        self.tc_main.setText("00:00:00;00")
        self.tc_dur.setText("00:00:00;00")
        self.tc_rem.setText("00:00:00;00")
        self.tc_in_l.setText("—")
        self.tc_out_l.setText("—")
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")

        # 슬라이더 초기화
        self.slider.setValue(0)

        # 재생버튼 초기화
        self.btn_play.setText("▶")

        # 메타 정보 초기화
        self.lbl_fmt.setText("—"); self.lbl_cod.setText("—")
        self.lbl_res.setText("—"); self.lbl_fps.setText("—"); self.lbl_ch.setText("—")
        self._res_text.setPlainText("")

        # 화면 초기화
        self._video_item.hide()
        self.empty_label.setText("▶\n\nMXF 파일을 열어주세요\n\n파일 추가 버튼 또는 파일 드래그로 불러오세요")
        self._empty_proxy.show()

        # AI 버튼 비활성화
        self.btn_black.setEnabled(False)
        self.btn_audio.setEnabled(False)
        self.ai_lbl.setText("파일을 열면 AI 분석을 시작할 수 있습니다")

        # 클립 리스트 선택 해제
        self.clip_list.clearSelection()
        self._set_all_files_not_playing()
        for f in self._files:
            if f.get("cue") and f.get("black") is None and f.get("mute") is None:
                f["cue"] = False
        if hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

        self.meter_ctrl.set_playing(False)
        self._cancel_audio_mix()
        self.status_changed.emit("  ⏏ EJECT — 파일 초기화됨")

    def _evict_tc_cache(self, max_files=10, max_gb=2.0):
        """tmp 캐시 정리 — 파일 수/용량 초과 시 오래된 것 삭제"""
        # 유효한 파일만 남김
        valid = [(fp, tp) for fp, tp in self._tc_cache.items()
                 if tp and Path(tp).exists()]
        # 용량 계산
        total_bytes = sum(Path(tp).stat().st_size for _, tp in valid)
        # 파일 수 또는 용량 초과 시 오래된 것부터 제거
        order = [fp for fp in self._tc_cache_order if fp in dict(valid)]
        while (len(order) > max_files or
               total_bytes > max_gb * 1024**3) and order:
            oldest_fp = order.pop(0)
            oldest_tp = self._tc_cache.pop(oldest_fp, None)
            if oldest_tp:
                for p in [oldest_tp, oldest_tp.replace('.mp4','_preview.mp4')]:
                    try: Path(p).unlink(missing_ok=True)
                    except Exception as e: log.warning(f'evict unlink {p}: {e}')
                try:
                    sz = Path(oldest_tp).stat().st_size if Path(oldest_tp).exists() else 0
                except Exception: sz = 0
                total_bytes -= sz
        self._tc_cache_order = order

    def _cancel_preconvert_job(self, filepath=None):
        jobs = list(self._preconvert_jobs.items())
        for fp, thread in jobs:
            if filepath and fp != filepath:
                continue
            self._preconvert_jobs.pop(fp, None)
            if thread in self._preconvert_threads:
                self._preconvert_threads.remove(thread)
            if fp in self._tc_cache and not self._tc_cache.get(fp):
                self._tc_cache.pop(fp, None)
            try:
                if thread and thread.isRunning():
                    thread.abort()
            except Exception as e:
                log.debug(f'preconvert cancel: {e}')

    def _preconvert(self, filepath):
        # VLC 원본 재생으로 전환한 뒤에는 MXF 사전 변환이 첫 재생 안정성을 해친다.
        if Path(filepath).suffix.lower() == '.mxf':
            log.info(f'skip preconvert for VLC MXF playback: {Path(filepath).name}')
            return
        # 비-MXF 호환 경로에서만 백그라운드 변환 캐시를 사용한다.

        if filepath in self._tc_cache:
            return  # 이미 변환됨 또는 진행 중

        self._tc_cache[filepath] = None  # 변환 중 마킹
        pairs = self._get_selected_ch_pairs()
        t = TranscodeThread(filepath, pairs)

        def _on_done(tmp_path, fp=filepath, thread=t):
            if hasattr(self, '_tc_cache'):
                self._tc_cache[fp] = tmp_path
                if hasattr(self, '_tc_cache_order') and fp not in self._tc_cache_order:
                    self._tc_cache_order.append(fp)
                self._evict_tc_cache()  # 용량 초과 시 정리
            # 완료된 스레드를 보관 목록에서 제거
            if hasattr(self, '_preconvert_threads') and thread in self._preconvert_threads:
                self._preconvert_threads.remove(thread)
            if hasattr(self, '_preconvert_jobs'):
                self._preconvert_jobs.pop(fp, None)
            self.ai_lbl.setText(f"✓ 사전변환 완료: {Path(fp).name}")

        def _on_err(err, fp=filepath, thread=t):
            if hasattr(self, '_tc_cache') and fp in self._tc_cache:
                del self._tc_cache[fp]   # 실패 시 캐시 제거
            if hasattr(self, '_preconvert_threads') and thread in self._preconvert_threads:
                self._preconvert_threads.remove(thread)
            if hasattr(self, '_preconvert_jobs'):
                self._preconvert_jobs.pop(fp, None)

        t.ready_full.connect(_on_done)
        t.error.connect(_on_err)

        # ★ self에 보관 → GC 소멸 방지 (이게 없으면 함수 종료 즉시 크래시)
        self._preconvert_threads.append(t)
        self._preconvert_jobs[filepath] = t
        t.start()
        self.ai_lbl.setText(f"⏳ 백그라운드 변환 중: {Path(filepath).name}")

    def add_files(self, start_dir=None):
        if self._is_busy_loading():
            self.status_changed.emit('  ⏳ 파일 로드 중입니다 — 완료 후 파일을 추가하세요')
            log.info('add_files ignored while loading')
            return
        start = self._file_dialog_start_dir(start_dir)
        log.info(f'file dialog start dir: {start}')
        files,_ = QFileDialog.getOpenFileNames(self,"파일 선택", start,
            "Video Files (*.mxf *.mp4 *.mov *.mts *.m2ts *.mkv *.avi);;All Files (*)")
        if files:
            self._save_last_dir(str(Path(files[0]).parent))
        new_files = []
        for f in files:
            if self._add_file_to_list(f):
                new_files.append(f)
        self._refresh_clip_list()
        if new_files:
            self.ai_lbl.setText("✓ 파일 추가 완료 — CUE 또는 더블클릭으로 원본 MXF를 바로 재생합니다")
        # Explorer 목록 즉시 갱신
        if hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

    def add_recent_file(self, filepath, cue=True):
        if cue and self._is_busy_loading():
            self.status_changed.emit('  ⏳ 파일 로드 중입니다 — 완료 후 다시 선택하세요')
            log.info(f'recent file cue ignored while loading: {Path(filepath).name if filepath else "?"}')
            return
        if not filepath or not Path(filepath).exists():
            self.status_changed.emit(f"  ⚠ 최근 파일을 찾을 수 없습니다: {filepath or '?'}")
            return
        is_new = self._add_file_to_list(filepath)
        self._refresh_clip_list()
        if is_new:
            self.ai_lbl.setText("✓ 파일 추가 완료 — 백그라운드 변환 없이 원본을 사용합니다")
        if cue:
            self.load_file(filepath)
        elif hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

    def _refresh_clip_list(self):
        existing = []
        removed = []
        for f in self._files:
            fp = f.get("filepath")
            try:
                if fp and Path(fp).exists():
                    existing.append(f)
                else:
                    removed.append(f.get("name") or str(fp))
            except Exception:
                removed.append(f.get("name") or str(fp))
        if removed:
            self._files = existing
            log.warning(f'missing loaded files removed: {", ".join(removed[:5])}')
            if self.cur_file and not Path(self.cur_file).exists():
                self.cur_file = None
                self.cur_info = {}
        self.clip_list.clear()
        for f in self._files:
            item = QListWidgetItem(
                f"  {f['name']}  —  {f['ext']}  {f['size']//1024//1024}MB"
            )
            item.setData(Qt.ItemDataRole.UserRole, f["filepath"])
            self.clip_list.addItem(item)
        # Explorer도 항상 동기화
        if hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()

    def clear_clips(self):
        self._files=[]; self.clip_list.clear()
        self._cancel_audio_mix()
        self.player.stop(); self._video_item.hide(); self._empty_proxy.show()

    def _retire_tc(self):
        """_tc_thread를 abort 후 dead_threads로 이동.
        finished 시그널로 완전 종료 시점에 자동 제거 → isRunning() 타이밍 충돌 방지"""
        if self._tc_thread:
            t = self._tc_thread
            self._tc_thread = None
            # finished 시그널: 스레드가 완전히 종료된 시점에 dead_threads에서 제거
            def _on_finished(thread=t):
                try:
                    self._dead_threads.remove(thread)
                    log.debug(f'dead_thread 제거: {thread} (finished)')
                except ValueError:
                    pass  # 이미 제거됐으면 무시
            t.finished.connect(_on_finished)
            self._dead_threads.append(t)
            t.abort()   # abort는 finished 시그널 연결 후 호출 (순서 중요)

    def _retire_loudness_analysis(self):
        self._loudness_seq += 1
        if not self._loudness_thread:
            return
        t = self._loudness_thread
        self._loudness_thread = None

        def _on_finished(thread=t):
            try:
                self._dead_threads.remove(thread)
            except ValueError:
                pass

        try:
            t.finished.connect(_on_finished)
        except Exception:
            pass
        self._dead_threads.append(t)
        try:
            t.abort()
        except Exception as e:
            log.debug(f'loudness abort: {e}')

    def _retire_probe(self):
        self._probe_seq += 1
        if not self._probe_thread:
            return
        t = self._probe_thread
        self._probe_thread = None

        def _on_finished(thread=t):
            try:
                self._dead_threads.remove(thread)
            except ValueError:
                pass

        try:
            t.finished.connect(_on_finished)
        except Exception:
            pass
        self._dead_threads.append(t)
        try:
            t.abort()
        except Exception as e:
            log.debug(f'probe abort: {e}')

    def _emit_file_loaded_once(self):
        if self._file_loaded_emitted:
            return
        if not self.cur_file:
            return
        if not getattr(self, '_metadata_ready', False):
            return
        if not getattr(self, '_cue_ready', False):
            return
        self._file_loaded_emitted = True
        self.file_loaded.emit(self.cur_info, self.cur_id or "")

    def _provisional_info(self, filepath):
        p = Path(filepath)
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        return {
            "filename": p.name,
            "filepath": filepath,
            "duration": 0,
            "size": size,
            "bit_rate": 0,
            "fps": 29.97,
            "width": 0,
            "height": 0,
            "codec": "",
            "channels": 0,
            "audio_stream_count": 0,
            "timecode": "",
            "format_short": "XDCAM" if p.suffix.lower() == ".mxf" else p.suffix.upper().lstrip("."),
            "df": True,
            "tc_offset": 0.0,
            "provisional": True,
        }

    def _apply_provisional_metadata(self, filepath):
        info = self._provisional_info(filepath)
        self.cur_info = info
        self.cur_id = None
        self._metadata_ready = False
        self._file_loaded_emitted = False
        self.fps = info.get("fps", 29.97)
        self.df = True
        self.tc_offset = 0.0
        self._tc_offset_frames = 0
        self._display_frame = 0
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self.duration = 0
        self._source_duration = 0
        self._using_preview = False
        self.lbl_fmt.setText(info.get("format_short", "—"))
        self.lbl_cod.setText("—")
        self.lbl_res.setText("—")
        self.lbl_fps.setText("29.97")
        self.lbl_df.setText("DF")
        self.lbl_df.setStyleSheet(
            f"color:{C['teal']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
        )
        self.lbl_ch.setText("SCAN")
        for cb, ch_no in self._ch_checks:
            cb.setChecked(ch_no in (1, 2))
            cb.setEnabled(False)
        self._selected_chs = [1, 2]
        self.tc_dur.setText(self._frames_to_tc(0, include_offset=False))
        self._res_text.setPlainText("")
        self.btn_black.setEnabled(False)
        self.btn_audio.setEnabled(False)
        self.ai_lbl.setText(f"⏳ 메타데이터 분석 중: {Path(filepath).name}")

    def _apply_probe_metadata(self, filepath, info, warnings, emit_loaded=False):
        self.cur_info = info
        self._metadata_ready = True
        self.fps       = info.get("fps", 29.97)
        self.df        = bool(info.get("df", False)) and self._nominal_fps() in (30, 60)
        self.tc_offset = info.get("tc_offset", 0.0)
        self._tc_offset_frames = self._parse_tc_offset_frames(info.get("timecode", ""))
        self._display_frame = 0
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self.duration  = info.get("duration", 0)
        self._source_duration = self.duration
        self._using_preview = False

        self.lbl_fmt.setText(info.get("format_short","—"))
        self.lbl_cod.setText(info.get("codec","—") or "—")
        h = info.get("height",0)
        w = info.get("width", 0)
        res_str = ("4K" if w >= 3840 else "HD" if w >= 1920 else f"{h}p") if h else "—"
        self.lbl_res.setText(res_str)
        fps_str = f"{self.fps:.2f}"
        self.lbl_fps.setText(fps_str)
        df_label = "DF" if self._drop_frame_enabled() else "NDF"
        df_color = C['teal'] if self._drop_frame_enabled() else C['text2']
        self.lbl_df.setText(df_label)
        self.lbl_df.setStyleSheet(f"color:{df_color};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;")
        ch_count = int(info.get('channels', 0) or 0)
        stream_count = max(int(info.get('audio_stream_count', 0) or 0), ch_count)
        self.lbl_ch.setText(f"{stream_count}CH")
        first_enabled = None
        for cb, ch_no in self._ch_checks:
            enabled = ch_no <= stream_count
            cb.setEnabled(enabled and not getattr(self, '_loading', False))
            if enabled and first_enabled is None:
                first_enabled = cb
        default_channels = [1, 2]
        for cb, _ in self._ch_checks:
            cb.setChecked(False)
        default_selected = []
        for cb, ch_no in self._ch_checks:
            if ch_no <= stream_count and ch_no in default_channels:
                cb.setChecked(True)
                default_selected.append(ch_no)
        if not default_selected and first_enabled:
            first_enabled.setChecked(True)
            default_selected = [1]
        self._selected_chs = default_selected or [1, 2]
        self.tc_dur.setText(self._frames_to_tc(self._duration_frames(), include_offset=False))
        vw = info.get('width',0); vh_px = info.get('height',0)
        self._res_text.setPlainText(f"{vw}\u00d7{vh_px}" if vw and vh_px else "")

        self.cur_id = save_clip(info)
        self.lbl_dbsaved.setText("✓ DB 저장됨")
        QTimer.singleShot(2500, lambda: self.lbl_dbsaved.setText(""))

        self.ai_lbl.setText(f"⚠ {warnings[0]}" if warnings else "AI 분석 준비됨")
        ch_count = info.get('channels', 2)
        self.meter_ctrl.start_file(
            filepath, ch_count, self.player, (1, 2),
            info.get('audio_stream_count', 0)
        )
        self.audio_mix.set_file(
            filepath,
            info.get('audio_stream_count', 0),
            ch_count
        )
        self.audio_mix.set_channels(self._selected_chs)
        self._start_loudness_analysis(filepath)
        if getattr(self, '_cue_ready', False):
            self._set_loading_state(False)
        if emit_loaded:
            self._emit_file_loaded_once()

    def _loudness_cache_key(self, filepath):
        try:
            st = Path(filepath).stat()
            return f'{Path(filepath).resolve()}|{st.st_size}|{st.st_mtime_ns}'
        except Exception:
            return str(filepath)

    def _start_loudness_analysis(self, filepath):
        self._retire_loudness_analysis()
        if not filepath or not Path(filepath).exists():
            return
        try:
            stream_count = int(self.cur_info.get('audio_stream_count', 0) or 0)
            ch_count = int(self.cur_info.get('channels', 0) or 0)
        except Exception:
            stream_count = 0
            ch_count = 0
        if stream_count <= 0 and ch_count <= 0:
            self.meter_ctrl.set_loudness_analysis_error('NO AUD')
            return
        missing = format_missing_runtime_tools(['FFmpeg'])
        if missing:
            self.meter_ctrl.set_loudness_analysis_error('NO FF')
            title = missing.splitlines()[0]
            self.status_changed.emit(f'  ⚠ {title}')
            log.warning(f'loudness analysis blocked: {missing}')
            return

        key = self._loudness_cache_key(filepath)
        cached = self._loudness_cache.get(key)
        if cached:
            self._apply_loudness_result(filepath, cached, from_cache=True)
            return

        self.meter_ctrl.set_loudness_analysis_pending('SCAN')
        self._loudness_seq += 1
        seq = self._loudness_seq
        t = LoudnessAnalyzeThread(
            filepath,
            stream_count,
            ch_count or 2,
            self.cur_info.get('duration', self.duration),
        )
        self._loudness_thread = t
        file_at_start = filepath

        def _progress(msg, fp=file_at_start, s=seq):
            if s != self._loudness_seq:
                return
            if fp != self.cur_file:
                return
            text = 'SCAN'
            if '%' in msg:
                pct = msg.rsplit(' ', 1)[-1]
                text = pct[:8]
            self.meter_ctrl.set_loudness_analysis_pending(text)

        def _done(result, fp=file_at_start, cache_key=key, thread=t, s=seq):
            if s != self._loudness_seq:
                log.debug(f'stale loudness result ignored: {Path(fp).name}')
                return
            if self._loudness_thread is thread:
                self._loudness_thread = None
            self._loudness_cache[cache_key] = dict(result)
            self._apply_loudness_result(fp, result)

        def _error(err, fp=file_at_start, thread=t, s=seq):
            if s != self._loudness_seq:
                log.debug(f'stale loudness error ignored: {Path(fp).name}')
                return
            if self._loudness_thread is thread:
                self._loudness_thread = None
            if fp == self.cur_file:
                self.meter_ctrl.set_loudness_analysis_error('ERR')
                self.status_changed.emit(
                    f'  ⚠ {friendly_error_title("loudness", err, fp)} — {Path(fp).name}')
            log.error(f'LoudnessAnalyze UI error: {err}')

        t.progress.connect(_progress)
        t.finished.connect(_done)
        t.error.connect(_error)
        t.start()
        log.info(f'loudness auto analysis started: {Path(filepath).name}')

    def _apply_loudness_result(self, filepath, result, from_cache=False):
        if filepath != self.cur_file:
            return
        integrated = result.get('integrated')
        self.meter_ctrl.set_loudness_analysis_result(integrated)
        src = '캐시' if from_cache else '완료'
        self.status_changed.emit(f'  ▌LKFS {src}  I {integrated:.1f}  |  1/2CH')

    def _set_loading_state(self, loading, message=None):
        self._loading = bool(loading)
        enabled = not self._loading
        for name in (
            'btn_m1', 'btn_gos', 'btn_rew', 'btn_play', 'btn_fwd',
            'btn_goe', 'btn_p1', 'btn_cue',
        ):
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled)
        for btn in getattr(self, '_speed_btns', {}).values():
            btn.setEnabled(enabled)
        stream_count = 0
        try:
            stream_count = max(
                int(self.cur_info.get('audio_stream_count', 0) or 0),
                int(self.cur_info.get('channels', 0) or 0),
            )
        except Exception:
            stream_count = 0
        for cb, ch_no in getattr(self, '_ch_checks', []):
            cb.setEnabled(enabled and stream_count > 0 and ch_no <= stream_count)
        has_file = bool(self.cur_file)
        metadata_ready = bool(getattr(self, '_metadata_ready', False))
        for name in ('btn_black', 'btn_audio'):
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled and has_file and metadata_ready)
        rp = getattr(self, '_right_panel', None)
        if rp and hasattr(rp, 'set_loading_state'):
            rp.set_loading_state(self._loading)
        if message:
            self.ai_lbl.setText(message)

    def _complete_file_load(self, filepath, message, status_message):
        if filepath != self.cur_file:
            return
        self._cue_ready = True
        if not getattr(self, '_metadata_ready', False):
            file_name = Path(filepath).name
            message = "✓ VLC CUE 완료 — 메타데이터 분석 중..."
            status_message = f"  ▌CUE  {file_name}  |  VLC 먼저 준비됨 — 메타데이터 분석 중"
            self._set_loading_state(True, message)
            self.status_changed.emit(status_message)
            return
        self._set_loading_state(False)
        self.ai_lbl.setText(message)
        self.status_changed.emit(status_message)
        self._emit_file_loaded_once()

    def _prepare_vlc_cue(self, filepath, target_ms=0):
        self._cue_ready_seq += 1
        seq = self._cue_ready_seq
        start = time.monotonic()
        timeout_sec = 2.0
        target_ms = max(0, int(target_ms))
        file_name = Path(filepath).name

        def _force_cue_position(label='cue'):
            if seq != self._cue_ready_seq or filepath != self.cur_file:
                return False
            try:
                before = int(self.player.position() or 0)
                self.player.pause()
                self.player.setPosition(target_ms)
                self._sync_frame_clock(target_ms)
                if abs(before - target_ms) > 120:
                    log.debug(
                        f'VLC cue position settle {label}: '
                        f'{file_name} {before}ms -> {target_ms}ms'
                    )
                return True
            except Exception as e:
                log.debug(f'vlc cue position settle {label}: {e}')
                return False

        def _finish_cue():
            if seq != self._cue_ready_seq or filepath != self.cur_file:
                return
            _force_cue_position('pre-complete')

            def _complete_after_settle():
                if seq != self._cue_ready_seq or filepath != self.cur_file:
                    return
                _force_cue_position('complete')
                self._complete_file_load(
                    filepath,
                    "✓ VLC 원본 MXF CUE 완료 — ▶ 재생버튼을 누르세요",
                    f"  ▌CUE  {file_name}  |  VLC MXF 원본 재생  —  ▶ 재생버튼을 누르세요",
                )

            QTimer.singleShot(140, _complete_after_settle)

        def _poll():
            if seq != self._cue_ready_seq or filepath != self.cur_file:
                return
            elapsed = time.monotonic() - start
            media_len = 0
            try:
                if hasattr(self.player, 'media_length'):
                    media_len = self.player.media_length()
            except Exception as e:
                log.debug(f'vlc cue length poll: {e}')
            # MXF는 preroll 전에는 get_length()가 0으로 남는 경우가 많다.
            # probe duration이 있으면 프리롤/seek 타이머가 지나간 뒤 CUE 완료로 본다.
            has_duration_hint = bool(media_len and media_len > 0) or bool(self.duration and self.duration > 0)
            ready = elapsed >= 0.72 and has_duration_hint
            fallback_ready = elapsed >= 1.15
            if ready or fallback_ready:
                if media_len and media_len > 0:
                    log.debug(f'VLC cue ready: {file_name} length={media_len}ms elapsed={elapsed:.2f}s')
                elif not has_duration_hint:
                    log.warning(f'VLC cue fallback without duration: {file_name}')
                else:
                    log.debug(f'VLC cue fallback with probe duration: {file_name} elapsed={elapsed:.2f}s')
                self._empty_proxy.hide()
                self._video_item.show()
                QTimer.singleShot(120, _finish_cue)
                return

            if elapsed < timeout_sec:
                QTimer.singleShot(80, _poll)
                return

            if not has_duration_hint:
                log.warning(f'VLC cue readiness timeout: {file_name}')
            else:
                log.debug(f'VLC cue readiness timeout fallback: {file_name}')
            self._empty_proxy.hide()
            self._video_item.show()
            QTimer.singleShot(120, _finish_cue)

        def _start_preroll():
            if seq != self._cue_ready_seq or filepath != self.cur_file:
                return
            self._empty_proxy.hide()
            self._video_item.show()
            try:
                self._show_cue_first_frame(target_ms)
            except Exception as e:
                log.debug(f'vlc cue preroll: {e}')
            QTimer.singleShot(80, _poll)

        QTimer.singleShot(80, _start_preroll)

    def _stop_all(self):
        timing_t0 = time.monotonic()
        step_t = timing_t0
        timings = []

        def mark_step(label):
            nonlocal step_t
            now = time.monotonic()
            timings.append(f'{label}={now - step_t:.3f}s')
            step_t = now

        rp = getattr(self, '_right_panel', None)
        if rp and hasattr(rp, 'cancel_active_analysis'):
            try:
                rp.cancel_active_analysis('파일 전환')
            except Exception as e:
                log.debug(f'cancel analysis on stop_all: {e}')
        mark_step('analysis_cancel')
        if hasattr(self, '_audio_recovery_timer'):
            self._audio_recovery_timer.stop()
        self._reset_audio_recovery()
        self._cue_ready_seq += 1
        if hasattr(self, 'meter_ctrl'):
            self.meter_ctrl.set_playing(False)
        mark_step('playback_flags')
        if hasattr(self, 'audio_mix'):
            self._cancel_audio_mix()
        mark_step('audio_mix_stop')
        self._cancel_preconvert_job()
        mark_step('preconvert_cancel')
        self._retire_probe()
        mark_step('probe_retire')
        self._retire_tc()
        self._retire_loudness_analysis()
        mark_step('threads_retire')
        if hasattr(self, 'meter_ctrl'):
            self.meter_ctrl.reset_loudness_analysis()
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except Exception as e: log.debug(f'player stop/clear: {e}')
        mark_step('vlc_clear')
        total = time.monotonic() - timing_t0
        msg = f'stop_all timing: total={total:.3f}s steps={" ".join(timings)}'
        if total >= 0.25:
            log.info(msg)
        else:
            log.debug(msg)

    def _show_file_load_error(self, title, detail='', filepath=None, replace_stage=False):
        name = Path(filepath).name if filepath else '?'
        self.ai_lbl.setText(f'⚠ {title}')
        self.status_changed.emit(f'  ⚠ {title} — {name}')
        if replace_stage or not self.cur_file:
            lines = [f'⚠ {title}']
            if detail:
                lines.append('')
                lines.append(detail)
            lines.append('')
            lines.append(f'파일: {name}')
            self.empty_label.setText('\n'.join(lines))
            self.empty_label.setStyleSheet(
                f"color:{C['red']};font-family:'Cascadia Mono','Consolas','D2Coding';"
                "font-size:13px;background:#000;")
            self._empty_proxy.show()
            self._video_item.hide()

    def _quick_file_preflight(self, filepath):
        if not filepath:
            return False, '파일을 찾을 수 없습니다', '파일 경로가 비어 있습니다.'
        path = Path(filepath)
        if not path.exists():
            return False, '파일을 찾을 수 없습니다', '파일이 이동/삭제됐거나 외장 드라이브 연결이 끊겼는지 확인하세요.'
        if not path.is_file():
            return False, '파일이 아닙니다', '폴더나 특수 경로는 열 수 없습니다.'
        if path.suffix.lower() not in VIDEO_EXTS:
            return False, '지원하지 않는 파일 형식입니다', 'MXF 같은 지원 영상 파일을 선택하세요.'
        try:
            size = path.stat().st_size
        except PermissionError:
            return False, '파일 접근 권한이 없습니다', '읽기 권한이 있는 위치인지, 다른 프로그램이 잠그고 있지 않은지 확인하세요.'
        except OSError as e:
            return False, '파일 정보를 읽을 수 없습니다', str(e)
        if size <= 0:
            return False, '빈 파일입니다', '파일 크기가 0바이트입니다. 정상 MXF 파일인지 확인하세요.'
        try:
            with path.open('rb') as fh:
                fh.read(4096)
        except PermissionError:
            return False, '파일 접근 권한이 없습니다', '읽기 권한이 있는 위치인지, 다른 프로그램이 잠그고 있지 않은지 확인하세요.'
        except OSError as e:
            return False, '파일을 읽을 수 없습니다', str(e)
        return True, '', ''

    def _validate_probe_info(self, filepath, info):
        if not info:
            return (
                False,
                '파일 메타데이터 확인 실패',
                'FFprobe가 파일 구조를 읽지 못했습니다. 파일 손상, 권한, 또는 지원되지 않는 컨테이너인지 확인하세요.',
                [],
            )
        width = int(info.get('width', 0) or 0)
        height = int(info.get('height', 0) or 0)
        codec = str(info.get('codec', '') or '').strip()
        if width <= 0 or height <= 0 or not codec:
            return (
                False,
                '비디오 스트림을 찾지 못했습니다',
                '이 파일에 재생 가능한 비디오 스트림이 없거나 FFprobe가 비디오 정보를 읽지 못했습니다.',
                [],
            )
        warnings = []
        audio_streams = int(info.get('audio_stream_count', 0) or 0)
        channels = int(info.get('channels', 0) or 0)
        if audio_streams <= 0 and channels <= 0:
            warnings.append('오디오 스트림 없음 — 영상만 재생됩니다')
        try:
            if float(info.get('duration', 0) or 0) <= 0:
                warnings.append('길이 정보 없음 — 탐색/REM 표시가 제한될 수 있습니다')
        except Exception:
            warnings.append('길이 정보 확인 실패 — 탐색/REM 표시가 제한될 수 있습니다')
        return True, '', '', warnings

    def _start_metadata_probe(self, filepath, load_t0, timings):
        self._probe_seq += 1
        seq = self._probe_seq
        thread = ProbeThread(filepath)
        self._probe_thread = thread
        file_name = Path(filepath).name

        def _stale():
            return seq != self._probe_seq or filepath != self.cur_file

        def _done(info, elapsed, t=thread):
            if _stale():
                log.debug(f'stale metadata probe ignored: {file_name}')
                return
            if self._probe_thread is t:
                self._probe_thread = None
            ok, title, detail, warnings = self._validate_probe_info(filepath, info)
            if not ok:
                self._metadata_ready = False
                self._set_loading_state(False)
                self.ai_lbl.setText(f'⚠ {title}')
                self.status_changed.emit(f'  ⚠ {title} — {file_name}')
                self._show_file_load_error(title, detail, filepath, replace_stage=False)
                log.warning(
                    f'async metadata probe blocked: {file_name} '
                    f'ffprobe={elapsed:.3f}s | {title} | {detail}'
                )
                return
            if warnings:
                log.warning(f'async metadata probe warning: {file_name} | {"; ".join(warnings)}')
            apply_t0 = time.monotonic()
            self._apply_probe_metadata(filepath, info, warnings, emit_loaded=True)
            apply_elapsed = time.monotonic() - apply_t0
            log.info(
                f'async metadata ready: {file_name} '
                f'ffprobe={elapsed:.3f}s apply={apply_elapsed:.3f}s '
                f'total={time.monotonic() - load_t0:.3f}s '
                f'pre_steps={" ".join(timings)}'
            )
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._reset_audio_recovery()
                self._schedule_audio_mix(delay_ms=80, restart=True, lead_sec=0.0)

        def _error(err, elapsed, t=thread):
            if _stale():
                log.debug(f'stale metadata probe error ignored: {file_name}')
                return
            if self._probe_thread is t:
                self._probe_thread = None
            self._metadata_ready = False
            self._set_loading_state(False)
            self.ai_lbl.setText('⚠ 메타데이터 분석 실패')
            self.status_changed.emit(f'  ⚠ 메타데이터 분석 실패 — {file_name}')
            log.error(f'async metadata probe error: {file_name} ffprobe={elapsed:.3f}s | {err}')

        thread.probed.connect(_done)
        thread.error.connect(_error)
        thread.start()
        log.info(f'async metadata probe started: {file_name}')

    def load_file(self, filepath):
        if self._same_path(filepath, self.cur_file):
            file_name = Path(filepath).name if filepath else '?'
            if self._is_busy_loading():
                self.status_changed.emit(f'  ⏳ 이미 로드 중입니다 — {file_name}')
                log.info(f'duplicate load ignored while loading: {file_name}')
                return
            self._cancel_audio_mix()
            try:
                self.player.pause()
            except Exception:
                pass
            self._show_cue_first_frame(0)
            self._cue_ready = True
            self._set_loading_state(False)
            self.ai_lbl.setText("✓ 이미 CUE 완료 — 첫 프레임으로 이동")
            self.status_changed.emit(f"  ▌CUE  {file_name}  |  이미 로드된 파일")
            log.info(f'duplicate load reused current cue: {file_name}')
            return
        load_t0 = time.monotonic()
        preflight_start = load_t0
        ok, title, detail = self._quick_file_preflight(filepath)
        if not ok:
            log.warning(f'load_file preflight blocked: {filepath} | {title} | {detail}')
            self._show_file_load_error(title, detail, filepath)
            return
        probe_start = time.monotonic()
        step_t = probe_start
        timings = []

        def mark_step(label):
            nonlocal step_t
            now = time.monotonic()
            timings.append(f'{label}={now - step_t:.3f}s')
            step_t = now

        self._remember_recent_file(filepath)
        mark_step('recent')
        log.info(f'load_file: {Path(filepath).name}')
        self._stop_all()
        mark_step('stop_all')
        self._cancel_preconvert_job(filepath)
        mark_step('cancel_preconvert')
        self._reset_audio_recovery()
        mark_step('reset_audio')
        self._set_loading_state(True, f"⏳ 파일 점검 중: {Path(filepath).name}")
        QApplication.processEvents()
        mark_step('loading_ui')
        self.cur_file = filepath
        self._metadata_ready = False
        self._cue_ready = False
        self._file_loaded_emitted = False
        for f in self._files:
            f["cue"] = (f.get("filepath") == filepath)
            f["playing"] = False
        self.cur_id   = None
        self._first_audio_start_after_cue = True
        self.in_pt=None; self.out_pt=None
        self._loop=False
        # 이전 에러 상태(빨간 LED 등) 초기화
        self.led.setStyleSheet(f"color:{C['text3']};font-size:10px;background:transparent;")
        self.empty_label.setStyleSheet(
            f"color:{C['text3']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:14px;background:#000;")
        self.tc_in_l.setText("—"); self.tc_out_l.setText("—")
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")
        mark_step('state_reset')

        # 클립 리스트 선택 표시
        for i in range(self.clip_list.count()):
            item = self.clip_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == filepath:
                self.clip_list.setCurrentItem(item)
                break
        mark_step('list_select')

        if Path(filepath).suffix.lower() == '.mxf':
            self._apply_provisional_metadata(filepath)
            mark_step('provisional_ui')
            self._set_loading_state(True, f"⏳ CUE 준비 중: {Path(filepath).name}")
            self.empty_label.setText('⏳  VLC로 MXF 원본 로딩 중...')
            self._empty_proxy.show(); self._video_item.hide()
            try:
                vlc_set_t0 = time.monotonic()
                self.player.setSource(QUrl.fromLocalFile(filepath))
                self.player.audio_set_volume(0)
                timings.append(f'vlc_set_source={time.monotonic() - vlc_set_t0:.3f}s')
                log.info(
                    f'load_file async cue start: {Path(filepath).name} '
                    f'total_before_cue={time.monotonic() - load_t0:.3f}s '
                    f'steps={" ".join(timings)}'
                )
                self._prepare_vlc_cue(filepath, 0)
                self._start_metadata_probe(filepath, load_t0, list(timings))
            except Exception as e:
                msg = friendly_error_text('vlc_load', e, filepath)
                self.empty_label.setText(f'⚠ {msg}')
                self.ai_lbl.setText(f'⚠ {friendly_error_title("vlc_load", e, filepath)}')
                self._set_loading_state(False)
                log.error(f'VLC load failed: {Path(filepath).name} | {e}')
            return

        # 메타데이터 probe
        probe_only_t0 = time.monotonic()
        info = probe(filepath)
        probe_only = time.monotonic() - probe_only_t0
        timings.append(f'ffprobe={probe_only:.3f}s')
        step_t = time.monotonic()
        ok, title, detail, warnings = self._validate_probe_info(filepath, info)
        mark_step('probe_validate')
        if not ok:
            log.warning(f'load_file probe blocked: {Path(filepath).name} | {title} | {detail}')
            for f in self._files:
                if f.get("filepath") == filepath:
                    f["cue"] = False
                    f["playing"] = False
            self.cur_file = None
            self.cur_info = {}
            self._refresh_clip_list()
            self._set_loading_state(False)
            self._show_file_load_error(title, detail, filepath, replace_stage=True)
            return
        if warnings:
            log.warning(f'load_file probe warning: {Path(filepath).name} | {"; ".join(warnings)}')
        log.info(
            f'file preflight ok: {Path(filepath).name} '
            f'quick={probe_start - preflight_start:.3f}s '
            f'ffprobe={probe_only:.3f}s '
            f'total_to_probe={time.monotonic() - probe_start:.3f}s '
            f'steps={" ".join(timings)}'
        )
        self._set_loading_state(True, f"⏳ CUE 준비 중: {Path(filepath).name}")
        self._metadata_ready = True
        self.cur_info = info
        self.fps       = info.get("fps", 29.97)
        self.df        = bool(info.get("df", False)) and self._nominal_fps() in (30, 60)
        self.tc_offset = info.get("tc_offset", 0.0)
        self._tc_offset_frames = self._parse_tc_offset_frames(info.get("timecode", ""))
        self._display_frame = 0
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self.duration  = info.get("duration", 0)
        self._source_duration = self.duration
        self._using_preview = False

        self.lbl_fmt.setText(info.get("format_short","—"))
        self.lbl_cod.setText(info.get("codec","—") or "—")
        h = info.get("height",0)
        w = info.get("width", 0)
        res_str = ("4K" if w >= 3840 else "HD" if w >= 1920 else f"{h}p") if h else "—"
        self.lbl_res.setText(res_str)
        fps_str = f"{self.fps:.2f}"
        self.lbl_fps.setText(fps_str)
        df_label = "DF" if self._drop_frame_enabled() else "NDF"
        df_color = C['teal'] if self._drop_frame_enabled() else C['text2']
        self.lbl_df.setText(df_label)
        self.lbl_df.setStyleSheet(f"color:{df_color};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;")
        ch_count = int(info.get('channels', 0) or 0)
        stream_count = max(int(info.get('audio_stream_count', 0) or 0), ch_count)
        self.lbl_ch.setText(f"{stream_count}CH")
        # 파일 채널 수에 따라 체크박스 활성화/비활성화
        first_enabled = None
        for cb, ch_no in self._ch_checks:
            enabled = ch_no <= stream_count
            cb.setEnabled(enabled and not getattr(self, '_loading', False))
            if enabled and first_enabled is None:
                first_enabled = cb
        # 방송 QC 기본 모니터링은 파일을 새로 열 때마다 1/2CH 동시 출력으로 시작한다.
        default_channels = [1, 2]
        for cb, _ in self._ch_checks:
            cb.setChecked(False)
        default_selected = []
        for cb, ch_no in self._ch_checks:
            if ch_no <= stream_count and ch_no in default_channels:
                cb.setChecked(True)
                default_selected.append(ch_no)
        if not default_selected and first_enabled:
            first_enabled.setChecked(True)
            default_selected = [1]
        self._selected_chs = default_selected or [1, 2]
        self.tc_dur.setText(self._frames_to_tc(self._duration_frames(), include_offset=False))
        vw = info.get('width',0); vh_px = info.get('height',0)
        self._res_text.setPlainText(f"{vw}\u00d7{vh_px}" if vw and vh_px else "")
        mark_step('metadata_ui')

        # DB 저장
        db_t0 = time.monotonic()
        self.cur_id = save_clip(info)
        timings.append(f'db_save={time.monotonic() - db_t0:.3f}s')
        step_t = time.monotonic()
        self.lbl_dbsaved.setText("✓ DB 저장됨")
        QTimer.singleShot(2500, lambda: self.lbl_dbsaved.setText(""))

        self.btn_black.setEnabled(False)
        self.btn_audio.setEnabled(False)
        self.ai_lbl.setText(f"⚠ {warnings[0]}" if warnings else "AI 분석 준비됨")

        # 실시간 오디오 미터 시작 (채널 수 전달)
        ch_count = info.get('channels', 2)
        self.meter_ctrl.start_file(
            filepath, ch_count, self.player, (1, 2),
            info.get('audio_stream_count', 0)
        )
        self.audio_mix.set_file(
            filepath,
            info.get('audio_stream_count', 0),
            ch_count
        )
        self.audio_mix.set_channels(self._selected_chs)
        self._start_loudness_analysis(filepath)
        mark_step('meter_loudness_start')

        if Path(filepath).suffix.lower() == '.mxf':
            self.empty_label.setText('⏳  VLC로 MXF 원본 로딩 중...')
            self._empty_proxy.show(); self._video_item.hide()
            try:
                vlc_set_t0 = time.monotonic()
                self.player.setSource(QUrl.fromLocalFile(filepath))
                self.player.audio_set_volume(0)
                timings.append(f'vlc_set_source={time.monotonic() - vlc_set_t0:.3f}s')
                log.info(
                    f'load_file timing: {Path(filepath).name} '
                    f'total_before_cue={time.monotonic() - load_t0:.3f}s '
                    f'steps={" ".join(timings)}'
                )
                self._prepare_vlc_cue(filepath, 0)
            except Exception as e:
                msg = friendly_error_text('vlc_load', e, filepath)
                self.empty_label.setText(f'⚠ {msg}')
                self.ai_lbl.setText(f'⚠ {friendly_error_title("vlc_load", e, filepath)}')
                self._set_loading_state(False)
                log.error(f'VLC load failed: {Path(filepath).name} | {e}')
            return

        # CUE — 캐시 확인 후 즉시 또는 변환 후 player에 올림
        cache = getattr(self, '_tc_cache', {})
        cached_tmp = cache.get(filepath)
        pre_job = getattr(self, '_preconvert_jobs', {}).pop(filepath, None)
        if pre_job and pre_job.isRunning():
            try:
                pre_job.abort()
            except Exception as e:
                log.debug(f'preconvert abort for cue: {e}')
            if hasattr(self, '_preconvert_threads') and pre_job in self._preconvert_threads:
                self._preconvert_threads.remove(pre_job)
            if filepath in cache:
                del cache[filepath]
            cached_tmp = None
        if cached_tmp and '_preview' in Path(cached_tmp).stem:
            del cache[filepath]
            cached_tmp = None
        if cached_tmp and Path(cached_tmp).exists():
            # 사전 변환 캐시 있음 → 즉시 올림
            self.empty_label.setText('⏳  로딩 중...')
            self._empty_proxy.show(); self._video_item.hide()
            QTimer.singleShot(50, lambda t=cached_tmp: self._on_transcode_ready(t))
        else:
            # 캐시 없음 → 변환 시작
            ext = Path(filepath).suffix.lower()
            msg = '⏳  파일 변환 중...' if ext in ('.mp4','.mov','.m4v','.mkv','.avi','.mts','.m2ts') \
                  else "⏳  MXF 변환 중...\n잠시만 기다려주세요"
            self.empty_label.setText(msg)
            self._empty_proxy.show(); self._video_item.hide()
            self._tc_thread = TranscodeThread(filepath, self._get_selected_ch_pairs())
            self._tc_thread.ready.connect(self._on_transcode_ready)
            self._tc_thread.ready_full.connect(self._on_transcode_full)
            # 진행률 표시
            self.prog_ai.setRange(0, 100)
            self.prog_ai.setValue(0)
            self.prog_ai.show()
            def _tc_progress(pct):
                self.prog_ai.setValue(pct)
                if pct < 100:
                    self.ai_lbl.setText(f'⏳ 변환 중... {pct}%')
                else:
                    self.ai_lbl.setText('✓ 변환 완료')
                    self.prog_ai.hide()
                    self.prog_ai.setRange(0, 0)  # indeterminate로 복원
            self._tc_thread.progress.connect(_tc_progress)
            def _tc_err(msg, el=self.empty_label, ai=self.ai_lbl, fp=filepath):
                friendly = friendly_error_text('ffmpeg_transcode', msg, fp)
                el.setText(f'⚠ {friendly}')
                ai.setText(f'⚠ {friendly_error_title("ffmpeg_transcode", msg, fp)}')
                self.prog_ai.hide(); self.prog_ai.setRange(0, 0)
            self._tc_thread.error.connect(_tc_err)
            self._tc_thread.start()

        # 미터 위치 갱신

        self._complete_file_load(
            filepath,
            "✓ CUE 완료 — ▶ 재생버튼을 누르세요",
            f"  ▌CUE  {Path(filepath).name}  |  {info.get('format_short','—')}  {info.get('width',0)}×{info.get('height',0)}  —  ▶ 재생버튼을 누르세요",
        )

    def _show_cue_first_frame(self, ms=0):
        ms = max(0, int(ms))
        self._cancel_audio_mix()
        self.player.audio_set_volume(0)
        self._sync_frame_clock(ms)
        if hasattr(self.player, 'show_first_frame'):
            self.player.show_first_frame(ms)
        else:
            self.player.setPosition(ms)

    def _on_transcode_ready(self, tmp):
        if not self.cur_file or getattr(self, '_loading', False): return
        import os
        if not os.path.exists(tmp): return
        try:
            is_preview = 'preview' in tmp
            self._using_preview = is_preview
            self.player.setSource(QUrl.fromLocalFile(tmp))
            self._empty_proxy.hide(); self._video_item.show()
            self.player.pause()
            QTimer.singleShot(120, lambda: self._show_cue_first_frame(0))
            self.ai_lbl.setText(
                "⏳ 전체 변환 중... (재생 가능)" if is_preview
                else "✓ CUE 완료 — ▶ 재생버튼을 누르세요")
            ch_count = self.cur_info.get('channels', 2)
            self.meter_ctrl.start_file(
                self.cur_file, ch_count, self.player, (1, 2),
                self.cur_info.get('audio_stream_count', 0))
        except Exception as e:
            # setSource 실패해도 프로그램 유지
            self.ai_lbl.setText(f'⚠ {friendly_error_title("player_load", e, self.cur_file)}')
            log.error(f'transcode ready load error: {e}')

    def _on_transcode_full(self, tmp):
        if not self.cur_file or getattr(self, '_loading', False): return
        import os
        if not os.path.exists(tmp): return
        try:
            self._using_preview = False
            pos = self.player.position()
            was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            self.player.pause()
            self.player.setSource(QUrl.fromLocalFile(tmp))
            self._empty_proxy.hide(); self._video_item.show()
            self.player.pause()
            QTimer.singleShot(200, lambda: self.player.setPosition(pos))
            if was_playing:
                QTimer.singleShot(350, lambda: self.player.play())
            else:
                QTimer.singleShot(350, lambda p=pos: self._show_cue_first_frame(p))
            if self.cur_file:
                if not hasattr(self, '_tc_cache'):
                    self._tc_cache = {}
                if not hasattr(self, '_tc_cache_order'):
                    self._tc_cache_order = []
                self._tc_cache[self.cur_file] = tmp
                if self.cur_file not in self._tc_cache_order:
                    self._tc_cache_order.append(self.cur_file)
                self._evict_tc_cache()
            self.ai_lbl.setText("✓ CUE 완료 — ▶ 재생버튼을 누르세요")
        except Exception as e:
            self.ai_lbl.setText(f'⚠ {friendly_error_title("player_load", e, self.cur_file)}')
            log.error(f'transcode full swap error: {e}')

    # ── 재생 제어 ────────────────────────────────────────
    def _get_selected_ch_pair(self):
        # 레거시 경로용: 선택 채널을 인접 쌍으로 매핑
        ch = self._get_selected_audio_channels()[0]
        if ch % 2 == 1:
            return (ch, min(ch + 1, 8))
        return (max(1, ch - 1), ch)

    def _get_selected_ch_pairs(self):
        return [self._get_selected_ch_pair()]

    def _get_selected_audio_channels(self):
        selected = [
            channel_no for cb, channel_no in self._ch_checks
            if cb.isChecked() and cb.isEnabled()
        ]
        return selected or [1, 2]

    def _on_ch_select(self):
        if getattr(self, '_loading', False): return
        selected = [
            ch for cb, ch in self._ch_checks
            if cb.isChecked() and cb.isEnabled()
        ]
        if not selected:
            for cb, ch_no in self._ch_checks:
                cb.setChecked(ch_no in (1, 2) and cb.isEnabled())
            selected = self._get_selected_audio_channels()
        self._selected_chs = selected
        if hasattr(self, 'meter_ctrl'):
            if self.cur_file:
                ch_count = self.cur_info.get('channels', 2)
                self.meter_ctrl.start_file(
                    self.cur_file, ch_count, self.player, (1, 2),
                    self.cur_info.get('audio_stream_count', 0))
        if self.cur_file:
            self.player.audio_set_volume(0)
            self.audio_mix.set_channels(selected)
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._reset_audio_recovery()
                self._schedule_audio_mix(delay_ms=120, restart=True)
            label = "/".join(str(ch) for ch in selected)
            self.ai_lbl.setText(f"✓ CH {label} 믹스 출력  |  LKFS 기준은 1/2CH")

    def _apply_audio_channel(self):
        return

    def _on_ch_routed(self, tmp, pos, was_playing):
        if not self.cur_file: return
        import os
        if not os.path.exists(tmp): return
        try:
            self.player.setSource(QUrl.fromLocalFile(tmp))
            self._empty_proxy.hide(); self._video_item.show()
            self.player.pause()
            QTimer.singleShot(300, lambda: self.player.setPosition(pos))
            if was_playing:
                QTimer.singleShot(400, lambda: self.player.play())
            ch_pair = self._get_selected_ch_pair()
            self.ai_lbl.setText(f"✓ {ch_pair[0]}/{ch_pair[1]}CH 출력 중")
        except Exception as e:
            self.ai_lbl.setText(f'⚠ {friendly_error_title("audio_route", e, self.cur_file)}')
            log.error(f'channel route failed: {e}')

    def _start_audio_mix(self, pos_ms=None, lead_sec=None):
        if not self.cur_file:
            return
        if not getattr(self, '_metadata_ready', False):
            log.debug(f'audio mix delayed until metadata ready: {Path(self.cur_file).name}')
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        pos = self.player.position() if pos_ms is None else int(pos_ms)
        self.player.audio_set_volume(0)
        self.audio_mix.set_file(
            self.cur_file,
            self.cur_info.get('audio_stream_count', 0),
            self.cur_info.get('channels', 2)
        )
        self.audio_mix.set_channels(self._get_selected_audio_channels())
        self.audio_mix.set_rate(self._playback_rate)
        lead = lead_sec
        if lead is None:
            lead = 0.0 if getattr(self, '_first_audio_start_after_cue', False) else None
        self._first_audio_start_after_cue = False
        if not self.audio_mix.play(max(0.0, pos / 1000.0), lead_sec=lead):
            title = (self.audio_mix.last_error or '오디오 출력 시작에 실패했습니다.').splitlines()[0]
            self.ai_lbl.setText(f'⚠ {title}')
            self.status_changed.emit(f'  ⚠ {title}')

    def _restart_audio_mix(self, pos_ms=None, lead_sec=None):
        if not self.cur_file:
            return
        if not getattr(self, '_metadata_ready', False):
            log.debug(f'audio mix restart delayed until metadata ready: {Path(self.cur_file).name}')
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        pos = self.player.position() if pos_ms is None else int(pos_ms)
        self.player.audio_set_volume(0)
        self.audio_mix.set_file(
            self.cur_file,
            self.cur_info.get('audio_stream_count', 0),
            self.cur_info.get('channels', 2)
        )
        self.audio_mix.set_channels(self._get_selected_audio_channels())
        self.audio_mix.set_rate(self._playback_rate)
        lead = lead_sec
        if lead is None:
            lead = 0.0 if getattr(self, '_first_audio_start_after_cue', False) else None
        self._first_audio_start_after_cue = False
        if not self.audio_mix.restart(max(0.0, pos / 1000.0), lead_sec=lead):
            title = (self.audio_mix.last_error or '오디오 출력 재시작에 실패했습니다.').splitlines()[0]
            self.ai_lbl.setText(f'⚠ {title}')
            self.status_changed.emit(f'  ⚠ {title}')

    def _cancel_audio_start_gate(self):
        self._audio_start_gate_seq += 1
        self._audio_start_gate_active = False

    def _cancel_audio_mix(self):
        self._cancel_audio_start_gate()
        self._audio_mix_seq += 1
        self.audio_mix.stop()

    def _schedule_audio_mix(self, delay_ms=80, pos_ms=None, restart=False, lead_sec=None):
        if not self.cur_file:
            return
        self._cancel_audio_start_gate()
        self._audio_mix_seq += 1
        seq = self._audio_mix_seq
        file_at_schedule = self.cur_file

        def _run():
            if seq != self._audio_mix_seq:
                return
            if self.cur_file != file_at_schedule:
                return
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
            if restart:
                self._restart_audio_mix(pos_ms, lead_sec=lead_sec)
            else:
                self._start_audio_mix(pos_ms, lead_sec=lead_sec)

        QTimer.singleShot(max(0, int(delay_ms)), _run)

    def _schedule_gated_audio_mix(self):
        if not self.cur_file:
            return
        self._audio_mix_seq += 1
        self._audio_start_gate_seq += 1
        self._audio_start_gate_active = True
        seq = self._audio_start_gate_seq
        file_at_schedule = self.cur_file
        start_ms = int(self.player.position() or 0)
        fps = max(1.0, float(self._media_fps() or 29.97))
        target_delta_ms = max(45, min(120, int(round(1000.0 * 2.0 / fps))))
        deadline = time.monotonic() + 4.5
        file_name = Path(file_at_schedule).name
        log.info(
            f'audio start gate armed file={file_name} '
            f'pos={start_ms}ms target={target_delta_ms}ms'
        )
        self.ai_lbl.setText('영상 시작 확인 후 오디오 출력 준비...')
        QTimer.singleShot(
            30,
            lambda: self._poll_gated_audio_mix(
                seq, file_at_schedule, start_ms, target_delta_ms, deadline
            )
        )

    def _poll_gated_audio_mix(self, seq, file_at_schedule, start_ms, target_delta_ms, deadline):
        if seq != self._audio_start_gate_seq:
            return
        if self.cur_file != file_at_schedule:
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return

        now_ms = int(self.player.position() or 0)
        moved_ms = max(0, now_ms - int(start_ms or 0))
        file_name = Path(file_at_schedule).name
        if moved_ms >= target_delta_ms:
            self._audio_start_gate_seq += 1
            self._audio_start_gate_active = False
            log.info(
                f'audio start gate opened file={file_name} '
                f'pos={now_ms}ms moved={moved_ms}ms'
            )
            self._start_audio_mix(pos_ms=now_ms, lead_sec=0.0)
            return

        if time.monotonic() >= deadline:
            self._audio_start_gate_seq += 1
            self._audio_start_gate_active = False
            log.warning(
                f'audio start gate timeout file={file_name} '
                f'pos={now_ms}ms moved={moved_ms}ms'
            )
            self._start_audio_mix(pos_ms=now_ms, lead_sec=0.0)
            return

        QTimer.singleShot(
            30,
            lambda: self._poll_gated_audio_mix(
                seq, file_at_schedule, start_ms, target_delta_ms, deadline
            )
        )

    def _audio_mix_expected(self):
        if not self.cur_file:
            return False
        selected = self._get_selected_audio_channels()
        if not selected:
            return False
        try:
            audio_streams = int(self.cur_info.get('audio_stream_count', 0) or 0)
            channels = int(self.cur_info.get('channels', 0) or 0)
        except Exception:
            audio_streams = 0
            channels = 0
        return audio_streams > 0 or channels > 0

    def _reset_audio_recovery(self):
        self._audio_recovery_attempts = 0
        self._audio_recovery_cooldown_until = 0.0
        self._audio_recovery_limit_logged = False

    def _check_audio_mix_recovery(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        if not self._audio_mix_expected():
            return
        if getattr(self, '_audio_start_gate_active', False):
            return
        if self.audio_mix.is_running():
            return

        now = time.monotonic()
        if now < self._audio_recovery_cooldown_until:
            return

        status = self.audio_mix.process_status()
        file_name = Path(self.cur_file).name if self.cur_file else '?'
        if self._audio_recovery_attempts >= self._audio_recovery_max_attempts:
            if not self._audio_recovery_limit_logged:
                self._audio_recovery_limit_logged = True
                log.warning(
                    f'audio mix recovery limit reached file={file_name} '
                    f'status={status}'
                )
                self.status_changed.emit(f'  ⚠ 오디오 자동 복구 한도 도달 — {file_name}')
                self.ai_lbl.setText('⚠ 오디오 자동 복구 한도 도달 — LOG 확인')
            return

        self._audio_recovery_attempts += 1
        self._audio_recovery_cooldown_until = now + 1.8
        pos_ms = int(self.player.position() or 0)
        log.warning(
            f'audio mix recovery {self._audio_recovery_attempts}/'
            f'{self._audio_recovery_max_attempts} file={file_name} '
            f'pos={pos_ms}ms status={status}'
        )
        self.status_changed.emit(
            f'  ⚠ 오디오 자동 복구 {self._audio_recovery_attempts}/'
            f'{self._audio_recovery_max_attempts} — {file_name}'
        )
        self.ai_lbl.setText(
            f'⚠ 오디오 믹스 자동 복구 '
            f'{self._audio_recovery_attempts}/{self._audio_recovery_max_attempts}'
        )
        self._restart_audio_mix(pos_ms=pos_ms, lead_sec=0.0)

    def _arm_play_start_watchdog(self, reason='play'):
        if not self.cur_file:
            return
        self._play_watchdog_seq += 1
        seq = self._play_watchdog_seq
        file_at_start = self.cur_file
        start_ms = int(self.player.position() or 0)
        QTimer.singleShot(
            3500,
            lambda: self._check_play_start_watchdog(seq, file_at_start, start_ms, reason)
        )
        log.debug(
            f'play watchdog armed reason={reason} '
            f'file={Path(file_at_start).name} pos={start_ms}ms'
        )

    def _cancel_play_start_watchdog(self):
        self._play_watchdog_seq += 1

    def _check_play_start_watchdog(self, seq, file_at_start, start_ms, reason):
        if seq != self._play_watchdog_seq:
            return
        if self.cur_file != file_at_start:
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return

        now_ms = int(self.player.position() or 0)
        moved_ms = max(0, now_ms - int(start_ms or 0))
        remaining_ms = int(max(0.0, self.duration * 1000.0 - start_ms))
        near_end = 0 < remaining_ms < 1500
        video_ok = moved_ms >= 150 or near_end

        selected = self._get_selected_audio_channels()
        audio_expected = bool(
            selected
            and (
                int(self.cur_info.get('audio_stream_count', 0) or 0) > 0
                or int(self.cur_info.get('channels', 0) or 0) > 0
            )
        )
        audio_status = self.audio_mix.process_status()
        audio_ok = True if not audio_expected else self.audio_mix.is_running()

        if video_ok and audio_ok:
            log.debug(
                f'play watchdog ok reason={reason} '
                f'file={Path(file_at_start).name} moved={moved_ms}ms '
                f'audio={audio_status}'
            )
            return

        problems = []
        if not video_ok:
            problems.append(f'video stagnant {start_ms}->{now_ms}ms')
        if not audio_ok:
            problems.append(f'audio mix {audio_status}')
        detail = '; '.join(problems)
        file_name = Path(file_at_start).name
        log.warning(f'play watchdog warning reason={reason} file={file_name}: {detail}')
        if not video_ok and not audio_ok:
            user_msg = '영상/오디오 시작 확인 필요'
        elif not video_ok:
            user_msg = '영상 위치가 움직이지 않습니다'
        else:
            user_msg = '오디오 출력 시작 확인 필요'
            try:
                self._check_audio_mix_recovery()
            except Exception as e:
                log.debug(f'watchdog audio recovery trigger: {e}')
        self.status_changed.emit(f'  ⚠ {user_msg} — {file_name}')
        self.ai_lbl.setText(f'⚠ {user_msg} — LOG 확인')

    def _set_position(self, ms):
        if self._is_busy_loading():
            self.status_changed.emit('  ⏳ CUE 준비 중입니다 — 잠시만 기다려주세요')
            return
        if self.cur_file and not getattr(self, '_metadata_ready', False):
            self.status_changed.emit('  ⏳ 메타데이터 확인 전입니다 — 잠시만 기다려주세요')
            return
        ms = max(0, min(int(self.duration * 1000), int(ms))) if self.duration > 0 else max(0, int(ms))
        self.player.setPosition(ms)
        self._sync_frame_clock(ms)
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._cancel_audio_mix()
            self._reset_audio_recovery()
            self._schedule_audio_mix(delay_ms=80, pos_ms=ms, restart=True)

    def _set_frame_position(self, frame):
        dur_frames = self._duration_frames()
        if dur_frames > 0:
            frame = max(0, min(dur_frames, int(frame)))
        else:
            frame = max(0, int(frame))
        self._set_position(self._frame_to_ms(frame))

    def _transport_allowed(self, action, cooldown_sec=0.18):
        if getattr(self, '_loading', False):
            self.status_changed.emit('  ⏳ CUE 준비 중입니다 — 잠시만 기다려주세요')
            return False
        if self.cur_file and not getattr(self, '_metadata_ready', False):
            self.status_changed.emit('  ⏳ 메타데이터 확인 전입니다 — 잠시만 기다려주세요')
            return False
        now = time.monotonic()
        if now < self._transport_guard_until:
            log.debug(f'transport ignored action={action} prev={self._transport_guard_action}')
            return False
        self._transport_guard_action = action
        self._transport_guard_until = now + float(cooldown_sec)
        return True

    def toggle_play(self):
        if not self.cur_file:
            return
        if not self._transport_allowed('play_pause'):
            return
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else: self.player.play()

    def stop(self):
        self._transport_guard_action = 'stop'
        self._transport_guard_until = time.monotonic() + 0.12
        if self._is_busy_loading():
            file_name = Path(self.cur_file).name if self.cur_file else '?'
            self._stop_all()
            for f in self._files:
                if self._same_path(f.get("filepath"), self.cur_file):
                    f["cue"] = False
                    f["playing"] = False
            self.cur_file = None
            self.cur_info = {}
            self.cur_id = None
            self._metadata_ready = False
            self._cue_ready = False
            self._file_loaded_emitted = False
            self._set_loading_state(False)
            self.empty_label.setText("▶\n\nMXF 파일을 열어주세요\n\n파일 추가 버튼 또는 파일 드래그로 불러오세요")
            self._empty_proxy.show()
            self._video_item.hide()
            self._refresh_clip_list()
            self.ai_lbl.setText(f"⏹ 로드 취소 — {file_name}")
            self.status_changed.emit(f"  ⏹ 로드 취소 — {file_name}")
            log.info(f'load cancelled by stop: {file_name}')
            return
        self._cancel_play_start_watchdog()
        self._cancel_audio_mix()
        self.player.stop(); self.player.setPosition(0)
        self.meter_ctrl.set_playing(False)

    def _step(self, frames):
        self._set_frame_position(self._display_frame + int(frames))

    def _cue(self):
        # CUE 버튼: Explorer 선택 파일을 player에 올림
        # 이미 같은 파일이 올라와 있으면 IN 포인트로 이동
        sel = None
        if hasattr(self, '_right_panel'):
            sel_items = self._right_panel.exp_list.selectedItems()
            if sel_items:
                sel = sel_items[0].data(Qt.ItemDataRole.UserRole)
        # Explorer 선택 없으면 clip_list fallback
        if not sel:
            ci = self.clip_list.currentItem()
            if ci: sel = ci.data(Qt.ItemDataRole.UserRole)
        if not sel: return

        if sel == self.cur_file:
            # 이미 같은 파일 → IN 포인트로 이동
            if self.in_pt is not None:
                self._set_position(int(self.in_pt * 1000))
        else:
            self.load_file(sel)

    def seek_to(self, sec):
        self._set_position(int(sec*1000))
        if self.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()

    def _on_slider_release(self):
        self._seeking=False
        if self.duration>0:
            self._set_frame_position(int(round(self.slider.value() / 1000 * self._duration_frames())))

    # ── IN / OUT ─────────────────────────────────────────
    def _set_in(self):
        self.in_pt = self._display_frame / self._media_fps()
        self.tc_in_l.setText(
            self._frames_to_tc(self._display_frame, include_offset=self._tc_include_offset())
        )
        self.tc_in_l.setStyleSheet(f"color:{C['yellow']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")

    def _clr_in(self):
        self.in_pt=None; self.tc_in_l.setText("—")
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")

    def _set_out(self):
        self.out_pt = self._display_frame / self._media_fps()
        self.tc_out_l.setText(
            self._frames_to_tc(self._display_frame, include_offset=self._tc_include_offset())
        )
        self.tc_out_l.setStyleSheet(f"color:{C['orange']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")

    def _clr_out(self):
        self.out_pt=None; self.tc_out_l.setText("—")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:16px;background:transparent;")


    # ── 이벤트 ───────────────────────────────────────────
    def _on_pos(self, ms):
        self._raise_vlc_meters()
        sec = ms/1000
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._set_display_position_ms(ms)
        elif abs(self._ms_to_frame(ms) - self._display_frame) > max(4, int(self._media_fps() * 0.25)):
            self._sync_frame_clock(ms)
        # 루프 재생: OUT 포인트 넘으면 IN 으로 복귀
        if self._loop and self.out_pt is not None and sec >= self.out_pt:
            in_ms = int(self.in_pt * 1000) if self.in_pt is not None else 0
            self._set_position(in_ms)

    def _on_dur(self, ms):
        media_duration = ms / 1000
        if self._using_preview and self._source_duration > media_duration:
            self.duration = self._source_duration
        else:
            self.duration = media_duration or self._source_duration
        self.tc_dur.setText(self._frames_to_tc(self._duration_frames(), include_offset=False))

    def _on_state(self, state):
        self._raise_vlc_meters()
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("||" if playing else "▶")
        if self.cur_file:
            changed = False
            for f in self._files:
                is_cur = f.get("filepath") == self.cur_file
                new_playing = bool(playing and is_cur)
                new_cue = bool(is_cur or f.get("cue"))
                if f.get("playing") != new_playing:
                    f["playing"] = new_playing
                    changed = True
                if is_cur and f.get("cue") != new_cue:
                    f["cue"] = new_cue
                    changed = True
            if changed and hasattr(self, '_right_panel'):
                self._right_panel.refresh_explorer()
        # LED 깜빡임 제어
        if playing:
            self._reset_audio_recovery()
            self._frame_clock_active = True
            self._sync_frame_clock(self.player.position())
            self._frame_display_timer.start()
            if not self._audio_recovery_timer.isActive():
                self._audio_recovery_timer.start()
            self._led_timer.start()
            self.player.audio_set_volume(0)
            if getattr(self, '_first_audio_start_after_cue', False):
                self._schedule_gated_audio_mix()
            else:
                self._schedule_audio_mix(delay_ms=60)
            self._arm_play_start_watchdog('state')
        else:
            self._cancel_play_start_watchdog()
            self._frame_clock_active = False
            self._frame_display_timer.stop()
            self._audio_recovery_timer.stop()
            self._set_display_position_ms(self.player.position())
            self._cancel_audio_mix()
            self._led_timer.stop()
            self.led.setStyleSheet(f"color:{C['text3']};font-size:10px;background:transparent;")
            self._led_on = False
        if playing and self.cur_file:
            if not self.meter_ctrl._thread.isRunning():
                ch = self.cur_info.get('channels', 2)
                self.meter_ctrl.start_file(
                    self.cur_file, ch, self.player, (1, 2),
                    self.cur_info.get('audio_stream_count', 0))
        else:
            self.meter_ctrl.set_playing(playing)

    def _on_player_error(self, error, error_string):
        """QMediaPlayer 재생 오류 핸들러"""
        if error == QMediaPlayer.Error.NoError:
            return
        area_map = {
            QMediaPlayer.Error.ResourceError: 'file_access',
            QMediaPlayer.Error.FormatError: 'vlc_playback',
            QMediaPlayer.Error.NetworkError: 'network',
            QMediaPlayer.Error.AccessDeniedError: 'permission',
        }
        area = area_map.get(error, 'vlc_playback')
        detail = error_string or ''
        friendly = friendly_error_text(area, detail, self.cur_file)
        title = friendly.splitlines()[0]
        # UI 상태 복원
        self._led_timer.stop()
        self.led.setStyleSheet(f"color:{C['red']};font-size:10px;background:transparent;")
        self.ai_lbl.setText(f'⚠ {title}')
        self.btn_play.setText('▶')
        # 빈 화면 표시
        self.empty_label.setText(f'⚠ {friendly}')
        self.empty_label.setStyleSheet(
            f"color:{C['red']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:#000;")
        self._empty_proxy.setVisible(True)
        # 로그
        log.error(f'[PLAYER ERROR] {title} | {detail}')

    def _on_media_status(self, status):
        """미디어 로드 상태 추적 — InvalidMedia 별도 처리"""
        S = QMediaPlayer.MediaStatus
        if status == S.InvalidMedia:
            self._on_player_error(
                QMediaPlayer.Error.FormatError,
                f'재생 불가: {Path(self.cur_file).name if self.cur_file else "알 수 없는 파일"}')
        elif status == S.LoadedMedia:
            # 정상 로드 — 빨간 LED 초기화
            self.led.setStyleSheet(
                f"color:{C['text3']};font-size:10px;background:transparent;")
        elif status == S.BufferingMedia:
            self.ai_lbl.setText('버퍼링 중...')
        elif status == S.EndOfMedia:
            # 재생 끝 — LED 끄기
            self._cancel_audio_mix()
            self._led_timer.stop()
            self.led.setStyleSheet(
                f"color:{C['text3']};font-size:10px;background:transparent;")
            self._led_on = False

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.accept()

    def dropEvent(self, e):
        if self._is_busy_loading():
            self.status_changed.emit('  ⏳ 파일 로드 중입니다 — 완료 후 드래그하세요')
            log.info('drop ignored while loading')
            e.ignore()
            return
        for url in e.mimeData().urls():
            fp = url.toLocalFile()
            if Path(fp).suffix.lower() in VIDEO_EXTS:
                self._add_file_to_list(fp)
                self._refresh_clip_list(); self.load_file(fp); break

    def keyPressEvent(self, e):
        k=e.key()
        if self._is_busy_loading():
            guarded = {
                Qt.Key.Key_Space, Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_I, Qt.Key.Key_O,
            }
            if k in guarded:
                self.status_changed.emit('  ⏳ CUE 준비 중입니다 — 잠시만 기다려주세요')
                e.accept()
                return
        # Space: 재생/일시정지 전용
        # 텍스트 입력창, 버튼류 포커스 시 무시 → player만 동작
        focused = QApplication.focusWidget()
        from PyQt6.QtWidgets import QLineEdit, QTextEdit, QAbstractButton, QAbstractSpinBox
        if k==Qt.Key.Key_Space:
            from PyQt6.QtWidgets import QTabBar, QTabWidget, QScrollBar
            # 입력/버튼/탭/스크롤 위젯 포커스 시 Space 무시
            if isinstance(focused, (QLineEdit, QTextEdit, QAbstractButton,
                                    QAbstractSpinBox, QTabBar, QTabWidget,
                                    QScrollBar, QListWidget)):
                e.ignore(); return
            self.toggle_play()
            e.accept(); return
        elif k==Qt.Key.Key_Left:     self._step(-1)
        elif k==Qt.Key.Key_Right:    self._step(1)
        elif k==Qt.Key.Key_Home:     self._set_position(0)
        elif k==Qt.Key.Key_End:      self._set_position(max(0,int(self.duration*1000)-100))
        elif k==Qt.Key.Key_I:        self._set_in()
        elif k==Qt.Key.Key_O:        self._set_out()
        e.ignore()

    # ── AI ───────────────────────────────────────────────
    def start_audio_analyze(self):
        """AI바 뮤트감지 버튼 → 오른쪽 오디오 탭으로 포워드"""
        if not self.cur_file:
            return
        rp = getattr(self, '_right_panel', None)
        if rp and hasattr(rp, '_run_audio_analyze'):
            try:
                if hasattr(rp, 'tabs'):
                    audio_page = rp.mute_list.parentWidget() if hasattr(rp, 'mute_list') else None
                    if audio_page:
                        rp.tabs.setCurrentWidget(audio_page)
                rp._run_audio_analyze()
                return
            except Exception as e:
                log.warning(f'audio analyze forward failed: {e}')
        self.ai_lbl.setText("⚠ 오른쪽 오디오 탭을 사용할 수 없습니다")

    def start_black_detect(self):
        """AI바 블랙 버튼 → 오른쪽 블랙 탭 분석 실행"""
        if not self.cur_file:
            return
        rp = getattr(self, '_right_panel', None)
        if rp and hasattr(rp, '_run_black_detect'):
            try:
                if hasattr(rp, 'tabs'):
                    black_page = rp.black_list.parentWidget() if hasattr(rp, 'black_list') else None
                    if black_page:
                        rp.tabs.setCurrentWidget(black_page)
                rp._run_black_detect()
                return
            except Exception as e:
                log.warning(f'black detect forward failed: {e}')
        self.ai_lbl.setText("⚠ 오른쪽 블랙 탭을 사용할 수 없습니다")

# ══════════════════════════════════════════════════════════
# 오른쪽: 탭 패널
# ══════════════════════════════════════════════════════════
