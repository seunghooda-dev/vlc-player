"""
vlc_player.py — VLC 재생·오디오 믹스 어댑터
AudioMixPlayer/VlcPlayerAdapter: video_panel에서 분리된 FFmpeg 오디오 믹스, VLC 트랜스포트 재생 어댑터
"""
import math
import os
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer

from constants import (
    FFMPEG, FFPLAY, VLC_DIR, log,
    register_child_process, terminate_child_process,
    friendly_error_text, format_missing_runtime_tools,
    _hidden_subprocess_flags, record_state_event,
)
from safe import safe_float, safe_int


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

    # 숫자 변환 헬퍼는 safe.py 로 통합됨. 기존 self._safe_* 호출부 호환용 위임.
    _safe_int = staticmethod(safe_int)
    _safe_float = staticmethod(safe_float)

    @staticmethod
    def _file_name(filepath, default='-'):
        try:
            text = str(filepath or '').strip()
            if text:
                return Path(text).name or default
        except Exception:
            pass
        return default

    @staticmethod
    def _media_file_path(filepath):
        try:
            text = str(filepath or '').strip()
            if not text:
                return None
            path = Path(text)
            if path.exists() and path.is_file():
                return path
        except Exception:
            pass
        return None

    def set_file(self, filepath, audio_stream_count=0, channel_count=2):
        self.filepath = filepath
        self.audio_stream_count = max(0, self._safe_int(audio_stream_count, 0))
        self.channel_count = max(0, self._safe_int(channel_count, 0))
        self.audio_layout_known = self.audio_stream_count > 0 or self.channel_count > 0

    def set_channels(self, channels):
        cleaned = []
        if channels is None:
            source = [1, 2]
            explicit_empty = False
        else:
            if isinstance(channels, (str, bytes)):
                source = [channels]
            else:
                try:
                    source = list(channels)
                except TypeError:
                    source = [channels]
            explicit_empty = len(source) == 0
        for ch in source:
            n = self._safe_int(ch, 0)
            if 1 <= n <= 16 and n not in cleaned:
                cleaned.append(n)
        self.channels = [] if explicit_empty else (cleaned or [1, 2])

    def _max_output_channel(self):
        if not self.audio_layout_known:
            return 16
        if self.audio_stream_count > 1:
            return max(1, min(16, self.audio_stream_count))
        if self.channel_count > 0:
            return max(1, min(16, self.channel_count))
        return 0

    def effective_channels(self):
        source_max = self._max_output_channel()
        cleaned = []
        for ch in self.channels or []:
            n = self._safe_int(ch, 0)
            if 1 <= n <= 16 and (source_max <= 0 or n <= source_max) and n not in cleaned:
                cleaned.append(n)
        if cleaned:
            return cleaned
        if source_max > 0:
            return [1]
        return []

    def set_volume(self, value):
        self.volume = max(0.0, min(1.0, self._safe_float(value, self.volume)))

    def set_rate(self, rate):
        self.rate = max(0.5, min(2.0, self._safe_float(rate, 1.0)))

    def stop(self):
        was_active = bool(self._playing or self._ffplay or self._ffmpeg)
        if was_active:
            self.log_diagnostic('audio child stopping')
            record_state_event('audio-mix', 'stopping', file=self._file_name(self.filepath), channels=self.channels)
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
            'channels': list(self.effective_channels()),
            'requested_channels': list(self.channels or []),
        }

    def diagnostic_status(self):
        status = self.process_status()
        status.update({
            'ffmpeg_pid': getattr(self._ffmpeg, 'pid', None),
            'ffplay_pid': getattr(self._ffplay, 'pid', None),
            'file': self.filepath,
            'channels': list(self.effective_channels()),
            'requested_channels': list(self.channels or []),
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
        file_name = self._file_name(status.get('file'))
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
        media_path = self._media_file_path(self.filepath)
        if not media_path:
            self.last_error = '오디오 출력 파일을 찾을 수 없습니다.'
            return False
        filepath = str(media_path)
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
            '-i', filepath,
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
        creationflags = _hidden_subprocess_flags()
        try:
            self._ffmpeg = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            register_child_process(self._ffmpeg, 'audio mix ffmpeg')
            self._ffplay = subprocess.Popen(
                ffplay_cmd,
                stdin=self._ffmpeg.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
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
                file=self._file_name(filepath),
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
        ch = max(1, min(16, self._safe_int(ch, 1)))
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
        for ch in self.effective_channels() or [1, 2]:
            n = max(1, min(16, self._safe_int(ch, 0)))
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
        self._ensure_unpaused(seq)
        self._state = QMediaPlayer.PlaybackState.PlayingState
        self.playbackStateChanged.emit(self._state)
        self._timer.start()
        QTimer.singleShot(80, lambda s=seq: self._ensure_unpaused(s))
        QTimer.singleShot(220, lambda s=seq: self._ensure_unpaused(s))
        QTimer.singleShot(500, lambda s=seq: self._emit_duration(s))
        self._audio_apply_attempts = 0
        QTimer.singleShot(200, lambda s=seq: self._apply_audio_channel(s))
        QTimer.singleShot(700, lambda s=seq: self._apply_audio_channel(s))
        QTimer.singleShot(1200, lambda s=seq: self._apply_audio_channel(s))

    def _ensure_unpaused(self, seq=None):
        if not self._is_current_op(seq):
            return
        try:
            self._player.set_pause(0)
        except Exception as e:
            log.debug(f'vlc resume after play: {e}')

    def has_video_output(self):
        """첫 프레임 렌더 후 vout 개수가 1 이상 — CUE 준비 완료 조기 감지에 사용."""
        try:
            return int(self._player.has_vout() or 0) > 0
        except Exception:
            return False

    def pause(self):
        self._next_op()
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

        # 조기 pause + 반복 seek는 VLC preroll을 방해해 첫 프레임을 늦춘다
        # (실측: 블라인드 freeze 1.22s vs vout 감지 후 freeze 0.86s).
        # vout(첫 프레임 렌더) 감지 즉시 1회 freeze한다. vout 미보고 파일은
        # CUE 완료 경로의 _force_cue_position(0.90s fallback)이 pause를 걸고,
        # 그마저 실패하는 비정상 경우를 위한 최후 음소거 가드만 1.4s에 둔다.
        preroll_t0 = time.monotonic()

        def _preroll_tick():
            if not self._is_current_op(seq):
                return
            elapsed = time.monotonic() - preroll_t0
            if self.has_video_output():
                log.info(f'vlc preroll first frame at {elapsed:.2f}s')
                # 상태 타임라인 기록 — 진단 ZIP만으로 현장 CUE 성능(느린 스토리지 등) 판별용
                record_state_event('cue', 'first frame rendered', elapsed=f'{elapsed:.2f}s')
                _freeze('freeze-vout')
                QTimer.singleShot(140, lambda: _freeze('freeze-settle'))
                return
            if elapsed >= 1.4:
                log.debug(f'vlc preroll guard freeze without vout at {elapsed:.2f}s')
                record_state_event('cue', 'preroll guard freeze without vout', elapsed=f'{elapsed:.2f}s')
                _freeze('freeze-guard')
                return
            QTimer.singleShot(40, _preroll_tick)

        QTimer.singleShot(40, _preroll_tick)

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
            self._selected_audio_channel = max(1, min(16, int(parsed)))
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
