# 오디오 레벨 미터 16채널 분배(_on_levels) 회귀 테스트
"""MeterController._on_levels의 16채널 홀/짝 레일 분배 검증.

MeterController.__new__ + 스텁 레일로 Qt 위젯 없이 검증한다(test_loudness 방식).
"""
import pytest

pytest.importorskip("PyQt6")

from meters import MeterController


class StubRail:
    def __init__(self):
        self.levels = None
        self.peaks = None

    def set_levels(self, levels, peaks):
        self.levels = list(levels)
        self.peaks = list(peaks)


class StubLoud:
    def __init__(self):
        self.lkfs = None

    def update_lkfs(self, m, s, i):
        self.lkfs = (m, s, i)


def _controller():
    c = MeterController.__new__(MeterController)
    c.lm = StubRail()
    c.rm = StubRail()
    c.loud = StubLoud()
    return c


def test_sixteen_channels_split_odd_left_even_right():
    c = _controller()
    levels = [i / 100 for i in range(1, 17)]   # ch1=0.01 .. ch16=0.16
    peaks = [i / 100 + 0.5 for i in range(1, 17)]
    c._on_levels(levels, peaks, -23.0, -22.0, -23.5)
    assert c.lm.levels == pytest.approx([0.01, 0.03, 0.05, 0.07, 0.09, 0.11, 0.13, 0.15])  # 홀수 8행
    assert c.rm.levels == pytest.approx([0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16])  # 짝수 8행
    assert c.lm.peaks == pytest.approx([0.51, 0.53, 0.55, 0.57, 0.59, 0.61, 0.63, 0.65])
    assert c.loud.lkfs == (-23.0, -22.0, -23.5)


def test_short_input_pads_upper_channels_to_zero():
    # 2채널 소재: ch1/ch2만 값, 3~16은 0으로 패딩되어 상위 바가 잔상 없이 꺼진다
    c = _controller()
    c._on_levels([0.8, 0.6], [0.9, 0.7], 0, 0, 0)
    assert c.lm.levels == [0.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert c.rm.levels == [0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_oversized_input_is_truncated_to_sixteen():
    c = _controller()
    c._on_levels([0.5] * 32, [0.5] * 32, 0, 0, 0)
    assert len(c.lm.levels) == 8 and len(c.rm.levels) == 8
