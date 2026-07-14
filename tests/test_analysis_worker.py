# 분석 워커 시그널 연결/정리 헬퍼(_start_analysis_worker·_release_finished_thread) 동작 검증
"""RightPanel 분석 워커 공용 헬퍼 테스트.

5개 검출 사이트에서 중복되던 connect+start·isRunning 정리 로직을 두 헬퍼로 모았다.
헬퍼는 위젯이 필요 없으므로 fake self·fake thread로 언바운드 호출해 검증한다
(check_imports 프로브와 동일한 방식).
"""
import types

import pytest

pytest.importorskip("PyQt6")

from right_panel import RightPanel


class FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *args):
        for fn in list(self._slots):
            fn(*args)


class FakeThread:
    def __init__(self, running=False):
        self._running = running
        self.started = False
        self.progress = FakeSignal()
        self.finished = FakeSignal()
        self.error = FakeSignal()

    def isRunning(self):
        return self._running

    def start(self):
        self.started = True


def _owner():
    return types.SimpleNamespace()


def test_start_analysis_worker_wires_and_starts():
    thread = FakeThread()
    calls = {'progress': [], 'finished': [], 'error': []}
    RightPanel._start_analysis_worker(
        _owner(), thread, 7,
        lambda s, m: calls['progress'].append((s, m)),
        lambda r, seq=None: calls['finished'].append((r, seq)),
        lambda e, seq=None: calls['error'].append((e, seq)),
    )
    assert thread.started is True
    # progress 시그널은 message만 emit하고 헬퍼가 seq를 앞에 붙여 전달한다
    thread.progress.emit('50%')
    assert calls['progress'] == [(7, '50%')]
    # finished/error는 seq를 키워드로 스냅샷 전달한다
    thread.finished.emit(['range'])
    assert calls['finished'] == [(['range'], 7)]
    thread.error.emit('boom')
    assert calls['error'] == [('boom', 7)]


def test_start_analysis_worker_snapshots_seq_per_site():
    # 서로 다른 seq로 두 워커를 연결해도 각 슬롯은 자기 seq를 스냅샷해야 한다
    seen = []
    t1, t2 = FakeThread(), FakeThread()
    noop = lambda *a, **k: None
    RightPanel._start_analysis_worker(_owner(), t1, 1, noop,
                                      lambda r, seq=None: seen.append(seq), noop)
    RightPanel._start_analysis_worker(_owner(), t2, 2, noop,
                                      lambda r, seq=None: seen.append(seq), noop)
    t2.finished.emit('y')
    t1.finished.emit('x')
    assert seen == [2, 1]


def test_release_finished_thread_nulls_when_stopped():
    owner = _owner()
    owner._black_thread = FakeThread(running=False)
    RightPanel._release_finished_thread(owner, '_black_thread')
    assert owner._black_thread is None


def test_release_finished_thread_keeps_running_reference():
    owner = _owner()
    running = FakeThread(running=True)
    owner._audio_thread = running
    RightPanel._release_finished_thread(owner, '_audio_thread')
    assert owner._audio_thread is running


def test_release_finished_thread_tolerates_missing_or_none():
    owner = _owner()
    # 속성이 아예 없어도 예외 없이 no-op
    RightPanel._release_finished_thread(owner, '_freeze_thread')
    # None이어도 no-op
    owner._freeze_thread = None
    RightPanel._release_finished_thread(owner, '_freeze_thread')
    assert owner._freeze_thread is None
