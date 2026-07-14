"""
transcode_coordinator.py — 비직접재생 파일 변환/캐시 조정자
VideoPanel에서 분리된 TranscodeCoordinator: CUE용 트랜스코드 시작/스왑, 임시파일 캐시 정리(LRU).
DIRECT_VLC_EXTS(변환 불필요 확장자)의 원 소유 모듈.
"""
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer

from constants import (
    log, TMP_DIR, _path_size,
    friendly_error_text, friendly_error_title,
)
from threads import TranscodeThread

DIRECT_VLC_EXTS = {'.mxf', '.mp4'}


class TranscodeCoordinator:
    """panel(VideoPanel) 역참조를 갖고 트랜스코드/사전변환/캐시를 조정한다."""
    def __init__(self, panel):
        self._panel = panel
        self._tc_thread = None
        self._tc_cache = {}
        self._tc_cache_order = []

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
                return (str(target), _path_size(target))
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
                size = _path_size(target)
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

    def _retire_tc(self):
        """_tc_thread를 abort 후 dead_threads로 이동.
        finished 시그널로 완전 종료 시점에 자동 제거 → isRunning() 타이밍 충돌 방지"""
        if self._tc_thread:
            t = self._tc_thread
            self._tc_thread = None
            # finished 시그널: 스레드가 완전히 종료된 시점에 dead_threads에서 제거
            def _on_finished(thread=t):
                try:
                    self._panel._dead_threads.remove(thread)
                    log.debug(f'dead_thread 제거: {thread} (finished)')
                except ValueError:
                    pass  # 이미 제거됐으면 무시
            t.finished.connect(_on_finished)
            self._panel._track_dead_thread(t)
            t.abort()   # abort는 finished 시그널 연결 후 호출 (순서 중요)

    def start_transcode_for_cue(self, filepath, load_seq):
        """CUE — 캐시 확인 후 즉시 또는 변환 후 player에 올림 (load_file 비직접재생 경로)"""
        panel = self._panel
        cache = getattr(self, '_tc_cache', {})
        cached_tmp = cache.get(filepath)
        if cached_tmp and '_preview' in Path(cached_tmp).stem:
            del cache[filepath]
            cached_tmp = None
        if cached_tmp and Path(cached_tmp).exists():
            # 사전 변환 캐시 있음 → 즉시 올림
            panel.empty_label.setText('⏳  로딩 중...')
            panel._empty_proxy.show(); panel._video_item.hide()
            QTimer.singleShot(50, lambda t=cached_tmp, fp=filepath, s=load_seq: self._on_transcode_ready(t, fp, s))
        else:
            # 캐시 없음 → 변환 시작
            ext = Path(filepath).suffix.lower()
            msg = '⏳  파일 변환 중...' if ext in ('.mp4','.mov','.m4v','.mkv','.avi','.mts','.m2ts') \
                  else "⏳  영상 변환 중...\n잠시만 기다려주세요"
            panel.empty_label.setText(msg)
            panel._empty_proxy.show(); panel._video_item.hide()
            self._tc_thread = TranscodeThread(filepath, panel._get_selected_ch_pairs())
            self._tc_thread.ready.connect(lambda tmp, fp=filepath, s=load_seq: self._on_transcode_ready(tmp, fp, s))
            self._tc_thread.ready_full.connect(lambda tmp, fp=filepath, s=load_seq: self._on_transcode_full(tmp, fp, s))
            # 진행률 표시
            panel.prog_ai.setRange(0, 100)
            panel.prog_ai.setValue(0)
            panel.prog_ai.show()
            def _tc_progress(pct, fp=filepath, s=load_seq):
                if not panel._load_is_current(s, fp):
                    return
                panel.prog_ai.setValue(pct)
                if pct < 100:
                    panel.ai_lbl.setText(f'⏳ 변환 중... {pct}%')
                else:
                    panel.ai_lbl.setText('✓ 변환 완료')
                    panel.prog_ai.hide()
                    panel.prog_ai.setRange(0, 0)  # indeterminate로 복원
            self._tc_thread.progress.connect(_tc_progress)
            def _tc_err(msg, el=panel.empty_label, ai=panel.ai_lbl, fp=filepath, s=load_seq):
                if not panel._load_is_current(s, fp):
                    log.debug(f'stale transcode error ignored: {Path(fp).name}')
                    return
                friendly = friendly_error_text('ffmpeg_transcode', msg, fp)
                el.setText(f'⚠ {friendly}')
                ai.setText(f'⚠ {friendly_error_title("ffmpeg_transcode", msg, fp)}')
                panel.prog_ai.hide(); panel.prog_ai.setRange(0, 0)
                # 완료 선언이 ready 시점으로 이동 — 변환 실패 시 여기서 로딩 잠금 해제
                panel._set_loading_state(False)
            self._tc_thread.error.connect(_tc_err)
            self._tc_thread.start()

    def _on_transcode_ready(self, tmp, expected_file=None, load_seq=None):
        panel = self._panel
        if expected_file and not panel._load_is_current(load_seq, expected_file):
            log.debug(f'stale transcode ready ignored: {Path(expected_file).name}')
            return
        # CUE 완료 선언이 이 슬롯으로 이동해 로드 중(_loading)에도 실행돼야 한다 —
        # 스테일 차단은 위의 load_seq 가드가 담당한다.
        if not panel.cur_file: return
        import os
        if not os.path.exists(tmp): return
        try:
            is_preview = 'preview' in tmp
            panel._using_preview = is_preview
            panel.player.setSource(QUrl.fromLocalFile(tmp))
            panel._empty_proxy.hide(); panel._video_item.show()
            panel.player.pause()
            QTimer.singleShot(120, lambda: panel._show_cue_first_frame(0))
            panel.meter_ctrl.prepare_file(panel.cur_file)
            # 소스가 실제로 올라온 지금이 CUE 완료 시점 — 조기 PLAY로 인한 재생 실패 방지.
            panel._complete_transcode_cue_load(expected_file or panel.cur_file, preview=is_preview)
        except Exception as e:
            # setSource 실패해도 프로그램 유지
            panel.ai_lbl.setText(f'⚠ {friendly_error_title("player_load", e, panel.cur_file)}')
            panel._set_loading_state(False)
            log.error(f'transcode ready load error: {e}')

    def _on_transcode_full(self, tmp, expected_file=None, load_seq=None):
        panel = self._panel
        if expected_file and not panel._load_is_current(load_seq, expected_file):
            log.debug(f'stale transcode full ignored: {Path(expected_file).name}')
            return
        if not panel.cur_file: return
        import os
        if not os.path.exists(tmp): return
        try:
            panel._using_preview = False
            pos = panel.player.position()
            was_playing = panel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            panel.player.pause()
            panel.player.setSource(QUrl.fromLocalFile(tmp))
            panel._empty_proxy.hide(); panel._video_item.show()
            panel.player.pause()
            QTimer.singleShot(200, lambda: panel.player.setPosition(pos))
            if was_playing:
                QTimer.singleShot(350, lambda: panel.player.play())
            else:
                QTimer.singleShot(350, lambda p=pos: panel._show_cue_first_frame(p))
            if panel.cur_file:
                if not hasattr(self, '_tc_cache'):
                    self._tc_cache = {}
                if not hasattr(self, '_tc_cache_order'):
                    self._tc_cache_order = []
                self._tc_cache[panel.cur_file] = tmp
                if panel.cur_file not in self._tc_cache_order:
                    self._tc_cache_order.append(panel.cur_file)
                self._evict_tc_cache()
            # 프리뷰 없이 ready_full만 오는 경우에도 완료가 보장되도록 여기서도 선언
            # (_emit_file_loaded_once 게이트로 중복 발행은 방지됨).
            panel._complete_transcode_cue_load(expected_file or panel.cur_file)
        except Exception as e:
            panel.ai_lbl.setText(f'⚠ {friendly_error_title("player_load", e, panel.cur_file)}')
            panel._set_loading_state(False)
            log.error(f'transcode full swap error: {e}')
