# 트랜스코드 조정자(TranscodeCoordinator) 캐시 정리·사전변환 취소·스레드 은퇴 동작 검증
"""TranscodeCoordinator 단위 테스트.

VideoPanel에서 분리된 조정자를 fake panel로 직접 생성해 검증한다
(test_loudness.py와 동일한 방식). _evict_tc_cache는 conftest가 격리한
사용자 데이터 디렉터리의 TMP_DIR에 실제 파일을 만들어 검증한다.
"""
import types

import pytest

pytest.importorskip("PyQt6")

import constants
from transcode_coordinator import TranscodeCoordinator, DIRECT_VLC_EXTS


class FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in list(self._slots):
            fn(*args)


class FakeThread:
    def __init__(self, running=True):
        self._running = running
        self.aborted = False
        self.finished = FakeSignal()

    def isRunning(self):
        return self._running

    def abort(self):
        self.aborted = True


def _panel():
    p = types.SimpleNamespace()
    p._dead_threads = []
    p._track_dead_thread = lambda t: p._dead_threads.append(t)
    return p


def test_direct_vlc_exts_canonical_home():
    # 원 소유가 이 모듈로 이동 — video_panel은 재노출만 한다
    assert DIRECT_VLC_EXTS == {'.mxf', '.mp4'}
    from video_panel import DIRECT_VLC_EXTS as reexported
    assert reexported is DIRECT_VLC_EXTS


def test_cancel_preconvert_job_targets_single_file():
    c = TranscodeCoordinator(_panel())
    t1, t2 = FakeThread(), FakeThread()
    c._preconvert_jobs = {'a.mov': t1, 'b.mov': t2}
    c._preconvert_threads = [t1, t2]
    c._tc_cache = {'a.mov': None, 'b.mov': None}  # 변환 중 마킹
    c._cancel_preconvert_job('a.mov')
    assert t1.aborted is True and t2.aborted is False
    assert 'a.mov' not in c._preconvert_jobs and 'b.mov' in c._preconvert_jobs
    assert c._preconvert_threads == [t2]
    assert 'a.mov' not in c._tc_cache  # 미완성 캐시 마킹 제거


def test_cancel_preconvert_job_all_and_keeps_completed_cache():
    c = TranscodeCoordinator(_panel())
    t1 = FakeThread()
    c._preconvert_jobs = {'a.mov': t1}
    c._preconvert_threads = [t1]
    c._tc_cache = {'a.mov': 'C:/tmp/a.mp4'}  # 완료된 캐시는 보존
    c._cancel_preconvert_job()
    assert c._preconvert_jobs == {}
    assert c._tc_cache == {'a.mov': 'C:/tmp/a.mp4'}


def test_retire_tc_parks_thread_and_finished_removes():
    panel = _panel()
    c = TranscodeCoordinator(panel)
    t = FakeThread()
    c._tc_thread = t
    c._retire_tc()
    assert c._tc_thread is None
    assert t.aborted is True
    assert panel._dead_threads == [t]
    t.finished.emit()  # 완전 종료 시 dead_threads에서 자동 제거
    assert panel._dead_threads == []


def test_retire_tc_noop_without_thread():
    panel = _panel()
    c = TranscodeCoordinator(panel)
    c._retire_tc()
    assert panel._dead_threads == []


def test_evict_tc_cache_removes_oldest_over_max_files(tmp_path, monkeypatch):
    # TMP_DIR 내부 실제 파일로 검증 — 외부 경로 가드는 로그만 남기고 건너뜀
    monkeypatch.setattr(constants, 'TMP_DIR', tmp_path, raising=False)
    import transcode_coordinator as tcm
    monkeypatch.setattr(tcm, 'TMP_DIR', tmp_path, raising=False)

    c = TranscodeCoordinator(_panel())
    files = {}
    for name in ('old', 'mid', 'new'):
        f = tmp_path / f'{name}.mp4'
        f.write_bytes(b'x' * 8)
        files[name] = f
        c._tc_cache[f'{name}.mxf'] = str(f)
        c._tc_cache_order.append(f'{name}.mxf')

    c._evict_tc_cache(max_files=2, max_gb=2.0)

    assert not files['old'].exists()      # 가장 오래된 것 삭제
    assert files['mid'].exists() and files['new'].exists()
    assert c._tc_cache_order == ['mid.mxf', 'new.mxf']
    assert 'old.mxf' not in c._tc_cache


def test_evict_tc_cache_skips_paths_outside_tmp(tmp_path, monkeypatch):
    import transcode_coordinator as tcm
    monkeypatch.setattr(tcm, 'TMP_DIR', tmp_path / 'inside', raising=False)
    (tmp_path / 'inside').mkdir()

    outside = tmp_path / 'outside.mp4'
    outside.write_bytes(b'x' * 8)

    c = TranscodeCoordinator(_panel())
    c._tc_cache['a.mxf'] = str(outside)
    c._tc_cache_order.append('a.mxf')
    c._evict_tc_cache(max_files=0, max_gb=0.0)

    assert outside.exists()  # TMP_DIR 밖 파일은 절대 삭제하지 않는다
    assert c._tc_cache_order == []  # 유효 목록에서만 제외
