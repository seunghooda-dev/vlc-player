# EOF 가드(_near_end_of_media) 회귀 테스트 — 파일 끝 오디오 정상 종료 오판 방지
import pytest

pytest.importorskip("PyQt6")

from video_panel import VideoPanel


class StubPlayer:
    def __init__(self, pos_ms):
        self._pos = pos_ms

    def position(self):
        return self._pos


def _panel(duration_s, pos_ms):
    p = VideoPanel.__new__(VideoPanel)
    p.duration = duration_s
    p.player = StubPlayer(pos_ms)
    return p


def test_near_eof_true_within_margin():
    assert _panel(600.0, 598500)._near_end_of_media() is True   # 끝 1.5초 전
    assert _panel(600.0, 600100)._near_end_of_media() is True   # 끝 지나침


def test_near_eof_false_mid_playback():
    assert _panel(600.0, 300000)._near_end_of_media() is False
    assert _panel(600.0, 597000)._near_end_of_media() is False  # 3초 전(기본 마진 2s 밖)


def test_near_eof_false_without_duration():
    assert _panel(0, 100000)._near_end_of_media() is False      # duration 미상은 가드 미적용
    assert _panel(None, 100000)._near_end_of_media() is False
