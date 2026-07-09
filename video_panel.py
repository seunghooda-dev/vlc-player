"""
video_panel.py — 메인 비디오 플레이어 패널
VideoPanel: 재생/타임코드/트랜스코드/IN-OUT/블랙검출/오디오미터
"""
import sys, os, json, hashlib, subprocess, time, math
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
from PyQt6.QtGui   import QColor, QFont, QDragEnterEvent, QDropEvent, QPainter
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem

from constants  import (
    C, FFMPEG, FFPROBE, FFPLAY, VLC_DIR, VIDEO_EXTS, TMP_DIR, BASE_DIR, log,
    register_child_process, terminate_child_process, load_settings, save_settings,
    friendly_error_text, friendly_error_title,
    format_missing_runtime_tools,
    record_state_event,
)
from db_models  import (
    probe, save_clip, frames_to_tc, tc_to_frames,
    load_qc_status, load_clip_metadata_hint, update_clip_qc,
)
from threads    import ProbeThread, TranscodeThread, LoudnessAnalyzeThread
from meters     import SideMeter, LoudnessMeter, MeterController, mk_btn, mk_label, separator

DIRECT_VLC_EXTS = {'.mxf', '.mp4'}


class QCMarkerSlider(QSlider):
    """Progress slider with lightweight QC result overlays."""
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._qc_markers = {"black": [], "mute": [], "freeze": []}
        self._qc_duration = 0.0
        self.setMinimumHeight(18)

    @staticmethod
    def _finite_seconds(value, default=None):
        try:
            seconds = float(value)
            if math.isfinite(seconds):
                return max(0.0, seconds)
        except Exception:
            pass
        return default

    @classmethod
    def _clean_ranges(cls, ranges):
        cleaned = []
        for item in ranges or []:
            if not isinstance(item, dict):
                continue
            start = cls._finite_seconds(item.get("start"))
            if start is None:
                continue
            end = cls._finite_seconds(item.get("end"), start)
            if end < start:
                continue
            row = dict(item)
            row["start"] = start
            row["end"] = end
            cleaned.append(row)
        return cleaned

    def set_qc_markers(self, black_ranges=None, mute_ranges=None, freeze_ranges=None, duration_sec=0.0):
        self._qc_markers = {
            "black": self._clean_ranges(black_ranges),
            "mute": self._clean_ranges(mute_ranges),
            "freeze": self._clean_ranges(freeze_ranges),
        }
        self._qc_duration = self._finite_seconds(duration_sec, 0.0) or 0.0
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.orientation() != Qt.Orientation.Horizontal or self._qc_duration <= 0:
            return
        black = self._qc_markers.get("black") or []
        mute = self._qc_markers.get("mute") or []
        freeze = self._qc_markers.get("freeze") or []
        if not black and not mute and not freeze:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        track_left = 7
        track_width = max(1, self.width() - track_left * 2)
        marker_top = max(1, int(self.height() * 0.12))
        marker_h = max(3, int((self.height() - marker_top * 2 - 2) / 3))

        def _draw_ranges(ranges, color, y):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            for r in ranges:
                start = r.get("start", 0.0)
                end = r.get("end", start)
                start = min(start, self._qc_duration)
                end = min(max(end, start + 0.001), self._qc_duration)
                x1 = track_left + int((start / self._qc_duration) * track_width)
                x2 = track_left + int((end / self._qc_duration) * track_width)
                painter.drawRect(x1, y, max(3, x2 - x1), marker_h)

        _draw_ranges(black, QColor(255, 74, 103, 210), marker_top)
        _draw_ranges(mute, QColor(255, 170, 48, 210), marker_top + marker_h + 1)
        _draw_ranges(freeze, QColor(183, 148, 244, 220), marker_top + (marker_h + 1) * 2)
        painter.end()


class VlcAudioAdapter:
    def __init__(self, player):
        self.player = player

    def setVolume(self, value):
        try:
            self.player.audio_set_volume(int(max(0.0, min(1.0, value)) * 100))
        except Exception as e:
            log.debug(f'vlc volume: {e}')


class AudioMixPlayer(QObject):
    """FFmpeg mixes checked audio channels; ffplay outputs the audio only."""
    def __init__(self):
        super().__init__()
        self.filepath = None
        self.channels = [1, 2]
        self.volume = 0.8
        self.rate = 1.0
        self.audio_stream_count = 0
        self.channel_count = 0
        self.audio_layout_known = False
        self._ffmpeg = None
        self._ffplay = None
        self._playing = False
        self._active_layout_known = False
        self.last_error = ''
        # FFmpeg/ffplay has a small startup/buffer delay after VLC video starts.
        # Seeking the external audio slightly ahead keeps MXF playback closer.
        self.start_lead_sec = 0.12

    @staticmethod
    def _safe_int(value, default=0):
        try:
            parsed = float(value)
            if math.isfinite(parsed):
                return int(parsed)
        except Exception:
            pass
        return default

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else default
        except Exception:
            return default

    def set_file(self, filepath, audio_stream_count=0, channel_count=2):
        self.filepath = filepath
        self.audio_stream_count = max(0, self._safe_int(audio_stream_count, 0))
        self.channel_count = max(0, self._safe_int(channel_count, 0))
        self.audio_layout_known = self.audio_stream_count > 0 or self.channel_count > 0

    def set_channels(self, channels):
        cleaned = []
        for ch in channels or [1, 2]:
            n = self._safe_int(ch, 0)
            if 1 <= n <= 8 and n not in cleaned:
                cleaned.append(n)
        self.channels = cleaned or [1, 2]

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, self._safe_float(value, self.volume)))

    def set_rate(self, rate):
        self.rate = max(0.5, min(2.0, self._safe_float(rate, 1.0)))

    def stop(self):
        was_active = bool(self._playing or self._ffplay or self._ffmpeg)
        if was_active:
            self.log_diagnostic('audio child stopping')
            record_state_event('audio-mix', 'stopping', file=Path(self.filepath or '').name, channels=self.channels)
        started = time.monotonic()
        self._playing = False
        for proc, label in ((self._ffplay, 'audio mix ffplay'), (self._ffmpeg, 'audio mix ffmpeg')):
            terminate_child_process(proc, label, timeout=0.18)
        self._ffplay = None
        self._ffmpeg = None
        self._active_layout_known = False
        if was_active:
            elapsed = time.monotonic() - started
            if elapsed > 0.45:
                log.warning(f'audio child stop took {elapsed:.3f}s')
            else:
                log.info(f'audio child stopped in {elapsed:.3f}s')
            record_state_event('audio-mix', 'stopped', elapsed=f'{elapsed:.3f}s')

    def _proc_state(self, proc):
        if proc is None:
            return 'missing'
        try:
            rc = proc.poll()
        except Exception as e:
            log.debug(f'audio child poll failed: {e}')
            return 'unknown'
        return 'running' if rc is None else f'exited({rc})'

    def process_status(self):
        return {
            'playing': bool(self._playing),
            'ffmpeg': self._proc_state(self._ffmpeg),
            'ffplay': self._proc_state(self._ffplay),
        }

    def diagnostic_status(self):
        status = self.process_status()
        status.update({
            'ffmpeg_pid': getattr(self._ffmpeg, 'pid', None),
            'ffplay_pid': getattr(self._ffplay, 'pid', None),
            'file': self.filepath,
            'channels': list(self.channels or []),
            'rate': round(self._safe_float(self.rate, 1.0), 3),
            'volume_percent': int(round(self._safe_float(self.volume, 0.0) * 100)),
            'audio_stream_count': max(0, self._safe_int(self.audio_stream_count, 0)),
            'channel_count': max(0, self._safe_int(self.channel_count, 0)),
            'layout_known': bool(self.audio_layout_known),
            'active_layout_known': bool(self._active_layout_known),
            'last_error': self.last_error,
        })
        return status

    def log_diagnostic(self, prefix='audio child status'):
        status = self.diagnostic_status()
        file_name = Path(status.get('file') or '').name or '-'
        log.info(
            f"{prefix}: "
            f"playing={status.get('playing')} "
            f"ffmpeg={status.get('ffmpeg')} pid={status.get('ffmpeg_pid') or '-'} "
            f"ffplay={status.get('ffplay')} pid={status.get('ffplay_pid') or '-'} "
            f"ch={status.get('channels') or '-'} rate={status.get('rate')} "
            f"volume={status.get('volume_percent')}% "
            f"layout={status.get('layout_known')}/{status.get('active_layout_known')} "
            f"file={file_name}"
        )
        if status.get('last_error'):
            log.warning(f"{prefix} last error: {status.get('last_error')}")

    def is_running(self):
        status = self.process_status()
        return (
            status.get('playing')
            and status.get('ffmpeg') == 'running'
            and status.get('ffplay') == 'running'
        )

    def active_layout_known(self):
        return bool(self.is_running() and self._active_layout_known)

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
        lead = self.start_lead_sec if lead_sec is None else max(0.0, self._safe_float(lead_sec, 0.0))
        start_sec = max(0.0, self._safe_float(pos_sec, 0.0) + lead)
        ffmpeg_cmd = [
            FFMPEG, '-hide_banner', '-loglevel', 'error',
            '-ss', f'{start_sec:.3f}',
            '-i', self.filepath,
            '-vn',
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
            '-ar', '48000',
            '-ac', '2',
            'pipe:1',
        ]
        if self.audio_layout_known:
            fc = self._build_filter()
            ffmpeg_cmd[8:8] = ['-filter_complex', fc, '-map', '[aout]']
        else:
            # Full metadata can be delayed or fail on some MXF files.
            # For play-start sync, output the first available audio stream first;
            # accurate checked-channel routing is restored once metadata arrives.
            ffmpeg_cmd[8:8] = ['-map', '0:a:0?']
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
            '-volume', str(max(0, min(100, self._safe_int(self._safe_float(self.volume, 0.8) * 100, 80)))),
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
            self._active_layout_known = bool(self.audio_layout_known)
            log.info(
                'audio mix started '
                f'ffmpeg={self._ffmpeg.pid} ffplay={self._ffplay.pid} '
                f'ch={self.channels} start={start_sec:.3f}s rate={self.rate:.3f} '
                f'layout_known={self.audio_layout_known}'
            )
            record_state_event(
                'audio-mix',
                'started',
                file=Path(self.filepath or '').name,
                ffmpeg=self._ffmpeg.pid,
                ffplay=self._ffplay.pid,
                channels=self.channels,
                start=f'{start_sec:.3f}s',
            )
            self.log_diagnostic()
        except Exception as e:
            self.last_error = friendly_error_text('audio_mix', e, self.filepath)
            log.error(f'audio mix start failed: {e}')
            self.stop()
            return False
        return True

    def _source_for_channel(self, ch, idx):
        ch = max(1, min(8, self._safe_int(ch, 1)))
        if self.audio_stream_count > 1:
            return f'0:a:{ch - 1}', ''
        label = f'mono{idx}'
        return label, f'[0:a]pan=mono|c0=c{ch - 1}[{label}]'

    def _tail_filters(self):
        filters = []
        rate = max(0.5, min(2.0, self._safe_float(self.rate, 1.0)))
        if abs(rate - 1.0) > 0.001:
            filters.append(f'atempo={rate:.3f}')
        return ','.join(filters) if filters else 'anull'

    def _build_filter(self):
        channels = []
        for ch in self.channels or [1, 2]:
            n = max(1, min(8, self._safe_int(ch, 0)))
            if n not in channels:
                channels.append(n)
        channels = channels or [1, 2]
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
        self._timer.setInterval(33)
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
        try:
            self._player.set_pause(1)
        except Exception:
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

        def _freeze(label='freeze'):
            if not self._is_current_op(seq):
                return
            try:
                self._player.set_time(target)
                self._player.set_pause(1)
            except Exception as e:
                log.debug(f'vlc preroll {label}: {e}')
            self._state = QMediaPlayer.PlaybackState.PausedState
            self.positionChanged.emit(target)
            self.playbackStateChanged.emit(self._state)
            self._emit_duration(seq)

        QTimer.singleShot(120, lambda: _freeze('freeze-1'))
        QTimer.singleShot(260, lambda: _freeze('freeze-2'))
        QTimer.singleShot(520, lambda: _freeze('freeze-3'))
        QTimer.singleShot(860, lambda: _freeze('freeze-4'))

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
            parsed = float(rate)
            if not math.isfinite(parsed):
                parsed = 1.0
            self._player.set_rate(max(0.5, min(2.0, parsed)))
        except Exception as e:
            log.debug(f'vlc set rate: {e}')

    def audio_set_volume(self, value):
        self._player.audio_set_volume(value)

    def set_audio_channel(self, channel_no):
        try:
            parsed = float(channel_no)
            if not math.isfinite(parsed):
                parsed = 1
            self._selected_audio_channel = max(1, min(8, int(parsed)))
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
        self._last_display_dur_frames = None
        self._last_slider_value = None
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
        self._metadata_probe_timer_seq = 0
        self._pending_metadata_probe = None
        self._load_seq = 0
        self._metadata_ready = False
        self._cue_ready = False
        self._file_loaded_emitted = False
        self._loudness_thread = None
        self._loudness_cache = {}
        self._loudness_cache_order = []
        self._loudness_cache_limit = 32
        self._loudness_seq = 0
        self._dead_threads = []   # abort된 스레드 보관 (GC 소멸 방지)
        self._dead_threads_limit = 16
        self._dead_threads_limit_logged = False
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
        self._last_meter_raise_at = 0.0
        self.setAcceptDrops(True)
        self._frame_display_timer = QTimer(self)
        self._frame_display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_display_timer.setInterval(16)
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

    def _next_load_seq(self, reason='', filepath=None):
        self._load_seq += 1
        if reason:
            name = Path(filepath).name if filepath else '-'
            log.debug(f'load seq advanced: seq={self._load_seq} reason={reason} file={name}')
            record_state_event('load-seq', reason, seq=self._load_seq, file=name)
        return self._load_seq

    def _load_is_current(self, seq, filepath=None):
        if seq is not None and seq != self._load_seq:
            return False
        if filepath and filepath != self.cur_file:
            return False
        return True

    def _path_access_hint(self, filepath):
        try:
            text = str(filepath or '')
            p = Path(text)
            if text.startswith('\\\\'):
                return '네트워크/NAS 경로입니다. 연결 상태, 공유 권한, 파일 잠금 여부를 확인하세요.'
            drive = p.drive
            if drive and os.name == 'nt':
                root = Path(drive + '\\')
                if not root.exists():
                    return f'{drive} 드라이브가 연결되어 있지 않습니다. 외장하드/네트워크 드라이브 연결을 확인하세요.'
            if drive and drive.upper() not in ('C:', 'D:'):
                return '외장하드 또는 네트워크 드라이브일 수 있습니다. 케이블/마운트/권한 상태를 확인하세요.'
        except Exception:
            pass
        return '파일이 이동/삭제됐거나 다른 프로그램이 잠그고 있지 않은지 확인하세요.'

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(0)

        # INFO BAR
        ib = QWidget(); ib.setFixedHeight(30)
        ib.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #090b10,stop:0.5 #11151d,stop:1 #090b10);"
            f"border-bottom:1px solid {C['border']};"
        )
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
        self.empty_label = QLabel("▶\n\nMXF / MP4 파일을 열어주세요\n\n⏏ 파일을 드래그하거나 CUE 버튼을 누르세요")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color:{C['text2']};font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';"
            "font-size:14px;font-weight:500;background:#000;")
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
        self._playback_rate = max(0.5, min(2.0, self._safe_float_value(self._settings.get('playback_rate', 1.0), 1.0)))
        self._audio_mix_seq = 0
        self._audio_recovery_timer = QTimer(self)
        self._audio_recovery_timer.setInterval(900)
        self._audio_recovery_timer.timeout.connect(self._check_audio_mix_recovery)
        self._playback_progress_timer = QTimer(self)
        self._playback_progress_timer.setInterval(1000)
        self._playback_progress_timer.timeout.connect(self._check_playback_progress)
        self._playback_progress_last_ms = 0
        self._playback_progress_last_frame = 0
        self._playback_progress_started_at = 0.0
        self._playback_progress_stall_ticks = 0
        self._playback_progress_last_warn = 0.0

        # MEDIA PLAYER
        self.player = VlcPlayerAdapter(self.video_view.viewport())
        self.player.audio_set_volume(0)
        self.player.setPlaybackRate(self._playback_rate)
        volume = max(0, min(100, self._safe_int_value(self._settings.get('volume', 80), 80)))
        self.audio_mix.set_volume(volume / 100.0)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        # TIMECODE DISPLAY
        tc_w = QWidget(); tc_w.setFixedHeight(88)
        tc_w.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #0d1017,stop:1 #080a0f);"
            f"border-top:1px solid {C['border']};border-bottom:1px solid {C['border']};"
        )
        tcl = QHBoxLayout(tc_w); tcl.setContentsMargins(16,6,16,6); tcl.setSpacing(0)
        TC_META_W = 220
        tc_balance = QWidget()
        tc_balance.setFixedWidth(TC_META_W)
        tc_balance.setStyleSheet("background:transparent;")
        tcl.addWidget(tc_balance)

        self.tc_main = QLabel('00:00:00;00')
        self.tc_main.setStyleSheet(f"color:{C['yellow']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:39px;font-weight:600;background:transparent;")
        self.tc_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tc_main.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tcl.addWidget(self.tc_main, 1)

        tc_meta = QFrame()
        tc_meta.setFixedWidth(TC_META_W)
        tc_meta.setStyleSheet("QFrame{background:transparent;border-left:1px solid #202633;}")
        meta_l = QHBoxLayout(tc_meta)
        meta_l.setContentsMargins(14,0,0,0)
        meta_l.setSpacing(0)
        sg = QGridLayout(); sg.setSpacing(1); sg.setContentsMargins(0,0,0,0)
        sg.setColumnMinimumWidth(0, 32); sg.setColumnMinimumWidth(1, 112)
        self.tc_dur  = QLabel('——:——:——;——')
        self.tc_rem  = QLabel('——:——:——;——')
        self.tc_in_l = QLabel('——:——:——;——')
        self.tc_out_l= QLabel('——:——:——;——')
        tc_side_colors = {
            'DUR': '#4B8DFF',  # dark fluorescent blue
            'REM': '#D85B9F',  # dark fluorescent pink
            'IN': C['teal'],
            'OUT': C['orange'],
        }
        for row,(k,v,c) in enumerate([
            ('DUR',  self.tc_dur,   tc_side_colors['DUR']),
            ('REM',  self.tc_rem,   tc_side_colors['REM']),
            ('IN',   self.tc_in_l,  tc_side_colors['IN']),
            ('OUT',  self.tc_out_l, tc_side_colors['OUT']),
        ]):
            kl = mk_label(k, c if k in ('DUR', 'REM') else C['text3'], 'Consolas', 10, bold=True); kl.setFixedWidth(32)
            v.setFixedWidth(112)
            v.setStyleSheet(f"color:{c};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sg.addWidget(kl, row, 0); sg.addWidget(v, row, 1)
        meta_l.addLayout(sg)
        tcl.addWidget(tc_meta)
        layout.addWidget(tc_w)

        # PROGRESS SLIDER
        pw = QWidget(); pw.setFixedHeight(18)
        pw.setStyleSheet("background:#090b10;")
        pbl = QHBoxLayout(pw); pbl.setContentsMargins(0,0,0,0)
        self.slider = QCMarkerSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0,1000)
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal{height:3px;background:#202634;border-radius:2px;}"
            f"QSlider::sub-page:horizontal{{background:qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 {C['teal']});border-radius:2px;}}"
            f"QSlider::handle:horizontal{{width:14px;height:14px;margin:-6px 0;background:{C['text0']};"
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
        tr = QWidget(); tr.setFixedHeight(70)
        tr.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #171a22,stop:1 #111319);"
            f"border-bottom:1px solid {C['border']};"
        )
        trl = QHBoxLayout(tr); trl.setContentsMargins(10,7,10,7); trl.setSpacing(8)

        BTN_W  = 50
        BTN_H  = 48
        PLAY_W = 76

        TR_BASE = (
            "QPushButton{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #283247,stop:0.56 #1B2332,stop:1 #101620);"
            f"color:{C['text1']};"
            "border:1px solid #334159;"
            "border-radius:7px;"
            "font-family:'Segoe UI Variable Text','Segoe UI','Malgun Gothic';"
            "font-size:13px;"
            "font-weight:700;"
            "padding:0;"
            f"min-width:{BTN_W}px;"
            "}"
            f"QPushButton:hover{{background:#33405A;color:{C['text0']};border-color:{C['blue']};}}"
            "QPushButton:pressed{background:#0B1018;padding-top:1px;border-color:#8ec4ff;}"
            "QPushButton:disabled{background:#11141a;color:#3f4555;border-color:#1d222d;}"
        )
        TR_COMPACT = TR_BASE + "QPushButton{font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;}"
        TR_JUMP = TR_BASE + f"QPushButton{{color:{C['text0']};font-size:14px;}}"
        TR_STOP = (
            TR_BASE
            + f"QPushButton{{color:{C['text0']};font-family:'Segoe UI Symbol','Segoe UI';font-size:24px;border-color:#3a4050;}}"
            + "QPushButton:hover{background:#252a36;border-color:#697184;}"
        )
        TR_PLAY = (
            "QPushButton{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #70C1FF,stop:0.48 #2D8CFF,stop:1 #155EA8);"
            f"color:{C['text0']};"
            f"border:1px solid {C['blue']};"
            "border-radius:7px;"
            "font-family:'Segoe UI Symbol','Segoe UI Variable Text','Segoe UI';"
            "font-size:22px;"
            "font-weight:700;"
            "padding:0 1px 1px 0;"
            f"min-width:{PLAY_W}px;"
            "}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #7AC8FF,stop:1 #2976D2);border-color:#c0e1ff;}"
            "QPushButton:pressed{background:#173153;padding-top:1px;border-color:#b5d9ff;}"
            "QPushButton:disabled{background:#141821;color:#4b5365;border-color:#252b37;}"
        )
        POD_STYLE = (
            "QFrame#transportPod{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,255,255,16),stop:1 rgba(0,0,0,60));"
            "border:1px solid #2D374A;"
            "border-radius:8px;"
            "}"
        )
        VOL_POD_STYLE = (
            "QFrame#volumePod{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #182236,stop:1 #0B1018);"
            "border:1px solid #334159;"
            "border-radius:8px;"
            "}"
        )

        def transport_pod(widgets, spacing=4, margins=(4, 4, 4, 4)):
            pod = QFrame()
            pod.setObjectName("transportPod")
            pod.setFixedHeight(BTN_H + 8)
            pod.setStyleSheet(POD_STYLE)
            pod_l = QHBoxLayout(pod)
            pod_l.setContentsMargins(*margins)
            pod_l.setSpacing(spacing)
            for widget in widgets:
                pod_l.addWidget(widget)
            return pod

        # EJECT
        self.btn_folder = QPushButton("EJECT")
        self.btn_folder.setFixedSize(70, BTN_H)
        self.btn_folder.setToolTip("EJECT - 현재 파일을 화면에서 내립니다")
        self.btn_folder.setStyleSheet(TR_BASE + "QPushButton{font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;}")

        # 방송 장비 느낌의 간결한 transport 심볼
        self.btn_m1  = QPushButton("-1F");   self.btn_m1.setFixedSize(BTN_W, BTN_H); self.btn_m1.setToolTip("-1 프레임  (← 방향키)")
        self.btn_gos = QPushButton("|<");    self.btn_gos.setFixedSize(BTN_W, BTN_H); self.btn_gos.setToolTip("처음으로  (Home)")
        self.btn_rew = QPushButton("<<");    self.btn_rew.setFixedSize(BTN_W, BTN_H); self.btn_rew.setToolTip("10초 뒤로")
        self.btn_play= QPushButton("▶");     self.btn_play.setFixedSize(PLAY_W, BTN_H); self.btn_play.setToolTip("재생 / 일시정지  (Space)")
        self.btn_stop= QPushButton("■");     self.btn_stop.setFixedSize(BTN_W, BTN_H); self.btn_stop.setToolTip("정지")
        self.btn_fwd = QPushButton(">>");    self.btn_fwd.setFixedSize(BTN_W, BTN_H); self.btn_fwd.setToolTip("10초 앞으로")
        self.btn_goe = QPushButton(">|");    self.btn_goe.setFixedSize(BTN_W, BTN_H); self.btn_goe.setToolTip("끝으로  (End)")
        self.btn_p1  = QPushButton("+1F");   self.btn_p1.setFixedSize(BTN_W, BTN_H); self.btn_p1.setToolTip("+1 프레임  (→ 방향키)")

        for b in [self.btn_folder, self.btn_m1, self.btn_gos, self.btn_rew,
                  self.btn_play, self.btn_stop, self.btn_fwd, self.btn_goe,
                  self.btn_p1]:
            b.setCursor(Qt.CursorShape.PointingHandCursor)

        for b in [self.btn_m1,self.btn_gos,self.btn_rew,self.btn_fwd,self.btn_goe,self.btn_p1]:
            b.setStyleSheet(TR_COMPACT)

        self.btn_gos.setStyleSheet(TR_JUMP)
        self.btn_goe.setStyleSheet(TR_JUMP)
        self.btn_stop.setStyleSheet(TR_STOP)
        self.btn_play.setStyleSheet(TR_PLAY)

        self.btn_cue = QPushButton('CUE')
        self.btn_cue.setFixedHeight(BTN_H)
        self.btn_cue.setToolTip('CUE\n선택한 파일을 플레이어에 올립니다\n이미 로드된 파일이면 IN 포인트로 이동합니다')
        self.btn_cue.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(255,209,102,42),stop:1 rgba(255,209,102,18));color:{C['yellow']};border:1px solid rgba(255,209,102,95);"
            "border-radius:8px;font-family:'Cascadia Mono','Consolas','D2Coding';font-weight:700;font-size:14px;"
            "padding:0 22px;}"
            f"QPushButton:hover{{background:rgba(255,209,102,45);border-color:{C['yellow']};color:#ffffff;}}"
            "QPushButton:pressed{padding-top:1px;background:#181818;}"
        )
        self.btn_cue.setCursor(Qt.CursorShape.PointingHandCursor)

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

        # 볼륨 슬라이더
        vol_lbl = QLabel('VOL')
        vol_lbl.setFixedWidth(28)
        vol_lbl.setStyleSheet(
            f"color:{C['text2']};font-family:'JetBrains Mono','Cascadia Mono','Consolas','D2Coding';"
            "font-size:10px;font-weight:800;background:transparent;"
        )
        vol_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        volume = max(0, min(100, self._safe_int_value(self._settings.get('volume', 80), 80)))
        self.vol_slider.setValue(volume)
        self.vol_slider.setFixedWidth(122)
        self.vol_slider.setFixedHeight(26)
        self.vol_slider.setToolTip('볼륨 조절 (0~100%)')
        self.vol_slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#202838;border-radius:2px;}"
            f"QSlider::sub-page:horizontal{{background:qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 {C['teal']});border-radius:2px;}}"
            'QSlider::handle:horizontal{width:14px;height:14px;margin:-6px 0;'
            f"background:#f5f8ff;border:1px solid rgba(90,167,255,170);border-radius:7px;}}"
            'QSlider::handle:horizontal:hover{background:#ffffff;border-color:#c0e1ff;}'
        )
        self.vol_pct = QLabel(f'{volume}%')
        self.vol_pct.setFixedSize(44, 28)
        self.vol_pct.setStyleSheet(
            f"color:{C['text0']};font-family:'JetBrains Mono','Cascadia Mono','Consolas','D2Coding';"
            "font-size:10px;font-weight:800;"
            "background:rgba(90,167,255,18);border:1px solid #34435A;border-radius:7px;"
        )
        self.vol_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        def _on_vol(v):
            self.player.audio_set_volume(0)
            self.audio_mix.set_volume(v / 100.0)
            if self.cur_file and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._schedule_audio_mix(delay_ms=350, restart=True, lead_sec=0.0)
            self.vol_pct.setText(f'{v}%')
            self._settings = save_settings(volume=int(v))
        self.vol_slider.valueChanged.connect(_on_vol)

        vol_pod = QFrame()
        vol_pod.setObjectName("volumePod")
        vol_pod.setFixedHeight(BTN_H + 8)
        vol_pod.setStyleSheet(VOL_POD_STYLE)
        vol_pod_l = QHBoxLayout(vol_pod)
        vol_pod_l.setContentsMargins(10,4,10,4)
        vol_pod_l.setSpacing(8)
        vol_pod_l.addWidget(vol_lbl)
        vol_pod_l.addWidget(self.vol_slider)
        vol_pod_l.addWidget(self.vol_pct)

        left_col = QWidget()
        left_col.setMinimumWidth(342)
        left_col_l = QHBoxLayout(left_col)
        left_col_l.setContentsMargins(0,0,0,0)
        left_col_l.setSpacing(0)
        left_col_l.addWidget(transport_pod([self.btn_folder]))
        left_col_l.addStretch()

        center_col = QWidget()
        center_col.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        center_l = QHBoxLayout(center_col)
        center_l.setContentsMargins(0,0,0,0)
        center_l.setSpacing(8)
        center_l.addWidget(transport_pod([self.btn_m1, self.btn_gos, self.btn_rew]))
        center_l.addWidget(transport_pod([self.btn_play, self.btn_stop], spacing=5))
        center_l.addWidget(transport_pod([self.btn_fwd, self.btn_goe, self.btn_p1]))

        right_col = QWidget()
        right_col.setMinimumWidth(342)
        right_col_l = QHBoxLayout(right_col)
        right_col_l.setContentsMargins(0,0,0,0)
        right_col_l.setSpacing(8)
        right_col_l.addStretch()
        right_col_l.addWidget(vol_pod)
        right_col_l.addWidget(transport_pod([self.btn_cue], margins=(4, 4, 4, 4)))

        trl.addWidget(left_col, 1)
        trl.addWidget(center_col, 0, Qt.AlignmentFlag.AlignCenter)
        trl.addWidget(right_col, 1)
        layout.addWidget(tr)

        # AUDIO CHANNEL SELECT BAR
        ch_bar = QWidget(); ch_bar.setFixedHeight(34)
        ch_bar.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #0d1017,stop:1 #090b10);"
            f"border-bottom:1px solid {C['border']};"
        )
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
            f"QCheckBox::indicator:checked{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {C['teal']},stop:1 {C['blue']});border-color:{C['teal']};}}"
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
        ai.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #141821,stop:1 #10131a);"
            f"border-bottom:1px solid {C['border']};"
        )
        ail = QHBoxLayout(ai); ail.setContentsMargins(10,6,10,6); ail.setSpacing(6)

        def _ai_btn(label, tooltip):
            b = QPushButton(label); b.setFixedHeight(30); b.setEnabled(False)
            b.setToolTip(tooltip)
            b.setStyleSheet(
                "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #222734,stop:1 #171b24);"
                f"color:{C['text1']};border:1px solid {C['border']};"
                "border-radius:6px;font-size:11px;font-weight:600;padding:0 12px;}"
                f"QPushButton:hover{{background:#2a3142;color:{C['text0']};border-color:{C['blue']};}}"
                f"QPushButton:enabled{{color:{C['text1']};}}"
                f"QPushButton:disabled{{color:{C['text3']};border-color:#1c2029;background:#101218;}}"
            )
            return b

        self.btn_black = _ai_btn('⬛  블랙', '1프레임 이상 검정 화면 구간 검출')
        self.btn_audio = _ai_btn('🔇  뮤트', '1초 이상 무음 구간 수동 검출 + 피크 측정')
        self.btn_freeze = _ai_btn('⏸  프리즈', '1초 이상 정지 화면 구간 수동 검출')

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
        self.btn_freeze.clicked.connect(self.start_freeze_detect)
        ail.addWidget(self.btn_black); ail.addWidget(self.btn_audio); ail.addWidget(self.btn_freeze)
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

    def _raise_vlc_meters(self, force=False):
        if not force:
            now = time.perf_counter()
            if now - getattr(self, '_last_meter_raise_at', 0.0) < 0.25:
                return
            self._last_meter_raise_at = now
        else:
            self._last_meter_raise_at = time.perf_counter()
        self.video_overlay.raise_()
        for w in (self.vlc_side_left, self.vlc_side_right, self.vlc_loud_meter):
            w.show()
            w.raise_()

    # ── 프레임 정확 표시 ─────────────────────────────────
    def _media_fps(self):
        try:
            fps = float(self.fps or 29.97)
            if not math.isfinite(fps):
                fps = 29.97
        except Exception:
            fps = 29.97
        return max(1.0, fps)

    @staticmethod
    def _safe_float_value(value, default=0.0):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else default
        except Exception:
            return default

    @staticmethod
    def _safe_int_value(value, default=0):
        try:
            parsed = float(value)
            if math.isfinite(parsed):
                return int(parsed)
        except Exception:
            pass
        return default

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
        duration = self._safe_float_value(getattr(self, 'duration', 0.0), 0.0)
        if duration <= 0:
            return 0
        return max(0, int(round(duration * self._media_fps())))

    def _sec_to_frame(self, sec):
        sec = max(0.0, self._safe_float_value(sec, 0.0))
        return max(0, int(round(sec * self._media_fps())))

    def _ms_to_frame(self, ms):
        return self._sec_to_frame(max(0, self._safe_int_value(ms, 0)) / 1000.0)

    def _frame_to_ms(self, frame):
        frame = max(0, self._safe_int_value(frame, 0))
        return int(round(frame / self._media_fps() * 1000))

    def _tc_include_offset(self):
        return False

    def _parse_tc_offset_frames(self, tc):
        if tc:
            return tc_to_frames(tc, self._media_fps(), self._drop_frame_enabled())
        return int(round(self._safe_float_value(self.tc_offset, 0.0) * self._media_fps()))

    def _frames_to_tc(self, frame, include_offset=False):
        offset = getattr(self, '_tc_offset_frames', 0) if include_offset else 0
        return frames_to_tc(frame, self._media_fps(), self._drop_frame_enabled(), offset)

    def _frame_timer_interval_ms(self):
        # 타임코드는 실제 프레임 변화보다 조금 빠르게만 폴링한다.
        # 같은 프레임을 여러 번 다시 그리면 큰 TC 라벨에서 끊김이 생긴다.
        fps = self._media_fps()
        return max(8, min(33, int(round(1000 / max(1.0, fps * 2)))))

    def _sync_frame_timer_interval(self):
        interval = self._frame_timer_interval_ms()
        if self._frame_display_timer.interval() != interval:
            self._frame_display_timer.setInterval(interval)

    def _set_display_frame(self, frame, update_slider=True):
        dur_frames = self._duration_frames()
        if dur_frames > 0:
            frame = max(0, min(dur_frames, int(frame)))
        else:
            frame = max(0, int(frame))
        dur_changed = dur_frames != getattr(self, '_last_display_dur_frames', None)
        frame_changed = frame != self._display_frame
        if not frame_changed and not dur_changed:
            return
        self._display_frame = frame
        self._last_display_dur_frames = dur_frames
        main_tc = self._frames_to_tc(frame, include_offset=self._tc_include_offset())
        if self.tc_main.text() != main_tc:
            self.tc_main.setText(main_tc)
        rem_frames = max(0, dur_frames - frame)
        rem_tc = self._frames_to_tc(rem_frames, include_offset=False)
        if self.tc_rem.text() != rem_tc:
            self.tc_rem.setText(rem_tc)
        duration = self._safe_float_value(getattr(self, 'duration', 0.0), 0.0)
        if update_slider and duration > 0 and not self._seeking:
            pos_sec = frame / self._media_fps()
            slider_value = max(0, min(1000, int(pos_sec / duration * 1000)))
            if slider_value != getattr(self, '_last_slider_value', None):
                self._last_slider_value = slider_value
                self.slider.setValue(slider_value)

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
        rate = max(0.1, self._safe_float_value(getattr(self, '_playback_rate', 1.0), 1.0))
        frame = self._clock_anchor_frame + int(elapsed * self._media_fps() * rate)
        if frame == self._display_frame:
            return
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
        qc = load_qc_status(filepath)
        try:
            size = p.stat().st_size
        except OSError as e:
            size = 0
            log.warning(f'file size unavailable for list record: {p.name} | {e}')
        return {
            "name": p.name,
            "filepath": filepath,
            "size": size,
            "ext": p.suffix.upper().lstrip("."),
            "cue": False,
            "playing": False,
            "black": qc.get("black") or None,   # None | ok | found | error
            "mute": qc.get("mute") or None,     # None | ok | found | error
            "freeze": qc.get("freeze") or None, # None | ok | found | error
            "black_count": max(0, self._safe_int_value(qc.get("black_count", 0), 0)),
            "mute_count": max(0, self._safe_int_value(qc.get("mute_count", 0), 0)),
            "freeze_count": max(0, self._safe_int_value(qc.get("freeze_count", 0), 0)),
            "black_ranges": list(qc.get("black_ranges") or []),
            "mute_ranges": list(qc.get("mute_ranges") or []),
            "freeze_ranges": list(qc.get("freeze_ranges") or []),
            "qc_summary": qc.get("summary") or "미분석",
            "qc_updated_at": qc.get("updated_at"),
            "analysis": None,
        }

    def _file_entry(self, filepath):
        for item in self._files:
            if item.get("filepath") == filepath:
                item.setdefault("cue", False)
                item.setdefault("playing", False)
                item.setdefault("black", None)
                item.setdefault("mute", None)
                item.setdefault("freeze", None)
                item.setdefault("black_count", 0)
                item.setdefault("mute_count", 0)
                item.setdefault("freeze_count", 0)
                item.setdefault("black_ranges", [])
                item.setdefault("mute_ranges", [])
                item.setdefault("freeze_ranges", [])
                item.setdefault("qc_summary", "미분석")
                item.setdefault("qc_updated_at", None)
                item.setdefault("analysis", None)
                return item
        return None

    def _apply_qc_markers(self):
        if not hasattr(self, "slider"):
            return
        if not self.cur_file:
            self.slider.set_qc_markers([], [], [], 0.0)
            return
        entry = self._file_entry(self.cur_file)
        duration = self.duration or self._source_duration or 0.0
        self.slider.set_qc_markers(
            (entry or {}).get("black_ranges") or [],
            (entry or {}).get("mute_ranges") or [],
            (entry or {}).get("freeze_ranges") or [],
            duration,
        )

    def _set_file_status(self, filepath, **changes):
        entry = self._file_entry(filepath)
        if not entry:
            return
        entry.update(changes)
        qc_keys = {
            "black", "mute", "freeze",
            "black_count", "mute_count", "freeze_count",
            "black_ranges", "mute_ranges", "freeze_ranges",
        }
        if qc_keys.intersection(changes):
            try:
                saved = update_clip_qc(
                    filepath,
                    black=changes.get("black") if "black" in changes else None,
                    mute=changes.get("mute") if "mute" in changes else None,
                    freeze=changes.get("freeze") if "freeze" in changes else None,
                    black_count=changes.get("black_count") if "black_count" in changes else None,
                    mute_count=changes.get("mute_count") if "mute_count" in changes else None,
                    freeze_count=changes.get("freeze_count") if "freeze_count" in changes else None,
                    black_ranges=changes.get("black_ranges") if "black_ranges" in changes else None,
                    mute_ranges=changes.get("mute_ranges") if "mute_ranges" in changes else None,
                    freeze_ranges=changes.get("freeze_ranges") if "freeze_ranges" in changes else None,
                )
                if saved:
                    entry["black"] = saved.get("black") or None
                    entry["mute"] = saved.get("mute") or None
                    entry["freeze"] = saved.get("freeze") or None
                    entry["black_count"] = max(0, self._safe_int_value(saved.get("black_count", 0), 0))
                    entry["mute_count"] = max(0, self._safe_int_value(saved.get("mute_count", 0), 0))
                    entry["freeze_count"] = max(0, self._safe_int_value(saved.get("freeze_count", 0), 0))
                    entry["black_ranges"] = list(saved.get("black_ranges") or [])
                    entry["mute_ranges"] = list(saved.get("mute_ranges") or [])
                    entry["freeze_ranges"] = list(saved.get("freeze_ranges") or [])
                    entry["qc_summary"] = saved.get("summary") or "미분석"
                    entry["qc_updated_at"] = saved.get("updated_at")
                    log.info(
                        "qc status saved "
                        f"file={Path(filepath).name} summary={entry['qc_summary']} "
                        f"black={entry['black']}({entry['black_count']}) "
                        f"mute={entry['mute']}({entry['mute_count']}) "
                        f"freeze={entry['freeze']}({entry['freeze_count']})"
                    )
                    record_state_event(
                        "qc",
                        "status saved",
                        file=Path(filepath).name,
                        summary=entry["qc_summary"],
                        black=entry["black"],
                        mute=entry["mute"],
                        freeze=entry["freeze"],
                    )
            except Exception as e:
                log.warning(f"qc status save failed file={Path(filepath).name}: {e}")
        if hasattr(self, '_right_panel'):
            self._right_panel.refresh_explorer()
        if filepath and self._same_path(filepath, self.cur_file):
            self._apply_qc_markers()

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
        self._last_display_dur_frames = None
        self._last_slider_value = None
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
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")

        # 슬라이더 초기화
        self.slider.setValue(0)
        self._apply_qc_markers()

        # 재생버튼 초기화
        self.btn_play.setText("▶")

        # 메타 정보 초기화
        self.lbl_fmt.setText("—"); self.lbl_cod.setText("—")
        self.lbl_res.setText("—"); self.lbl_fps.setText("—"); self.lbl_ch.setText("—")
        self._res_text.setPlainText("")

        # 화면 초기화
        self._video_item.hide()
        self.empty_label.setText("▶\n\nMXF / MP4 파일을 열어주세요\n\n파일 추가 버튼 또는 파일 드래그로 불러오세요")
        self._empty_proxy.show()

        # AI 버튼 비활성화
        self.btn_black.setEnabled(False)
        self.btn_audio.setEnabled(False)
        self.btn_freeze.setEnabled(False)
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
        def _is_within_tmp(path):
            try:
                target = Path(path).resolve()
                root = TMP_DIR.resolve()
                return target == root or root in target.parents
            except Exception:
                return False

        def _cache_record(path_text):
            try:
                if not path_text:
                    return None
                target = Path(path_text).resolve()
                if not _is_within_tmp(target):
                    log.warning(f'cache record skipped outside TMP_DIR: {target}')
                    return None
                if target.is_symlink() or not target.is_file():
                    return None
                return (str(target), target.stat().st_size)
            except Exception as e:
                log.debug(f'cache record skipped: {e}')
                return None

        def _safe_unlink_cache(path_text):
            try:
                target = Path(path_text).resolve()
                if not _is_within_tmp(target):
                    log.warning(f'cache evict skipped outside TMP_DIR: {target}')
                    return 0
                if target.is_symlink() or not target.is_file():
                    return 0
                size = target.stat().st_size
                target.unlink(missing_ok=True)
                return size
            except Exception as e:
                log.debug(f'evict unlink {path_text}: {e}')
                return 0

        # 유효한 파일만 남김
        valid = []
        for fp, tp in self._tc_cache.items():
            rec = _cache_record(tp)
            if rec:
                valid.append((fp, rec[0], rec[1]))
        # 용량 계산
        total_bytes = sum(size for _, _, size in valid)
        # 파일 수 또는 용량 초과 시 오래된 것부터 제거
        valid_by_fp = {fp: tp for fp, tp, _ in valid}
        order = [fp for fp in self._tc_cache_order if fp in valid_by_fp]
        while (len(order) > max_files or
               total_bytes > max_gb * 1024**3) and order:
            oldest_fp = order.pop(0)
            oldest_tp = self._tc_cache.pop(oldest_fp, None)
            if oldest_tp:
                for p in [oldest_tp, oldest_tp.replace('.mp4','_preview.mp4')]:
                    total_bytes -= _safe_unlink_cache(p)
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
        # VLC 원본 재생 경로에서는 사전 변환이 첫 재생 반응성을 해친다.
        if Path(filepath).suffix.lower() in DIRECT_VLC_EXTS:
            log.info(f'skip preconvert for VLC direct playback: {Path(filepath).name}')
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

        def _on_finished(fp=filepath, thread=t):
            if hasattr(self, '_preconvert_threads') and thread in self._preconvert_threads:
                self._preconvert_threads.remove(thread)
                log.debug(f'preconvert thread cleanup on finished: {Path(fp).name}')
            if hasattr(self, '_preconvert_jobs') and self._preconvert_jobs.get(fp) is thread:
                self._preconvert_jobs.pop(fp, None)
            if hasattr(self, '_tc_cache') and self._tc_cache.get(fp) is None:
                self._tc_cache.pop(fp, None)

        t.ready_full.connect(_on_done)
        t.error.connect(_on_err)
        t.finished.connect(_on_finished)

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
            self.ai_lbl.setText("✓ 파일 추가 완료 — CUE 또는 더블클릭으로 원본 파일을 바로 재생합니다")
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

    def _prune_dead_threads(self):
        dead_threads = getattr(self, '_dead_threads', [])
        if not dead_threads:
            return
        kept = []
        removed = 0
        for thread in list(dead_threads):
            try:
                if thread and thread.isRunning():
                    kept.append(thread)
                else:
                    removed += 1
            except Exception:
                removed += 1
        self._dead_threads = kept
        if removed:
            log.debug(f'dead thread refs pruned: removed={removed} running={len(kept)}')
        try:
            limit = max(1, int(getattr(self, '_dead_threads_limit', 16) or 16))
        except Exception:
            limit = 16
        if len(kept) > limit:
            if getattr(self, '_dead_threads_limit_logged', False):
                return
            self._dead_threads_limit_logged = True
            log.warning(f'dead thread refs still running above limit: {len(kept)}/{limit}')
        else:
            self._dead_threads_limit_logged = False

    def _track_dead_thread(self, thread):
        if not thread:
            return
        if not hasattr(self, '_dead_threads'):
            self._dead_threads = []
        if thread not in self._dead_threads:
            self._dead_threads.append(thread)
        self._prune_dead_threads()

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
            self._track_dead_thread(t)
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
        self._track_dead_thread(t)
        try:
            t.abort()
        except Exception as e:
            log.debug(f'loudness abort: {e}')

    def _retire_probe(self):
        self._probe_seq += 1
        self._metadata_probe_timer_seq += 1
        self._pending_metadata_probe = None
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
        self._track_dead_thread(t)
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
        info = {
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
        hint = load_clip_metadata_hint(filepath)
        if hint:
            info.update(hint)
            info["filename"] = p.name
            info["filepath"] = filepath
            info["size"] = size or info.get("size", 0)
            info["provisional"] = True
            log.debug(f"metadata hint applied before probe: {p.name}")
        return info

    def _apply_provisional_metadata(self, filepath):
        p = Path(filepath)
        info = self._provisional_info(filepath)
        self.cur_info = info
        self.cur_id = None
        self._metadata_ready = False
        self._file_loaded_emitted = False
        self.fps = self._safe_float_value(info.get("fps", 29.97), 29.97)
        self.df = bool(info.get("df", True))
        self.tc_offset = 0.0
        self._tc_offset_frames = 0
        self._display_frame = 0
        self._last_display_dur_frames = None
        self._last_slider_value = None
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self._sync_frame_timer_interval()
        self.duration = max(0.0, self._safe_float_value(info.get("duration", 0), 0.0))
        self._source_duration = self.duration
        self._using_preview = False
        self.lbl_fmt.setText(info.get("format_short", "—"))
        self.lbl_cod.setText(info.get("codec", "") or "—")
        h = max(0, self._safe_int_value(info.get("height", 0), 0))
        w = max(0, self._safe_int_value(info.get("width", 0), 0))
        res_str = ("4K" if w >= 3840 else "HD" if w >= 1920 else f"{h}p") if h else "—"
        self.lbl_res.setText(res_str)
        self.lbl_fps.setText(f"{self._media_fps():.2f}")
        self.lbl_df.setText("DF" if self._drop_frame_enabled() else "NDF")
        self.lbl_df.setStyleSheet(
            f"color:{C['teal']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;"
        )
        hinted_ch = max(
            max(0, self._safe_int_value(info.get("audio_stream_count", 0), 0)),
            max(0, self._safe_int_value(info.get("channels", 0), 0)),
        )
        provisional_ch = max(1, min(8, hinted_ch)) if hinted_ch else (8 if p.suffix.lower() == ".mxf" else 2)
        self.lbl_ch.setText(f"{provisional_ch}CH")
        for cb, ch_no in self._ch_checks:
            cb.setChecked(ch_no in (1, 2))
            cb.setEnabled(ch_no <= provisional_ch)
        self._selected_chs = [1, 2]
        self.audio_mix.set_file(filepath, 0, 0)
        self.audio_mix.set_channels(self._selected_chs)
        # Metadata is intentionally delayed for playback responsiveness, but
        # meters should still appear immediately with a sensible provisional rail.
        provisional_streams = max(0, self._safe_int_value(info.get("audio_stream_count", 0), 0))
        self.meter_ctrl.start_file(filepath, provisional_ch, self.player, (1, 2), provisional_streams)
        self.tc_dur.setText(self._frames_to_tc(self._duration_frames(), include_offset=False))
        self._apply_qc_markers()
        self._res_text.setPlainText(f"{w}\u00d7{h}" if w and h else "")
        self.btn_black.setEnabled(False)
        self.btn_audio.setEnabled(False)
        self.btn_freeze.setEnabled(False)
        self.ai_lbl.setText(f"⏳ 3/4 메타데이터 분석 중 — {Path(filepath).name}")

    def _apply_probe_metadata(self, filepath, info, warnings, emit_loaded=False):
        try:
            previous_selected = self._get_selected_audio_channels()
        except Exception:
            previous_selected = list(getattr(self, '_selected_chs', []) or [])
        self.cur_info = info
        self._metadata_ready = True
        self.fps       = self._safe_float_value(info.get("fps", 29.97), 29.97)
        self.df        = bool(info.get("df", False)) and self._nominal_fps() in (30, 60)
        self.tc_offset = self._safe_float_value(info.get("tc_offset", 0.0), 0.0)
        self._tc_offset_frames = self._parse_tc_offset_frames(info.get("timecode", ""))
        self._display_frame = 0
        self._last_display_dur_frames = None
        self._last_slider_value = None
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self._sync_frame_timer_interval()
        self.duration  = max(0.0, self._safe_float_value(info.get("duration", 0), 0.0))
        self._source_duration = self.duration
        self._using_preview = False

        self.lbl_fmt.setText(info.get("format_short","—"))
        self.lbl_cod.setText(info.get("codec","—") or "—")
        h = max(0, self._safe_int_value(info.get("height", 0), 0))
        w = max(0, self._safe_int_value(info.get("width", 0), 0))
        res_str = ("4K" if w >= 3840 else "HD" if w >= 1920 else f"{h}p") if h else "—"
        self.lbl_res.setText(res_str)
        fps_str = f"{self._media_fps():.2f}"
        self.lbl_fps.setText(fps_str)
        df_label = "DF" if self._drop_frame_enabled() else "NDF"
        df_color = C['teal'] if self._drop_frame_enabled() else C['text2']
        self.lbl_df.setText(df_label)
        self.lbl_df.setStyleSheet(f"color:{df_color};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;")
        ch_count = max(0, self._safe_int_value(info.get('channels', 0), 0))
        audio_streams = max(0, self._safe_int_value(info.get('audio_stream_count', 0), 0))
        stream_count = max(audio_streams, ch_count)
        self.lbl_ch.setText(f"{stream_count}CH")
        first_enabled = None
        for cb, ch_no in self._ch_checks:
            enabled = ch_no <= stream_count
            cb.setEnabled(enabled and not getattr(self, '_loading', False))
            if enabled and first_enabled is None:
                first_enabled = cb
        default_channels = [1, 2]
        valid_previous = []
        for ch in previous_selected:
            ch_num = self._safe_int_value(ch, 0)
            if 1 <= ch_num <= stream_count:
                valid_previous.append(ch_num)
        preferred_channels = valid_previous or default_channels
        for cb, _ in self._ch_checks:
            cb.setChecked(False)
        default_selected = []
        for cb, ch_no in self._ch_checks:
            if ch_no <= stream_count and ch_no in preferred_channels:
                cb.setChecked(True)
                default_selected.append(ch_no)
        if not default_selected and first_enabled:
            first_enabled.setChecked(True)
            default_selected = [1]
        self._selected_chs = default_selected or [1, 2]
        self.tc_dur.setText(self._frames_to_tc(self._duration_frames(), include_offset=False))
        self._apply_qc_markers()
        self._res_text.setPlainText(f"{w}\u00d7{h}" if w and h else "")

        self.cur_id = save_clip(info)
        self.lbl_dbsaved.setText("✓ DB 저장됨")
        QTimer.singleShot(2500, lambda: self.lbl_dbsaved.setText(""))

        self.ai_lbl.setText(f"⚠ {warnings[0]}" if warnings else "AI 분석 준비됨")
        self.meter_ctrl.start_file(
            filepath, ch_count or 2, self.player, (1, 2),
            audio_streams
        )
        self.audio_mix.set_file(
            filepath,
            audio_streams,
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

    def _touch_loudness_cache(self, key):
        if not key:
            return
        cache = getattr(self, '_loudness_cache', {})
        order = [
            item for item in getattr(self, '_loudness_cache_order', [])
            if item in cache and item != key
        ]
        if key in cache:
            order.append(key)
        self._loudness_cache_order = order

    def _store_loudness_cache(self, key, result):
        if not key or not isinstance(result, dict):
            return
        if not hasattr(self, '_loudness_cache'):
            self._loudness_cache = {}
        self._loudness_cache[key] = dict(result)
        self._touch_loudness_cache(key)
        try:
            limit = max(1, int(getattr(self, '_loudness_cache_limit', 32) or 32))
        except Exception:
            limit = 32
        while len(self._loudness_cache_order) > limit:
            old = self._loudness_cache_order.pop(0)
            self._loudness_cache.pop(old, None)
            log.debug('loudness cache evicted oldest entry')

    def _normalize_loudness_result(self, result):
        if not isinstance(result, dict):
            log.warning(f'loudness result ignored: unexpected type {type(result).__name__}')
            return None
        try:
            integrated = float(result.get('integrated'))
        except Exception:
            log.warning('loudness result ignored: missing integrated value')
            return None
        if not math.isfinite(integrated):
            log.warning(f'loudness result ignored: non-finite integrated value {integrated!r}')
            return None
        normalized = dict(result)
        normalized['integrated'] = integrated
        return normalized

    def _start_loudness_analysis(self, filepath):
        self._retire_loudness_analysis()
        if not filepath or not Path(filepath).exists():
            return
        stream_count = max(0, self._safe_int_value(self.cur_info.get('audio_stream_count', 0), 0))
        ch_count = max(0, self._safe_int_value(self.cur_info.get('channels', 0), 0))
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

        duration = max(0.0, self._safe_float_value(self.cur_info.get('duration', self.duration), 0.0))
        if duration > 300.0:
            self.meter_ctrl.set_loudness_analysis_pending('LIVE')
            log.info(
                f'loudness full-file auto scan skipped for long file: '
                f'{Path(filepath).name} duration={duration:.1f}s'
            )
            record_state_event('loudness', 'full scan skipped', file=Path(filepath).name, duration=f'{duration:.1f}s')
            return

        key = self._loudness_cache_key(filepath)
        cached = self._loudness_cache.get(key)
        if cached:
            self._touch_loudness_cache(key)
            self._apply_loudness_result(filepath, cached, from_cache=True)
            return

        self.meter_ctrl.set_loudness_analysis_pending('SCAN')
        self._loudness_seq += 1
        seq = self._loudness_seq
        t = LoudnessAnalyzeThread(
            filepath,
            stream_count,
            ch_count or 2,
            duration,
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
            normalized = self._normalize_loudness_result(result)
            if normalized is None:
                if fp == self.cur_file:
                    self.meter_ctrl.set_loudness_analysis_error('ERR')
                    self.status_changed.emit(f'  ⚠ 라우드니스 결과 오류 — {Path(fp).name}')
                return
            self._store_loudness_cache(cache_key, normalized)
            self._apply_loudness_result(fp, normalized)

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
        result = self._normalize_loudness_result(result)
        if result is None:
            self.meter_ctrl.set_loudness_analysis_error('ERR')
            self.status_changed.emit(f'  ⚠ 라우드니스 결과 오류 — {Path(filepath).name}')
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
        stream_count = max(
            max(0, self._safe_int_value(self.cur_info.get('audio_stream_count', 0), 0)),
            max(0, self._safe_int_value(self.cur_info.get('channels', 0), 0)),
        )
        for cb, ch_no in getattr(self, '_ch_checks', []):
            cb.setEnabled(enabled and stream_count > 0 and ch_no <= stream_count)
        has_file = bool(self.cur_file)
        metadata_ready = bool(getattr(self, '_metadata_ready', False))
        for name in ('btn_black', 'btn_audio', 'btn_freeze'):
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
        record_state_event(
            'cue',
            'cue complete',
            file=Path(filepath).name,
            metadata=getattr(self, '_metadata_ready', False),
            pos=f'{self.player.position()}ms',
        )
        if not getattr(self, '_metadata_ready', False):
            file_name = Path(filepath).name
            message = "✓ CUE 완료 — PLAY 우선, 메타데이터는 백그라운드 분석"
            status_message = f"  ▌CUE  {file_name}  |  PLAY 가능 — 메타데이터 백그라운드 분석 예정"
            self._set_loading_state(False)
            self.ai_lbl.setText(message)
            self.status_changed.emit(status_message)
            self._start_pending_metadata_probe_after_cue(delay_ms=1200)
            return
        self._set_loading_state(False)
        self.ai_lbl.setText(message)
        self.status_changed.emit(status_message)
        self._emit_file_loaded_once()

    def _prepare_vlc_cue(self, filepath, target_ms=0, load_seq=None):
        self._cue_ready_seq += 1
        seq = self._cue_ready_seq
        start = time.monotonic()
        timeout_sec = 1.4
        target_ms = max(0, int(target_ms))
        file_name = Path(filepath).name
        record_state_event('cue', 'cue prepare', file=file_name, target=f'{target_ms}ms', seq=load_seq)

        def _force_cue_position(label='cue'):
            if seq != self._cue_ready_seq or not self._load_is_current(load_seq, filepath):
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
            if seq != self._cue_ready_seq or not self._load_is_current(load_seq, filepath):
                return
            _force_cue_position('pre-complete')

            def _complete_after_settle():
                if seq != self._cue_ready_seq or not self._load_is_current(load_seq, filepath):
                    return
                _force_cue_position('complete')
                self._complete_file_load(
                    filepath,
                    "✓ 4/4 재생 준비 완료 — ▶ 재생버튼을 누르세요",
                    f"  ▌CUE  {file_name}  |  4/4 재생 준비 완료  —  ▶ 재생버튼을 누르세요",
                )

            QTimer.singleShot(80, _complete_after_settle)

        def _poll():
            if seq != self._cue_ready_seq or not self._load_is_current(load_seq, filepath):
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
            ready = elapsed >= 0.45 and has_duration_hint
            fallback_ready = elapsed >= 0.90
            if ready or fallback_ready:
                if media_len and media_len > 0:
                    log.debug(f'VLC cue ready: {file_name} length={media_len}ms elapsed={elapsed:.2f}s')
                elif not has_duration_hint:
                    log.warning(f'VLC cue fallback without duration: {file_name}')
                else:
                    log.debug(f'VLC cue fallback with probe duration: {file_name} elapsed={elapsed:.2f}s')
                record_state_event(
                    'cue',
                    'cue readiness reached',
                    file=file_name,
                    elapsed=f'{elapsed:.2f}s',
                    media_len=f'{media_len}ms',
                    fallback=fallback_ready,
                )
                self._empty_proxy.hide()
                self._video_item.show()
                QTimer.singleShot(70, _finish_cue)
                return

            if elapsed < timeout_sec:
                QTimer.singleShot(50, _poll)
                return

            if not has_duration_hint:
                log.warning(f'VLC cue readiness timeout: {file_name}')
            else:
                log.debug(f'VLC cue readiness timeout fallback: {file_name}')
            self._empty_proxy.hide()
            self._video_item.show()
            QTimer.singleShot(70, _finish_cue)

        def _start_preroll():
            if seq != self._cue_ready_seq or not self._load_is_current(load_seq, filepath):
                return
            self._empty_proxy.hide()
            self._video_item.show()
            try:
                self._show_cue_first_frame(target_ms)
            except Exception as e:
                log.debug(f'vlc cue preroll: {e}')
            QTimer.singleShot(50, _poll)

        QTimer.singleShot(50, _start_preroll)

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
        if hasattr(self, '_playback_progress_timer'):
            self._playback_progress_timer.stop()
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
            return False, '파일을 찾을 수 없습니다', self._path_access_hint(filepath)
        if not path.is_file():
            return False, '파일이 아닙니다', '폴더나 특수 경로는 열 수 없습니다.'
        if path.suffix.lower() not in VIDEO_EXTS:
            return False, '지원하지 않는 파일 형식입니다', 'MXF/MP4 같은 지원 영상 파일을 선택하세요.'
        try:
            size = path.stat().st_size
        except PermissionError:
            return False, '파일 접근 권한이 없습니다', '읽기 권한, NAS/외장하드 권한, 다른 프로그램의 파일 잠금 여부를 확인하세요.'
        except OSError as e:
            return False, '파일 정보를 읽을 수 없습니다', f'{e}\n{self._path_access_hint(filepath)}'
        if size <= 0:
            return False, '빈 파일입니다', '파일 크기가 0바이트입니다. 정상 영상 파일인지 확인하세요.'
        try:
            with path.open('rb') as fh:
                fh.read(4096)
        except PermissionError:
            return False, '파일 접근 권한이 없습니다', '읽기 권한, NAS/외장하드 권한, 다른 프로그램의 파일 잠금 여부를 확인하세요.'
        except OSError as e:
            return False, '파일을 읽을 수 없습니다', f'{e}\n{self._path_access_hint(filepath)}'
        return True, '', ''

    def _validate_probe_info(self, filepath, info):
        if not info:
            return (
                False,
                '파일 메타데이터 확인 실패',
                'FFprobe가 파일 구조를 읽지 못했습니다. 파일 손상, 권한, 또는 지원되지 않는 컨테이너인지 확인하세요.',
                [],
            )
        width = max(0, self._safe_int_value(info.get('width', 0), 0))
        height = max(0, self._safe_int_value(info.get('height', 0), 0))
        codec = str(info.get('codec', '') or '').strip()
        if width <= 0 or height <= 0 or not codec:
            return (
                False,
                '비디오 스트림을 찾지 못했습니다',
                '이 파일에 재생 가능한 비디오 스트림이 없거나 FFprobe가 비디오 정보를 읽지 못했습니다.',
                [],
            )
        warnings = []
        audio_streams = max(0, self._safe_int_value(info.get('audio_stream_count', 0), 0))
        channels = max(0, self._safe_int_value(info.get('channels', 0), 0))
        if audio_streams <= 0 and channels <= 0:
            warnings.append('오디오 스트림 없음 — 영상만 재생됩니다')
        duration = self._safe_float_value(info.get('duration', 0), None)
        if duration is None:
            warnings.append('길이 정보 확인 실패 — 탐색/REM 표시가 제한될 수 있습니다')
        elif duration <= 0:
            warnings.append('길이 정보 없음 — 탐색/REM 표시가 제한될 수 있습니다')
        return True, '', '', warnings

    def _metadata_audio_restart_required(self, info, was_fallback_audio):
        if not was_fallback_audio:
            return True
        audio_streams = max(0, self._safe_int_value(info.get('audio_stream_count', 0), 0))
        channels = max(0, self._safe_int_value(info.get('channels', 0), 0))
        selected = self._get_selected_audio_channels()
        if not selected:
            return False
        simple_first_stream = audio_streams <= 1 and channels <= 2
        default_pair_only = all(ch in (1, 2) for ch in selected)
        if simple_first_stream and default_pair_only:
            return False
        return True

    def _start_metadata_probe(self, filepath, load_t0, timings, load_seq=None):
        self._probe_seq += 1
        seq = self._probe_seq
        thread = ProbeThread(filepath)
        self._probe_thread = thread
        file_name = Path(filepath).name

        def _stale():
            return seq != self._probe_seq or not self._load_is_current(load_seq, filepath)

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
                record_state_event('metadata', 'probe blocked', file=file_name, ffprobe=f'{elapsed:.3f}s', reason=title)
                return
            if warnings:
                log.warning(f'async metadata probe warning: {file_name} | {"; ".join(warnings)}')
            apply_t0 = time.monotonic()
            was_fallback_audio = self.audio_mix.is_running() and not self.audio_mix.active_layout_known()
            self._apply_probe_metadata(filepath, info, warnings, emit_loaded=True)
            apply_elapsed = time.monotonic() - apply_t0
            total_elapsed = time.monotonic() - load_t0
            log.info(
                f'async metadata ready: {file_name} '
                f'ffprobe={elapsed:.3f}s apply={apply_elapsed:.3f}s '
                f'total={total_elapsed:.3f}s '
                f'pre_steps={" ".join(timings)}'
            )
            record_state_event(
                'metadata',
                'probe ready',
                file=file_name,
                ffprobe=f'{elapsed:.3f}s',
                apply=f'{apply_elapsed:.3f}s',
                total=f'{total_elapsed:.3f}s',
            )
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._reset_audio_recovery()
                if self._metadata_audio_restart_required(info, was_fallback_audio):
                    self._schedule_audio_mix(delay_ms=80, restart=True, lead_sec=0.0)
                else:
                    log.info(f'audio mix kept after metadata: {file_name} fallback stream already matches selected channels')
                    record_state_event('audio-mix', 'kept after metadata', file=file_name)

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
            record_state_event('metadata', 'probe error', file=file_name, ffprobe=f'{elapsed:.3f}s', error=err)

        thread.probed.connect(_done)
        thread.error.connect(_error)
        thread.start()
        log.info(f'async metadata probe started: {file_name}')
        record_state_event('metadata', 'probe started', file=file_name, seq=load_seq)

    def _schedule_metadata_probe(self, filepath, load_t0, timings, load_seq=None, delay_ms=650):
        self._metadata_probe_timer_seq += 1
        timer_seq = self._metadata_probe_timer_seq
        file_name = Path(filepath).name

        def _run():
            if timer_seq != self._metadata_probe_timer_seq:
                return
            if not self._load_is_current(load_seq, filepath):
                log.debug(f'stale delayed metadata probe skipped: {file_name}')
                return
            if getattr(self, '_metadata_ready', False):
                return
            self._pending_metadata_probe = None
            self.status_changed.emit(f'  ⏳ 메타데이터 백그라운드 분석 중 — {file_name}')
            self._start_metadata_probe(filepath, load_t0, list(timings), load_seq=load_seq)

        QTimer.singleShot(max(0, int(delay_ms)), _run)

    def _start_pending_metadata_probe_after_cue(self, delay_ms=650):
        pending = getattr(self, '_pending_metadata_probe', None)
        if not pending:
            return
        filepath, load_t0, timings, load_seq = pending
        if not self._load_is_current(load_seq, filepath):
            self._pending_metadata_probe = None
            return
        self._schedule_metadata_probe(filepath, load_t0, timings, load_seq=load_seq, delay_ms=delay_ms)

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
        file_name = Path(filepath).name if filepath else '?'
        self.status_changed.emit(f"  ⏳ 1/4 파일 확인 — {file_name}")
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
        load_seq = self._next_load_seq('load_file', filepath)
        log.info(f'load_file: {Path(filepath).name}')
        record_state_event('file', 'load requested', file=Path(filepath).name)
        self._stop_all()
        mark_step('stop_all')
        self._cancel_preconvert_job(filepath)
        mark_step('cancel_preconvert')
        self._reset_audio_recovery()
        mark_step('reset_audio')
        self._set_loading_state(True, f"⏳ 1/4 파일 점검 완료 — {Path(filepath).name}")
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
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")
        mark_step('state_reset')

        # 클립 리스트 선택 표시
        for i in range(self.clip_list.count()):
            item = self.clip_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == filepath:
                self.clip_list.setCurrentItem(item)
                break
        mark_step('list_select')

        if Path(filepath).suffix.lower() in DIRECT_VLC_EXTS:
            self._apply_provisional_metadata(filepath)
            mark_step('provisional_ui')
            self._set_loading_state(True, f"⏳ 2/4 VLC CUE 준비 중 — {Path(filepath).name}")
            self.empty_label.setText('⏳  2/4 VLC로 원본 로딩 중...')
            self._empty_proxy.show(); self._video_item.hide()
            try:
                vlc_set_t0 = time.monotonic()
                self.player.setSource(QUrl.fromLocalFile(filepath))
                self.player.audio_set_volume(0)
                timings.append(f'vlc_set_source={time.monotonic() - vlc_set_t0:.3f}s')
                log.info(
                    f'load_file async cue start: {Path(filepath).name} '
                    f'seq={load_seq} '
                    f'total_before_cue={time.monotonic() - load_t0:.3f}s '
                    f'steps={" ".join(timings)}'
                )
                record_state_event(
                    'file',
                    'vlc source set',
                    file=Path(filepath).name,
                    seq=load_seq,
                    total=f'{time.monotonic() - load_t0:.3f}s',
                )
                self._pending_metadata_probe = (filepath, load_t0, list(timings), load_seq)
                self._prepare_vlc_cue(filepath, 0, load_seq=load_seq)
            except Exception as e:
                msg = friendly_error_text('vlc_load', e, filepath)
                self.empty_label.setText(f'⚠ {msg}')
                self.ai_lbl.setText(f'⚠ {friendly_error_title("vlc_load", e, filepath)}')
                self._set_loading_state(False)
                log.error(f'VLC load failed: {Path(filepath).name} | {e}')
                record_state_event('file', 'vlc source error', file=Path(filepath).name, error=e)
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
        self._set_loading_state(True, f"⏳ 2/4 CUE 준비 중 — {Path(filepath).name}")
        self._metadata_ready = True
        self.cur_info = info
        self.fps       = self._safe_float_value(info.get("fps", 29.97), 29.97)
        self.df        = bool(info.get("df", False)) and self._nominal_fps() in (30, 60)
        self.tc_offset = self._safe_float_value(info.get("tc_offset", 0.0), 0.0)
        self._tc_offset_frames = self._parse_tc_offset_frames(info.get("timecode", ""))
        self._display_frame = 0
        self._last_display_dur_frames = None
        self._last_slider_value = None
        self._clock_anchor_frame = 0
        self._clock_anchor_time = 0.0
        self._frame_clock_active = False
        self._frame_display_timer.stop()
        self._sync_frame_timer_interval()
        self.duration  = max(0.0, self._safe_float_value(info.get("duration", 0), 0.0))
        self._source_duration = self.duration
        self._using_preview = False

        self.lbl_fmt.setText(info.get("format_short","—"))
        self.lbl_cod.setText(info.get("codec","—") or "—")
        h = max(0, self._safe_int_value(info.get("height", 0), 0))
        w = max(0, self._safe_int_value(info.get("width", 0), 0))
        res_str = ("4K" if w >= 3840 else "HD" if w >= 1920 else f"{h}p") if h else "—"
        self.lbl_res.setText(res_str)
        fps_str = f"{self._media_fps():.2f}"
        self.lbl_fps.setText(fps_str)
        df_label = "DF" if self._drop_frame_enabled() else "NDF"
        df_color = C['teal'] if self._drop_frame_enabled() else C['text2']
        self.lbl_df.setText(df_label)
        self.lbl_df.setStyleSheet(f"color:{df_color};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:11px;")
        ch_count = max(0, self._safe_int_value(info.get('channels', 0), 0))
        audio_streams = max(0, self._safe_int_value(info.get('audio_stream_count', 0), 0))
        stream_count = max(audio_streams, ch_count)
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
        self._res_text.setPlainText(f"{w}\u00d7{h}" if w and h else "")
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
        self.btn_freeze.setEnabled(False)
        self.ai_lbl.setText(f"⚠ {warnings[0]}" if warnings else "AI 분석 준비됨")

        # 실시간 오디오 미터 시작 (채널 수 전달)
        self.meter_ctrl.start_file(
            filepath, ch_count or 2, self.player, (1, 2),
            audio_streams
        )
        self.audio_mix.set_file(
            filepath,
            audio_streams,
            ch_count
        )
        self.audio_mix.set_channels(self._selected_chs)
        self._start_loudness_analysis(filepath)
        mark_step('meter_loudness_start')

        if Path(filepath).suffix.lower() in DIRECT_VLC_EXTS:
            self.empty_label.setText('⏳  2/4 VLC로 원본 로딩 중...')
            self._empty_proxy.show(); self._video_item.hide()
            try:
                vlc_set_t0 = time.monotonic()
                self.player.setSource(QUrl.fromLocalFile(filepath))
                self.player.audio_set_volume(0)
                timings.append(f'vlc_set_source={time.monotonic() - vlc_set_t0:.3f}s')
                log.info(
                    f'load_file timing: {Path(filepath).name} '
                    f'seq={load_seq} '
                    f'total_before_cue={time.monotonic() - load_t0:.3f}s '
                    f'steps={" ".join(timings)}'
                )
                self._prepare_vlc_cue(filepath, 0, load_seq=load_seq)
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
            QTimer.singleShot(50, lambda t=cached_tmp, fp=filepath, s=load_seq: self._on_transcode_ready(t, fp, s))
        else:
            # 캐시 없음 → 변환 시작
            ext = Path(filepath).suffix.lower()
            msg = '⏳  파일 변환 중...' if ext in ('.mp4','.mov','.m4v','.mkv','.avi','.mts','.m2ts') \
                  else "⏳  영상 변환 중...\n잠시만 기다려주세요"
            self.empty_label.setText(msg)
            self._empty_proxy.show(); self._video_item.hide()
            self._tc_thread = TranscodeThread(filepath, self._get_selected_ch_pairs())
            self._tc_thread.ready.connect(lambda tmp, fp=filepath, s=load_seq: self._on_transcode_ready(tmp, fp, s))
            self._tc_thread.ready_full.connect(lambda tmp, fp=filepath, s=load_seq: self._on_transcode_full(tmp, fp, s))
            # 진행률 표시
            self.prog_ai.setRange(0, 100)
            self.prog_ai.setValue(0)
            self.prog_ai.show()
            def _tc_progress(pct, fp=filepath, s=load_seq):
                if not self._load_is_current(s, fp):
                    return
                self.prog_ai.setValue(pct)
                if pct < 100:
                    self.ai_lbl.setText(f'⏳ 변환 중... {pct}%')
                else:
                    self.ai_lbl.setText('✓ 변환 완료')
                    self.prog_ai.hide()
                    self.prog_ai.setRange(0, 0)  # indeterminate로 복원
            self._tc_thread.progress.connect(_tc_progress)
            def _tc_err(msg, el=self.empty_label, ai=self.ai_lbl, fp=filepath, s=load_seq):
                if not self._load_is_current(s, fp):
                    log.debug(f'stale transcode error ignored: {Path(fp).name}')
                    return
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

    def _on_transcode_ready(self, tmp, expected_file=None, load_seq=None):
        if expected_file and not self._load_is_current(load_seq, expected_file):
            log.debug(f'stale transcode ready ignored: {Path(expected_file).name}')
            return
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

    def _on_transcode_full(self, tmp, expected_file=None, load_seq=None):
        if expected_file and not self._load_is_current(load_seq, expected_file):
            log.debug(f'stale transcode full ignored: {Path(expected_file).name}')
            return
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
        if self.cur_file:
            self.player.audio_set_volume(0)
            self.audio_mix.set_channels(selected)
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._reset_audio_recovery()
                self._schedule_audio_mix(delay_ms=120, restart=True)
            label = "/".join(str(ch) for ch in selected)
            self.ai_lbl.setText(f"✓ CH {label} 믹스 출력  |  LKFS 기준은 1/2CH")
            record_state_event('audio-mix', 'channel selection changed', file=Path(self.cur_file).name, channels=selected)

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
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        pos = self.player.position() if pos_ms is None else self._safe_int_value(pos_ms, 0)
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
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        pos = self.player.position() if pos_ms is None else self._safe_int_value(pos_ms, 0)
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
        if not getattr(self, '_metadata_ready', False):
            # MXF playback must keep video/audio together even while metadata
            # is still probing. A fallback first-audio-stream output is expected.
            return True
        audio_streams = max(0, self._safe_int_value(self.cur_info.get('audio_stream_count', 0), 0))
        channels = max(0, self._safe_int_value(self.cur_info.get('channels', 0), 0))
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

    def _reset_playback_progress_watch(self):
        try:
            pos_ms = int(self.player.position() or 0)
        except Exception:
            pos_ms = 0
        self._playback_progress_last_ms = pos_ms
        self._playback_progress_last_frame = self._ms_to_frame(pos_ms)
        self._playback_progress_started_at = time.monotonic()
        self._playback_progress_stall_ticks = 0

    def _start_playback_progress_watch(self):
        self._reset_playback_progress_watch()
        if hasattr(self, '_playback_progress_timer') and not self._playback_progress_timer.isActive():
            self._playback_progress_timer.start()

    def _stop_playback_progress_watch(self):
        if hasattr(self, '_playback_progress_timer'):
            self._playback_progress_timer.stop()
        self._playback_progress_stall_ticks = 0

    def _check_playback_progress(self):
        if not self.cur_file:
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._stop_playback_progress_watch()
            return
        try:
            pos_ms = int(self.player.position() or 0)
            frame = self._ms_to_frame(pos_ms)
        except Exception as e:
            log.debug(f'playback progress read failed: {e}')
            return

        last_ms = self._safe_int_value(getattr(self, '_playback_progress_last_ms', pos_ms), pos_ms)
        last_frame = self._safe_int_value(getattr(self, '_playback_progress_last_frame', frame), frame)
        moved_ms = pos_ms - last_ms
        moved_frames = frame - last_frame
        now = time.monotonic()
        started = self._safe_float_value(getattr(self, '_playback_progress_started_at', now), now)
        near_end = bool(self.duration and pos_ms >= int(max(0, self.duration * 1000 - 900)))

        if now - started < 2.0 or near_end:
            self._playback_progress_last_ms = pos_ms
            self._playback_progress_last_frame = frame
            self._playback_progress_stall_ticks = 0
            return

        stagnant = moved_ms < 180 and moved_frames <= 0
        if stagnant:
            self._playback_progress_stall_ticks += 1
        else:
            self._playback_progress_stall_ticks = 0

        if self._playback_progress_stall_ticks >= 2:
            last_warn = float(getattr(self, '_playback_progress_last_warn', 0.0) or 0.0)
            if now - last_warn >= 5.0:
                status = self.audio_mix.process_status() if hasattr(self, 'audio_mix') else {}
                file_name = Path(self.cur_file).name
                log.warning(
                    "playback progress warning "
                    f"file={file_name} pos={pos_ms}ms frame={frame} "
                    f"moved={moved_ms}ms/{moved_frames}f "
                    f"ticks={self._playback_progress_stall_ticks} audio={status}"
                )
                record_state_event(
                    "playback-watch",
                    "progress stagnant",
                    file=file_name,
                    pos=f"{pos_ms}ms",
                    frame=frame,
                    moved=f"{moved_ms}ms/{moved_frames}f",
                    ticks=self._playback_progress_stall_ticks,
                )
                self._playback_progress_last_warn = now

        self._playback_progress_last_ms = pos_ms
        self._playback_progress_last_frame = frame

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
                self._safe_int_value(self.cur_info.get('audio_stream_count', 0), 0) > 0
                or self._safe_int_value(self.cur_info.get('channels', 0), 0) > 0
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
        duration = self._safe_float_value(getattr(self, 'duration', 0.0), 0.0)
        target_ms = max(0, self._safe_int_value(ms, 0))
        ms = max(0, min(int(duration * 1000), target_ms)) if duration > 0 else target_ms
        self.player.setPosition(ms)
        self._sync_frame_clock(ms)
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._cancel_audio_mix()
            self._reset_audio_recovery()
            self._schedule_audio_mix(delay_ms=80, pos_ms=ms, restart=True)

    def _set_frame_position(self, frame):
        dur_frames = self._duration_frames()
        frame = self._safe_int_value(frame, 0)
        if dur_frames > 0:
            frame = max(0, min(dur_frames, frame))
        else:
            frame = max(0, frame)
        self._set_position(self._frame_to_ms(frame))

    def _transport_allowed(self, action, cooldown_sec=0.18):
        if getattr(self, '_loading', False):
            self.status_changed.emit('  ⏳ CUE 준비 중입니다 — 잠시만 기다려주세요')
            return False
        if self.cur_file and not getattr(self, '_metadata_ready', False):
            if action == 'play_pause' and getattr(self, '_cue_ready', False):
                pass
            else:
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
            log.info(f'play request: pause file={Path(self.cur_file).name} pos={self.player.position()}ms')
            record_state_event('transport', 'pause requested', file=Path(self.cur_file).name, pos=f'{self.player.position()}ms')
            self.player.pause()
        else:
            log.info(
                f'play request: start file={Path(self.cur_file).name} '
                f'pos={self.player.position()}ms metadata={self._metadata_ready} cue={self._cue_ready} '
                f'ch={self._get_selected_audio_channels()}'
            )
            record_state_event(
                'transport',
                'play requested',
                file=Path(self.cur_file).name,
                pos=f'{self.player.position()}ms',
                channels=self._get_selected_audio_channels(),
            )
            self.status_changed.emit(
                f"  ▶ PLAY 요청 — {Path(self.cur_file).name} | CH {','.join(map(str, self._get_selected_audio_channels()))}"
            )
            self.player.play()

    def stop(self):
        self._transport_guard_action = 'stop'
        self._transport_guard_until = time.monotonic() + 0.12
        if self.cur_file:
            record_state_event('transport', 'stop requested', file=Path(self.cur_file).name, pos=f'{self.player.position()}ms')
        if self._is_busy_loading():
            file_name = Path(self.cur_file).name if self.cur_file else '?'
            self._next_load_seq('stop_cancel', self.cur_file)
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
            self.empty_label.setText("▶\n\nMXF / MP4 파일을 열어주세요\n\n파일 추가 버튼 또는 파일 드래그로 불러오세요")
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
        self.tc_in_l.setStyleSheet(f"color:{C['yellow']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")

    def _clr_in(self):
        self.in_pt=None; self.tc_in_l.setText("—")
        self.tc_in_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")

    def _set_out(self):
        self.out_pt = self._display_frame / self._media_fps()
        self.tc_out_l.setText(
            self._frames_to_tc(self._display_frame, include_offset=self._tc_include_offset())
        )
        self.tc_out_l.setStyleSheet(f"color:{C['orange']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")

    def _clr_out(self):
        self.out_pt=None; self.tc_out_l.setText("—")
        self.tc_out_l.setStyleSheet(f"color:{C['text0']};font-family:'Cascadia Mono','Consolas','D2Coding';font-size:13px;background:transparent;")


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
        self._apply_qc_markers()

    def _on_state(self, state):
        self._raise_vlc_meters(force=True)
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
            log.info(
                f'play state entered file={Path(self.cur_file).name if self.cur_file else "-"} '
                f'pos={self.player.position()}ms metadata={self._metadata_ready} cue={self._cue_ready} '
                f'audio_first={getattr(self, "_first_audio_start_after_cue", False)}'
            )
            record_state_event(
                'transport',
                'playing state',
                file=Path(self.cur_file).name if self.cur_file else '-',
                pos=f'{self.player.position()}ms',
                metadata=self._metadata_ready,
                cue=self._cue_ready,
            )
            if self.cur_file:
                self.status_changed.emit(f"  ▶ 재생 중 — {Path(self.cur_file).name} | 오디오 믹스 준비")
            self._reset_audio_recovery()
            self._frame_clock_active = True
            self._sync_frame_timer_interval()
            self._sync_frame_clock(self.player.position())
            self._frame_display_timer.start()
            self._start_playback_progress_watch()
            if not self._audio_recovery_timer.isActive():
                self._audio_recovery_timer.start()
            self._led_timer.start()
            self.player.audio_set_volume(0)
            if getattr(self, '_first_audio_start_after_cue', False):
                self._schedule_audio_mix(delay_ms=20)
            else:
                self._schedule_audio_mix(delay_ms=40)
            self._arm_play_start_watchdog('state')
        else:
            if self.cur_file:
                log.debug(
                    f'play state left file={Path(self.cur_file).name} '
                    f'pos={self.player.position()}ms state={state.name if hasattr(state, "name") else state}'
                )
                record_state_event(
                    'transport',
                    'left playing',
                    file=Path(self.cur_file).name,
                    pos=f'{self.player.position()}ms',
                    state=state.name if hasattr(state, "name") else state,
                )
            self._cancel_play_start_watchdog()
            self._stop_playback_progress_watch()
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
        focused = QApplication.focusWidget()
        from PyQt6.QtWidgets import (
            QLineEdit, QTextEdit, QPlainTextEdit, QAbstractButton,
            QAbstractSpinBox, QTabBar, QTabWidget, QScrollBar,
        )
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit,
                                QAbstractSpinBox, QTabBar, QTabWidget)):
            e.ignore()
            return

        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        # Space: 재생/일시정지 전용
        # 버튼류/파일목록/스크롤 위젯 포커스 시 무시 → player만 동작
        if k==Qt.Key.Key_Space:
            if isinstance(focused, (QAbstractButton, QScrollBar, QListWidget)):
                e.ignore(); return
            self.toggle_play()
            e.accept(); return
        elif k==Qt.Key.Key_Left:
            if shift:
                self._set_position(max(0,self.player.position()-10000))
            else:
                self._step(-1)
            e.accept(); return
        elif k==Qt.Key.Key_Right:
            if shift:
                self._set_position(min(int(self.duration*1000),self.player.position()+10000))
            else:
                self._step(1)
            e.accept(); return
        elif k==Qt.Key.Key_Home:
            self._set_position(0)
            e.accept(); return
        elif k==Qt.Key.Key_End:
            self._set_position(max(0,int(self.duration*1000)-100))
            e.accept(); return
        elif k==Qt.Key.Key_I:
            self._set_in()
            e.accept(); return
        elif k==Qt.Key.Key_O:
            self._set_out()
            e.accept(); return
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

    def start_freeze_detect(self):
        """AI바 프리즈 버튼 → 오른쪽 프리즈 탭 분석 실행"""
        if not self.cur_file:
            return
        rp = getattr(self, '_right_panel', None)
        if rp and hasattr(rp, '_run_freeze_detect'):
            try:
                if hasattr(rp, 'tabs'):
                    freeze_page = rp.freeze_list.parentWidget() if hasattr(rp, 'freeze_list') else None
                    if freeze_page:
                        rp.tabs.setCurrentWidget(freeze_page)
                rp._run_freeze_detect()
                return
            except Exception as e:
                log.warning(f'freeze detect forward failed: {e}')
        self.ai_lbl.setText("⚠ 오른쪽 프리즈 탭을 사용할 수 없습니다")

# ══════════════════════════════════════════════════════════
# 오른쪽: 탭 패널
# ══════════════════════════════════════════════════════════
