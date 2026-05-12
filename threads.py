"""
threads.py — 백그라운드 스레드
TranscodeThread, AudioAnalyzeThread, LoudnessAnalyzeThread, BlackDetectThread
"""

__all__ = [
    'ProbeThread',
    'RuntimeWarmupThread',
    'TranscodeThread',
    'AudioAnalyzeThread',
    'LoudnessAnalyzeThread',
    'BlackDetectThread',
]
import sys, re, json, subprocess, threading as _th, hashlib, math, os, time
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from constants import (
    FFMPEG, FFPROBE, FFPLAY, TMP_DIR, VIDEO_EXTS, log,
    register_child_process, unregister_child_process, terminate_child_process,
    acquire_heavy_analysis_slot, release_heavy_analysis_slot,
)
from db_models import sec_to_tc, frames_to_tc, probe as probe_media

class ProbeThread(QThread):
    probed = pyqtSignal(dict, float)  # info, elapsed seconds
    error = pyqtSignal(str, float)

    def __init__(self, fp):
        super().__init__()
        self.fp = fp
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        started = time.monotonic()
        try:
            info = probe_media(self.fp)
            elapsed = time.monotonic() - started
            if self._abort:
                return
            self.probed.emit(info, elapsed)
        except Exception as e:
            elapsed = time.monotonic() - started
            if not self._abort:
                self.error.emit(str(e), elapsed)

class RuntimeWarmupThread(QThread):
    completed = pyqtSignal(dict)

    def __init__(self, recent_files=None):
        super().__init__()
        self.recent_files = list(recent_files or [])
        self._abort = False

    def abort(self):
        self._abort = True

    def _run_version(self, name, command):
        if self._abort:
            return None
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [command, '-version'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=0x08000000 if os.name == 'nt' else 0,
            )
            return {'ok': proc.returncode == 0, 'elapsed': time.monotonic() - started}
        except Exception as e:
            return {'ok': False, 'elapsed': time.monotonic() - started, 'error': str(e)}

    def run(self):
        started = time.monotonic()
        result = {'tools': {}, 'recent_probe': None, 'elapsed': 0.0}
        try:
            for name, command in (
                ('ffprobe', FFPROBE),
                ('ffmpeg', FFMPEG),
                ('ffplay', FFPLAY),
            ):
                state = self._run_version(name, command)
                if state is not None:
                    result['tools'][name] = state
            for fp in self.recent_files[:3]:
                if self._abort:
                    return
                try:
                    p = Path(fp)
                    if not p.exists() or p.suffix.lower() not in VIDEO_EXTS:
                        continue
                    probe_started = time.monotonic()
                    info = probe_media(str(p))
                    result['recent_probe'] = {
                        'file': p.name,
                        'ok': bool(info),
                        'elapsed': time.monotonic() - probe_started,
                    }
                    break
                except Exception as e:
                    result['recent_probe'] = {
                        'file': str(fp),
                        'ok': False,
                        'elapsed': 0.0,
                        'error': str(e),
                    }
                    break
        finally:
            result['elapsed'] = time.monotonic() - started
            if not self._abort:
                self.completed.emit(result)

class TranscodeThread(QThread):
    ready    = pyqtSignal(str)   # 프리뷰 준비
    ready_full = pyqtSignal(str)  # 전체 변환 완료
    progress = pyqtSignal(int)    # 변환 진행률 0~100
    error    = pyqtSignal(str)

    def __init__(self, fp, ch_pair=(1,2)):
        super().__init__()
        self.fp      = fp
        self.ch_pair = ch_pair
        import hashlib as _hl
        ch_key = str(ch_pair).replace(' ','')
        uid = _hl.md5(f"{fp}_{ch_key}".encode()).hexdigest()[:8]
        self._fast_remux = Path(fp).suffix.lower() == '.mxf'
        ext = '.mov' if self._fast_remux else '.mp4'
        self.tmp         = str(TMP_DIR / f"{uid}{ext}")
        self.tmp_preview = str(TMP_DIR / f"{uid}_preview.mp4")
        self._abort = False
        self._proc  = None

    def abort(self):
        self._abort = True
        if self._proc and self._proc.poll() is None:
            terminate_child_process(self._proc, 'transcode ffmpeg')

    def _build_filter(self, audio_streams, pairs):
        n_streams  = len(audio_streams)
        total_ch   = sum(audio_streams) if audio_streams else 2
        multi_mono = n_streams > 1 and all(c == 1 for c in audio_streams)
        if multi_mono:
            ins   = "".join(f"[0:a:{i}]" for i in range(n_streams))
            merge = f"{ins}amerge=inputs={n_streams}[merged]"
            if len(pairs) == 1:
                c1=min(pairs[0][0]-1,total_ch-1); c2=min(pairs[0][1]-1,total_ch-1)
                return f"{merge};[merged]pan=stereo|c0=c{c1}|c1=c{c2}[aout]"
            pans = []; [pans.append(f"[merged]pan=stereo|c0=c{min(p1-1,total_ch-1)}|c1=c{min(p2-1,total_ch-1)}[ch{i}]") for i,(p1,p2) in enumerate(pairs)]
            mix = "".join(f"[ch{i}]" for i in range(len(pairs)))
            return f"{merge};{chr(59).join(pans)};{mix}amix=inputs={len(pairs)}:normalize=0[aout]"
        else:
            if len(pairs) == 1:
                c1=min(pairs[0][0]-1,total_ch-1); c2=min(pairs[0][1]-1,total_ch-1)
                return f"[0:a]pan=stereo|c0=c{c1}|c1=c{c2}[aout]"
            pans = [f"[0:a]pan=stereo|c0=c{min(p1-1,total_ch-1)}|c1=c{min(p2-1,total_ch-1)}[ch{i}]" for i,(p1,p2) in enumerate(pairs)]
            mix = "".join(f"[ch{i}]" for i in range(len(pairs)))
            return ";".join(pans) + f";{mix}amix=inputs={len(pairs)}:normalize=0[aout]"

    def _make_cmd(self, out_path, audio_fc, duration=None):
        fc = f"[0:v]scale=-2:720[vout];{audio_fc}"
        cmd = [FFMPEG,"-y","-i",self.fp]
        if duration:
            cmd += ["-t", str(duration)]
        cmd += ["-filter_complex", fc,
                "-map","[vout]","-map","[aout]",
                "-vcodec","libx264","-preset","ultrafast","-crf","28","-threads","0",
                "-acodec","aac","-ac","2","-b:a","128k",
                out_path]
        return cmd

    def _make_remux_cmd(self, out_path, audio_fc):
        return [FFMPEG, "-y", "-i", self.fp,
                "-filter_complex", audio_fc,
                "-map", "0:v:0", "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-ac", "2", "-b:a", "192k",
                "-movflags", "+faststart",
                out_path]

    def _run_ffmpeg(self, cmd, total_sec=0, emit_error=True):
        """FFmpeg 실행 + 진행률 파싱 + stderr 안전 처리"""
        import threading as _th, re as _re
        try:
            self._proc = register_child_process(subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=0x08000000
            ), 'transcode ffmpeg')
            # stderr를 별도 스레드에서 읽음 → 버퍼 블록 방지 (버그 3번 해결)
            self._stderr_buf = []
            def _read_stderr():
                for line in self._proc.stderr:
                    try:
                        decoded = line.decode('utf-8','replace').strip()
                        self._stderr_buf.append(decoded)
                        # time= HH:MM:SS.ms 파싱 → 진행률
                        m = _re.search(r'time=(\d+):(\d+):([\d.]+)', decoded)
                        if m and total_sec > 0:
                            elapsed = (int(m.group(1))*3600
                                       + int(m.group(2))*60
                                       + float(m.group(3)))
                            pct = min(99, int(elapsed / total_sec * 100))
                            self.progress.emit(pct)
                    except Exception as e: log.debug(f'progress parse: {e}')
            t = _th.Thread(target=_read_stderr, daemon=True)
            t.start()
            while True:
                if self._abort:
                    terminate_child_process(self._proc, 'transcode ffmpeg')
                    return False
                if self._proc.poll() is not None:
                    break
                self.msleep(100)
            t.join(timeout=2)
            if self._proc.returncode != 0 and not self._abort:
                err_tail = ' | '.join(self._stderr_buf[-3:])
                if emit_error:
                    self.error.emit(f"변환 실패 (rc={self._proc.returncode}): {err_tail}")
                return False
            return True
        except Exception as e:
            if not self._abort:
                self.error.emit(str(e))
            return False
        finally:
            unregister_child_process(self._proc)

    def run(self):
        try:
            import json as _j
            pr = subprocess.run(
                [FFPROBE,"-v","quiet","-print_format","json","-show_streams",self.fp],
                capture_output=True, text=True, timeout=15
            )
            audio_streams = []
            if pr.returncode == 0:
                for s in _j.loads(pr.stdout).get("streams",[]):
                    if s.get("codec_type") == "audio":
                        audio_streams.append(s.get("channels", 1))

            pairs    = self.ch_pair if isinstance(self.ch_pair, list) else [self.ch_pair]
            audio_fc = self._build_filter(audio_streams, pairs)

            # MXF는 비디오 재인코딩 대신 컨테이너 remux를 먼저 시도한다.
            if self._fast_remux:
                self.progress.emit(0)
                if self._run_ffmpeg(self._make_remux_cmd(self.tmp, audio_fc), emit_error=False):
                    if self._abort: return
                    self.progress.emit(100)
                    self.ready_full.emit(self.tmp)
                    return
                if self._abort: return
                log.warning('fast remux failed; falling back to H.264 transcode')

            # 1단계: 프리뷰를 먼저 만들어 전체 변환 전에도 재생 가능하게 함
            if not self._run_ffmpeg(self._make_cmd(self.tmp_preview, audio_fc, duration=30)): return
            if self._abort: return
            self.ready.emit(self.tmp_preview)

            # 2단계: 전체 변환 → 완료 후 교체
            total_sec = 0
            try:
                import json as _j2
                pr2 = subprocess.run(
                    [FFPROBE,'-v','quiet','-print_format','json',
                     '-show_format', self.fp],
                    capture_output=True, text=True, timeout=10)
                if pr2.returncode == 0:
                    total_sec = float(
                        _j2.loads(pr2.stdout).get('format',{}).get('duration',0))
            except Exception as e:
                log.debug(f'duration probe: {e}')
            self.progress.emit(0)
            if not self._run_ffmpeg(self._make_cmd(self.tmp, audio_fc), total_sec): return
            if self._abort: return
            self.progress.emit(100)
            self.ready_full.emit(self.tmp)

        except Exception as e:
            if not self._abort:
                self.error.emit(str(e))

# ══════════════════════════════════════════════════════════
# 오디오 분석 스레드 (뮤트감지)
# ══════════════════════════════════════════════════════════
class AudioAnalyzeThread(QThread):
    """1/2CH 오디오 레벨 인덱스를 캐시하고 뮤트 구간을 빠르게 계산"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)   # {'mutes': [...], 'peaks': {...}, 'ch_count': int}
    error    = pyqtSignal(str)

    def __init__(self, fp, fps, noise_threshold=-50, min_duration=2.0, df=None, tc_offset_frames=0):
        super().__init__()
        self.fp              = fp
        self.fps             = fps
        self.df              = df
        self.tc_offset_frames = int(tc_offset_frames or 0)
        self.noise_threshold = noise_threshold   # dB (-50 기본)
        self.min_duration    = min_duration      # 초
        self._abort          = False
        self._proc           = None

    def _tc(self, sec):
        return sec_to_tc(sec, self.fps, self.df, self.tc_offset_frames)

    def abort(self):
        self._abort = True
        if self._proc and self._proc.poll() is None:
            terminate_child_process(self._proc, 'audio analyze ffmpeg')

    def _run_ffmpeg_capture(self, cmd, timeout=300):
        self._proc = register_child_process(subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=0x08000000, encoding='utf-8', errors='replace'), 'audio analyze ffmpeg')
        try:
            waited = 0
            while self._proc.poll() is None:
                if self._abort:
                    self.abort()
                    return ''
                if waited >= timeout * 10:
                    self.abort()
                    raise TimeoutError('FFmpeg audio analyze timeout')
                self.msleep(100)
                waited += 1
            out, err = self._proc.communicate(timeout=2)
            if self._proc.returncode != 0 and not self._abort:
                log.warning(f'audio analyze ffmpeg rc={self._proc.returncode}: {err[-500:]}')
            return err or ''
        finally:
            unregister_child_process(self._proc)

    def _audio_12_filter(self, audio_streams, out_label='aud'):
        """분석 속도를 위해 QC 기준 채널인 1/2CH만 추출한다."""
        if not audio_streams:
            return f'[0:a:0]anull[{out_label}]', 2
        first_ch = int(audio_streams[0] or 1)
        if first_ch >= 2:
            return f'[0:a:0]pan=stereo|c0=c0|c1=c1[{out_label}]', 2
        if len(audio_streams) >= 2:
            return f'[0:a:0][0:a:1]amerge=inputs=2[{out_label}]', 2
        return f'[0:a:0]anull[{out_label}]', 1

    def _cache_path(self, source_ch_count, basis):
        st = os.stat(self.fp)
        key = hashlib.sha1(
            f'{self.fp}|{st.st_size}|{st.st_mtime_ns}|{source_ch_count}|{basis}|sr8000|win0.1|v2'
            .encode('utf-8', 'ignore')
        ).hexdigest()
        cache_dir = TMP_DIR / 'audio_index'
        cache_dir.mkdir(exist_ok=True)
        return cache_dir / f'{key}.json'

    def _load_index_cache(self, path):
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('version') != 2:
                return None
            levels = data.get('levels_db')
            if not isinstance(levels, list):
                return None
            return data
        except Exception as e:
            log.debug(f'audio index cache load: {e}')
            return None

    def _save_index_cache(self, path, data):
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            log.debug(f'audio index cache save: {e}')

    def _build_level_index(self, base_fc, ch_count, source_ch_count, basis):
        import numpy as _np
        sample_rate = 8000
        window_sec = 0.1
        window_frames = int(sample_rate * window_sec)
        bytes_per_window = window_frames * ch_count * 2
        raw_fc = f'{base_fc};[aud]aresample={sample_rate}[aout]'
        cmd = [
            FFMPEG, '-hide_banner', '-nostats', '-loglevel', 'error',
            '-threads', '0',
            '-i', self.fp, '-vn',
            '-filter_complex', raw_fc,
            '-map', '[aout]',
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
            '-ar', str(sample_rate),
            '-ac', str(ch_count),
            'pipe:1'
        ]
        slot_label = 'audio index'
        if not acquire_heavy_analysis_slot(slot_label):
            raise RuntimeError('다른 분석 작업이 진행 중입니다. 잠시 후 다시 시도하세요.')
        try:
            self._proc = register_child_process(subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=0x08000000), 'audio index ffmpeg')

            levels = []
            buf = bytearray()
            processed_windows = 0
            next_emit_sec = 0.0
            assert self._proc.stdout is not None
            while True:
                if self._abort:
                    self.abort()
                    return []
                chunk = self._proc.stdout.read(262144)
                if not chunk:
                    break
                buf.extend(chunk)
                while len(buf) >= bytes_per_window:
                    block = bytes(buf[:bytes_per_window])
                    del buf[:bytes_per_window]
                    arr = _np.frombuffer(block, dtype=_np.int16).astype(_np.float32)
                    if ch_count > 1:
                        arr = arr.reshape(-1, ch_count)
                        rms = _np.sqrt(_np.mean(arr * arr, axis=0)).max()
                    else:
                        rms = float(_np.sqrt(_np.mean(arr * arr)))
                    db = 20.0 * math.log10(max(float(rms) / 32768.0, 1e-12))
                    levels.append(round(db, 1))
                    processed_windows += 1
                    pos_sec = processed_windows * window_sec
                    if pos_sec >= next_emit_sec:
                        self.progress.emit(
                            f'{source_ch_count}ch 파일 — {basis} 100ms 레벨 인덱스 생성 중... {self._tc(pos_sec)}')
                        next_emit_sec += 30.0

            if len(buf) >= ch_count * 2:
                usable = len(buf) - (len(buf) % (ch_count * 2))
                arr = _np.frombuffer(bytes(buf[:usable]), dtype=_np.int16).astype(_np.float32)
                if arr.size:
                    if ch_count > 1:
                        arr = arr.reshape(-1, ch_count)
                        rms = _np.sqrt(_np.mean(arr * arr, axis=0)).max()
                    else:
                        rms = float(_np.sqrt(_np.mean(arr * arr)))
                    db = 20.0 * math.log10(max(float(rms) / 32768.0, 1e-12))
                    levels.append(round(db, 1))

            err = b''
            try:
                err = self._proc.stderr.read() if self._proc.stderr else b''
            except Exception:
                pass
            rc = self._proc.wait()
            if rc != 0 and not self._abort:
                tail = err.decode('utf-8', 'replace')[-500:]
                raise RuntimeError(f'오디오 인덱스 생성 실패 (rc={rc}): {tail}')
            return levels
        finally:
            unregister_child_process(self._proc)
            release_heavy_analysis_slot(slot_label)

    def _mutes_from_levels(self, levels, window_sec):
        mutes = []
        start_i = None
        for i, db in enumerate(levels):
            silent = db <= self.noise_threshold
            if silent and start_i is None:
                start_i = i
            elif not silent and start_i is not None:
                self._append_mute(mutes, start_i, i, window_sec)
                start_i = None
        if start_i is not None:
            self._append_mute(mutes, start_i, len(levels), window_sec)
        return mutes

    def _append_mute(self, mutes, start_i, end_i, window_sec):
        start_s = start_i * window_sec
        end_s = end_i * window_sec
        dur_s = end_s - start_s
        if dur_s + 1e-9 < self.min_duration:
            return
        mutes.append({
            'start'   : start_s,
            'end'     : end_s,
            'duration': dur_s,
            'tc_start': self._tc(start_s),
            'tc_end'  : self._tc(end_s),
        })

    def run(self):
        import re as _re, json as _json
        try:
            self.progress.emit('오디오 분석 준비 중...')

            # ── 1단계: 채널 수 확인 (ffprobe) ──
            pr = subprocess.run(
                [FFPROBE,'-v','quiet','-print_format','json','-show_streams', self.fp],
                capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            audio_streams = []
            try:
                for st in _json.loads(pr.stdout).get('streams',[]):
                    if st.get('codec_type') == 'audio':
                        audio_streams.append(int(st.get('channels', 1) or 1))
            except Exception as e: log.debug(f'audio ch parse: {e}')
            if not audio_streams:
                audio_streams = [2]
            source_ch_count = sum(audio_streams)
            base_fc, ch_count = self._audio_12_filter(audio_streams, 'aud')
            basis = '1/2CH' if ch_count >= 2 else '1CH'

            cache_path = self._cache_path(source_ch_count, basis)
            cache = self._load_index_cache(cache_path)
            cache_hit = cache is not None
            if cache_hit:
                self.progress.emit(f'{basis} 레벨 인덱스 캐시 사용 — 뮤트 구간 계산 중...')
                levels = cache['levels_db']
                window_sec = float(cache.get('window_sec', 0.1))
            else:
                self.progress.emit(f'{source_ch_count}ch 파일 — {basis} 레벨 인덱스 생성 중...')
                window_sec = 0.1
                levels = self._build_level_index(base_fc, ch_count, source_ch_count, basis)
                if self._abort:
                    return
                cache = {
                    'version': 2,
                    'filepath': self.fp,
                    'source_ch_count': source_ch_count,
                    'channel_basis': basis,
                    'sample_rate': 8000,
                    'window_sec': window_sec,
                    'levels_db': levels,
                }
                self._save_index_cache(cache_path, cache)

            mutes = self._mutes_from_levels(levels, window_sec)

            mode = '캐시' if cache_hit else '신규 인덱스'
            self.progress.emit(f'완료: 뮤트 {len(mutes)}구간 | {basis} {mode} 기반 검출 완료')
            log.info(f'AudioAnalyze 완료: 뮤트 {len(mutes)}구간, source={source_ch_count}ch, basis={basis}, cache={cache_hit}')
            self.finished.emit({
                'mutes'    : mutes,
                'peaks'    : {},
                'rms'      : {},
                'ch_count' : ch_count,
                'source_ch_count': source_ch_count,
                'channel_basis': basis,
                'cache_hit': cache_hit,
                'index_window_sec': window_sec,
                'threshold': self.noise_threshold,
                'min_dur'  : self.min_duration,
            })

        except Exception as e:
            log.error(f'AudioAnalyzeThread 오류: {e}')
            self.error.emit(str(e))


class LoudnessAnalyzeThread(QThread):
    """파일 전체 1/2CH 기준 EBU R128 Integrated/LRA/True Peak 분석"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    NUM_RE = r'([+-]?(?:\d+(?:\.\d*)?|\.\d+|inf|nan|-inf))'

    def __init__(self, fp, audio_stream_count=0, channel_count=2, duration=0.0):
        super().__init__()
        self.fp = fp
        self.audio_stream_count = max(0, int(audio_stream_count or 0))
        self.channel_count = max(1, int(channel_count or 2))
        try:
            self.duration = max(0.0, float(duration or 0.0))
        except Exception:
            self.duration = 0.0
        self._abort = False
        self._proc = None

    def abort(self):
        self._abort = True
        if self._proc and self._proc.poll() is None:
            terminate_child_process(self._proc, 'loudness analyze ffmpeg', timeout=0.2)

    def _channel_filter(self):
        if self.audio_stream_count > 1:
            if self.audio_stream_count >= 2:
                return '[0:a:0][0:a:1]amerge=inputs=2[aud]'
            return '[0:a:0]anull[aud]'
        if self.channel_count >= 2:
            return '[0:a:0]pan=stereo|c0=c0|c1=c1[aud]'
        return '[0:a:0]anull[aud]'

    def _float_or_none(self, value):
        try:
            parsed = float(value)
        except Exception:
            return None
        return parsed if math.isfinite(parsed) else None

    def _parse_summary(self, text):
        summary_idx = text.rfind('Summary:')
        summary = text[summary_idx:] if summary_idx >= 0 else text
        integrated = None
        lra = None
        true_peak = None

        m = re.search(
            rf'Integrated loudness:\s*.*?I:\s*{self.NUM_RE}\s*LUFS',
            summary, re.IGNORECASE | re.DOTALL
        )
        if m:
            integrated = self._float_or_none(m.group(1))
        m = re.search(
            rf'Loudness range:\s*.*?LRA:\s*{self.NUM_RE}\s*LU',
            summary, re.IGNORECASE | re.DOTALL
        )
        if m:
            lra = self._float_or_none(m.group(1))
        m = re.search(
            rf'True peak:\s*.*?Peak:\s*{self.NUM_RE}\s*dBFS',
            summary, re.IGNORECASE | re.DOTALL
        )
        if m:
            true_peak = self._float_or_none(m.group(1))

        if integrated is None:
            values = [
                self._float_or_none(m.group(1))
                for m in re.finditer(rf'\bI:\s*{self.NUM_RE}\s*LUFS', summary, re.IGNORECASE)
            ]
            values = [v for v in values if v is not None]
            integrated = values[-1] if values else None
        if lra is None:
            values = [
                self._float_or_none(m.group(1))
                for m in re.finditer(rf'\bLRA:\s*{self.NUM_RE}\s*LU', summary, re.IGNORECASE)
            ]
            values = [v for v in values if v is not None]
            lra = values[-1] if values else None
        if true_peak is None:
            values = [
                self._float_or_none(m.group(1))
                for m in re.finditer(rf'\bPeak:\s*{self.NUM_RE}\s*dBFS', summary, re.IGNORECASE)
            ]
            values = [v for v in values if v is not None]
            true_peak = values[-1] if values else None

        if integrated is None:
            raise ValueError('Integrated LKFS 값을 찾지 못했습니다')
        return {
            'integrated': integrated,
            'lra': lra,
            'true_peak': true_peak,
            'basis': '1/2CH' if self.channel_count >= 2 or self.audio_stream_count >= 2 else '1CH',
        }

    def run(self):
        tail = []
        try:
            self.progress.emit('라우드니스 전체 분석 준비 중...')
            fc = f'{self._channel_filter()};[aud]ebur128=peak=true[loud]'
            cmd = [
                FFMPEG, '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
                '-threads', '1',
                '-i', self.fp, '-vn',
                '-filter_complex', fc,
                '-map', '[loud]',
                '-f', 'null', '-',
            ]
            slot_label = 'loudness analyze'
            if not acquire_heavy_analysis_slot(slot_label):
                raise RuntimeError('다른 분석 작업이 진행 중입니다. 잠시 후 다시 시도하세요.')
            try:
                self._proc = register_child_process(subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=0x08000000
                ), 'loudness analyze ffmpeg')

                assert self._proc.stderr is not None
                last_emit = 0.0
                start = time.monotonic()
                while True:
                    if self._abort:
                        self.abort()
                        return
                    line = self._proc.stderr.readline()
                    if line:
                        tail.append(line)
                        if len(tail) > 420:
                            tail.pop(0)
                        m = re.search(r't:\s*([\d.]+)', line)
                        if m:
                            pos = float(m.group(1))
                            now = time.monotonic()
                            if now - last_emit >= 1.0:
                                last_emit = now
                                if self.duration > 0:
                                    pct = max(0, min(99, int(pos / self.duration * 100)))
                                    self.progress.emit(f'라우드니스 전체 분석 중... {pct}%')
                                else:
                                    self.progress.emit(f'라우드니스 전체 분석 중... {pos:.1f}s')
                        continue
                    if self._proc.poll() is not None:
                        break
                    if time.monotonic() - start > max(180.0, min(7200.0, self.duration * 6.0 + 120.0)):
                        self.abort()
                        raise TimeoutError('라우드니스 분석 시간 초과')
                    self.msleep(50)

                rc = self._proc.wait()
                if self._abort:
                    return
                text = ''.join(tail)
                if rc != 0:
                    raise RuntimeError(f'FFmpeg loudness 실패 (rc={rc}): {text[-500:]}')
                result = self._parse_summary(text)
                self.progress.emit(
                    f"라우드니스 완료 — I {result['integrated']:.1f} LKFS"
                )
                log.info(
                    f"LoudnessAnalyze 완료: I={result['integrated']:.2f}, "
                    f"LRA={result.get('lra')}, TP={result.get('true_peak')}, "
                    f"basis={result.get('basis')}"
                )
                self.finished.emit(result)
            finally:
                unregister_child_process(self._proc)
                try:
                    release_heavy_analysis_slot('loudness analyze')
                except Exception:
                    pass
        except Exception as e:
            log.error(f'LoudnessAnalyzeThread 오류: {e}')
            if not self._abort:
                self.error.emit(str(e))


class BlackDetectThread(QThread):
    """FFmpeg blackframe으로 1프레임 이상 블랙 화면 구간 검출"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)   # [{'start': float, 'end': float, 'frames': int, ...}]
    error    = pyqtSignal(str)

    def __init__(self, fp, fps, amount=98, threshold=32, df=None, tc_offset_frames=0):
        super().__init__()
        self.fp        = fp
        self.fps       = fps or 29.97
        self.df        = df
        self.tc_offset_frames = int(tc_offset_frames or 0)
        self.amount    = int(amount)
        self.threshold = int(threshold)
        self._abort    = False
        self._proc     = None

    def _tc_from_frame(self, frame):
        return frames_to_tc(frame, self.fps, self.df, self.tc_offset_frames)

    def _tc_from_sec(self, sec):
        return sec_to_tc(sec, self.fps, self.df, self.tc_offset_frames)

    def abort(self):
        self._abort = True
        if self._proc and self._proc.poll() is None:
            terminate_child_process(self._proc, 'black detect ffmpeg')

    def _flush_segment(self, out, seg):
        if not seg:
            return
        frame_dur = 1.0 / self.fps if self.fps > 0 else 0.0
        start = max(0.0, float(seg['start']))
        end_frame_time = max(start, float(seg['end']))
        frames = max(1, int(seg['frames']))
        duration = max(frame_dur, frames * frame_dur)
        out.append({
            'start'     : start,
            'end'       : end_frame_time,
            'duration'  : duration,
            'frames'    : frames,
            'start_frame': int(seg['start_frame']),
            'end_frame' : int(seg['end_frame']),
            'tc_start'  : self._tc_from_frame(seg['start_frame']),
            'tc_end'    : self._tc_from_frame(seg['end_frame']),
        })

    def run(self):
        import re as _re
        try:
            self.progress.emit('블랙 프레임 검출 준비 중...')
            frame_gap = 1.0 / self.fps if self.fps > 0 else 0.04
            black_re = _re.compile(r'frame:(\d+)\s+pblack:(\d+)\s+pts:\S+\s+t:([\d.]+)')
            cmd = [
                FFMPEG, '-hide_banner', '-nostats', '-loglevel', 'info',
                '-i', self.fp, '-an',
                '-vf', f'blackframe=amount={self.amount}:threshold={self.threshold}',
                '-f', 'null', '-'
            ]
            slot_label = 'black detect'
            if not acquire_heavy_analysis_slot(slot_label):
                raise RuntimeError('다른 분석 작업이 진행 중입니다. 잠시 후 다시 시도하세요.')
            try:
                self._proc = register_child_process(subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    encoding='utf-8', errors='replace',
                    creationflags=0x08000000
                ), 'black detect ffmpeg')

                ranges = []
                seg = None
                hit_count = 0
                assert self._proc.stderr is not None
                for line in self._proc.stderr:
                    if self._abort:
                        self.abort()
                        return
                    m = black_re.search(line)
                    if not m:
                        continue
                    frame = int(m.group(1))
                    pblack = int(m.group(2))
                    t = float(m.group(3))
                    hit_count += 1

                    if seg is None:
                        seg = {
                            'start': t, 'end': t,
                            'start_frame': frame, 'end_frame': frame,
                            'frames': 1,
                        }
                    else:
                        prev_frame = int(seg['end_frame'])
                        prev_t = float(seg['end'])
                        is_next_frame = frame <= prev_frame + 1
                        is_next_time = t <= prev_t + frame_gap * 1.6
                        if is_next_frame or is_next_time:
                            seg['end'] = t
                            seg['end_frame'] = frame
                            seg['frames'] += 1
                        else:
                            self._flush_segment(ranges, seg)
                            seg = {
                                'start': t, 'end': t,
                                'start_frame': frame, 'end_frame': frame,
                                'frames': 1,
                            }

                    if hit_count % 200 == 0:
                        self.progress.emit(f'블랙 프레임 {hit_count}개 검출 중... 최근 {self._tc_from_sec(t)} ({pblack}%)')

                if seg is not None:
                    self._flush_segment(ranges, seg)

                rc = self._proc.wait()
                if self._abort:
                    return
                if rc != 0:
                    self.error.emit(f'FFmpeg blackframe 실패 (rc={rc})')
                    return

                self.progress.emit(f'완료: 블랙 구간 {len(ranges)}개')
                log.info(f'BlackDetect 완료: {len(ranges)}구간, amount={self.amount}, threshold={self.threshold}')
                self.finished.emit(ranges)
            finally:
                unregister_child_process(self._proc)
                try:
                    release_heavy_analysis_slot('black detect')
                except Exception:
                    pass

        except Exception as e:
            log.error(f'BlackDetectThread 오류: {e}')
            if not self._abort:
                self.error.emit(str(e))
