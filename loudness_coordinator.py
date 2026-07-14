"""
loudness_coordinator.py — 라우드니스(LKFS) 분석 스케줄링/캐시 조정자
VideoPanel에서 분리된 LoudnessCoordinator: 재생 우선 스케줄링, 결과 캐시, 스레드 수명 관리
"""
import math
import time
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtMultimedia import QMediaPlayer

from constants import (
    log, format_missing_runtime_tools, friendly_error_title,
    record_state_event, _path_size, _path_mtime_ns,
)
from threads import LoudnessAnalyzeThread


class LoudnessCoordinator:
    """panel(VideoPanel) 역참조를 갖고 라우드니스 분석을 조정한다."""
    def __init__(self, panel):
        self._panel = panel
        self._loudness_thread = None
        self._loudness_cache = {}
        self._loudness_cache_order = []
        self._loudness_cache_limit = 32
        self._loudness_seq = 0
        self._loudness_schedule_seq = 0

    def is_loudness_running(self):
        return bool(self._loudness_thread and self._loudness_thread.isRunning())

    def _retire_loudness_analysis(self):
        self._loudness_schedule_seq += 1
        self._loudness_seq += 1
        if not self._loudness_thread:
            return
        t = self._loudness_thread
        self._loudness_thread = None

        def _on_finished(thread=t):
            try:
                self._panel._dead_threads.remove(thread)
            except ValueError:
                pass

        try:
            t.finished.connect(_on_finished)
        except Exception:
            pass
        self._panel._track_dead_thread(t)
        try:
            t.abort()
        except Exception as e:
            log.debug(f'loudness abort: {e}')

    def _loudness_cache_key(self, filepath):
        try:
            path = Path(filepath)
            size = _path_size(path)
            mtime_ns = _path_mtime_ns(path)
            if not size and not mtime_ns:
                return str(filepath)
            return f'{path.resolve()}|{size}|{mtime_ns}'
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
        limit = max(1, self._panel._safe_int_value(getattr(self, '_loudness_cache_limit', 32), 32))
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
        p = self._panel._video_file_path(filepath)
        if not p:
            return
        filepath = str(p)
        file_name = p.name
        stream_count = max(0, self._panel._safe_int_value(self._panel.cur_info.get('audio_stream_count', 0), 0))
        ch_count = max(0, self._panel._safe_int_value(self._panel.cur_info.get('channels', 0), 0))
        if stream_count <= 0 and ch_count <= 0:
            self._panel.meter_ctrl.set_loudness_analysis_error('NO AUD')
            return
        missing = format_missing_runtime_tools(['FFmpeg'])
        if missing:
            self._panel.meter_ctrl.set_loudness_analysis_error('NO FF')
            title = missing.splitlines()[0]
            self._panel.status_changed.emit(f'  ⚠ {title}')
            log.warning(f'loudness analysis blocked: {missing}')
            return

        duration = max(0.0, self._panel._safe_float_value(self._panel.cur_info.get('duration', self._panel.duration), 0.0))
        if duration > 300.0:
            self._panel.meter_ctrl.set_loudness_analysis_pending('LIVE')
            log.info(
                f'loudness full-file auto scan skipped for long file: '
                f'{file_name} duration={duration:.1f}s'
            )
            record_state_event('loudness', 'full scan skipped', file=file_name, duration=f'{duration:.1f}s')
            return

        key = self._loudness_cache_key(filepath)
        cached = self._loudness_cache.get(key)
        if cached:
            self._touch_loudness_cache(key)
            self._apply_loudness_result(filepath, cached, from_cache=True)
            return

        self._panel.meter_ctrl.set_loudness_analysis_pending('SCAN')
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
            if fp != self._panel.cur_file:
                return
            text = 'SCAN'
            if '%' in msg:
                pct = msg.rsplit(' ', 1)[-1]
                text = pct[:8]
            self._panel.meter_ctrl.set_loudness_analysis_pending(text)

        def _done(result, fp=file_at_start, cache_key=key, thread=t, s=seq):
            if s != self._loudness_seq:
                log.debug(f'stale loudness result ignored: {self._panel._display_file_name(fp)}')
                return
            if self._loudness_thread is thread:
                self._loudness_thread = None
            normalized = self._normalize_loudness_result(result)
            if normalized is None:
                if fp == self._panel.cur_file:
                    self._panel.meter_ctrl.set_loudness_analysis_error('ERR')
                    self._panel.status_changed.emit(f'  ⚠ 라우드니스 결과 오류 — {self._panel._display_file_name(fp)}')
                return
            self._store_loudness_cache(cache_key, normalized)
            self._apply_loudness_result(fp, normalized)

        def _error(err, fp=file_at_start, thread=t, s=seq):
            if s != self._loudness_seq:
                log.debug(f'stale loudness error ignored: {self._panel._display_file_name(fp)}')
                return
            if self._loudness_thread is thread:
                self._loudness_thread = None
            if fp == self._panel.cur_file:
                self._panel.meter_ctrl.set_loudness_analysis_error('ERR')
                self._panel.status_changed.emit(
                    f'  ⚠ {friendly_error_title("loudness", err, fp)} — {self._panel._display_file_name(fp)}')
            log.error(f'LoudnessAnalyze UI error: {err}')

        t.progress.connect(_progress)
        t.finished.connect(_done)
        t.error.connect(_error)
        t.start()
        log.info(f'loudness auto analysis started: {file_name}')

    def _schedule_loudness_analysis(self, filepath, delay_ms=1500):
        """Keep full-file FFmpeg scans away from the first playback frames."""
        p = self._panel._video_file_path(filepath)
        if not p or str(p) != self._panel.cur_file:
            return
        filepath = str(p)
        info = self._panel.cur_info if isinstance(self._panel.cur_info, dict) else {}
        duration = max(0.0, self._panel._safe_float_value(info.get('duration', self._panel.duration), 0.0))
        source_count = self._panel._audio_source_count_from_info(info)
        cache_key = self._loudness_cache_key(filepath)
        if source_count <= 0 or duration > 300.0 or self._loudness_cache.get(cache_key):
            self._start_loudness_analysis(filepath)
            return

        self._retire_loudness_analysis()
        seq = self._loudness_schedule_seq
        file_name = p.name
        self._panel.meter_ctrl.set_loudness_analysis_pending('WAIT')

        def _run():
            if seq != self._loudness_schedule_seq or filepath != self._panel.cur_file:
                return
            if not getattr(self._panel, '_metadata_ready', False):
                return
            if self._panel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                started = float(getattr(self._panel, '_play_started_at', 0.0) or 0.0)
                age = max(0.0, time.monotonic() - started) if started else 0.0
                settle_sec = 2.5
                if age < settle_sec:
                    remaining_ms = max(100, int(round((settle_sec - age) * 1000.0)))
                    log.debug(
                        f'loudness scan deferred for playback startup: '
                        f'{file_name} remaining={remaining_ms}ms'
                    )
                    QTimer.singleShot(remaining_ms, _run)
                    return
            self._start_loudness_analysis(filepath)

        QTimer.singleShot(max(0, int(delay_ms)), _run)
        log.info(f'loudness scan scheduled: {file_name} delay={max(0, int(delay_ms))}ms')

    def _apply_loudness_result(self, filepath, result, from_cache=False):
        if filepath != self._panel.cur_file:
            return
        result = self._normalize_loudness_result(result)
        if result is None:
            self._panel.meter_ctrl.set_loudness_analysis_error('ERR')
            self._panel.status_changed.emit(f'  ⚠ 라우드니스 결과 오류 — {self._panel._display_file_name(filepath)}')
            return
        integrated = result.get('integrated')
        self._panel.meter_ctrl.set_loudness_analysis_result(integrated)
        src = '캐시' if from_cache else '완료'
        self._panel.status_changed.emit(f'  ▌LKFS {src}  I {integrated:.1f}  |  1/2CH')
