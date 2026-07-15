# VLC 어댑터(VlcPlayerAdapter 트랜스포트·AudioMixPlayer 채널 로직) 순수 동작 검증
"""vlc_player 어댑터 단위 테스트.

VlcPlayerAdapter는 QObject라 실제 VLC/위젯 없이 __new__로 만들어 _player만 가짜로
주입한다(시그널을 emit하지 않는 순수 메서드만 대상). AudioMixPlayer는 VLC가 필요
없어 정상 생성한다. 여기서 검증하는 동작은 기존 check_imports 문자열 마커가 지키던
것을 실제 호출로 대체하기 위한 것이다.
"""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QObject
from PyQt6.QtMultimedia import QMediaPlayer

from vlc_player import VlcPlayerAdapter, AudioMixPlayer


class FakeVlcPlayer:
    def __init__(self, vout=0, time_ms=0, length_ms=0):
        self._vout = vout
        self._time = time_ms
        self._length = length_ms
        self.paused = []
        self.rate = None
        self.volume = None

    def has_vout(self):
        return self._vout

    def set_pause(self, v):
        self.paused.append(v)

    def set_rate(self, r):
        self.rate = r

    def get_time(self):
        return self._time

    def get_length(self):
        return self._length

    def audio_set_volume(self, v):
        self.volume = v


def _adapter(player):
    a = VlcPlayerAdapter.__new__(VlcPlayerAdapter)
    a._player = player
    a._op_seq = 0
    return a


def test_next_op_and_is_current_op():
    a = _adapter(FakeVlcPlayer())
    s1 = a._next_op()
    s2 = a._next_op()
    assert s2 == s1 + 1
    assert a._is_current_op(s2) is True
    assert a._is_current_op(s1) is False
    assert a._is_current_op(None) is True  # None은 항상 현재 op로 취급


def test_ensure_unpaused_only_when_current_op():
    p = FakeVlcPlayer()
    a = _adapter(p)
    a._op_seq = 5
    a._ensure_unpaused(5)
    assert p.paused == [0]  # 현재 op면 set_pause(0)로 재개
    a._ensure_unpaused(4)   # 오래된 seq면 무시
    assert p.paused == [0]


def test_has_video_output_truthiness_and_guard():
    assert _adapter(FakeVlcPlayer(vout=0)).has_video_output() is False
    assert _adapter(FakeVlcPlayer(vout=2)).has_video_output() is True

    class Boom:
        def has_vout(self):
            raise RuntimeError('vlc gone')

    assert _adapter(Boom()).has_video_output() is False


def test_pause_invalidates_pending_ops_and_pauses():
    # pause()는 op seq를 올려(예약된 resume 콜백 무효화) set_pause(1)로 정지한다.
    p = FakeVlcPlayer()
    a = _adapter(p)
    QObject.__init__(a)  # 시그널 emit에 필요한 QObject 초기화
    stale_seq = a._next_op()  # play()가 예약해 둔 지연 resume의 seq 가정
    states = []
    a.playbackStateChanged.connect(states.append)
    a.pause()
    assert p.paused == [1]
    assert a._is_current_op(stale_seq) is False  # 지연 resume 무효화
    assert states == [QMediaPlayer.PlaybackState.PausedState]
    a._ensure_unpaused(stale_seq)  # 무효화된 resume이 도착해도
    assert p.paused == [1]         # 다시 재생되지 않는다


def test_audio_mix_process_status_exposes_channel_keys():
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=0, channel_count=2)
    amp.set_channels([1, 2])
    status = amp.process_status()
    assert status['channels'] == [1, 2]            # 실제 적용 채널
    assert status['requested_channels'] == [1, 2]  # 요청 채널
    assert status['playing'] is False
    assert status['ffmpeg'] == 'missing' and status['ffplay'] == 'missing'


def test_set_playback_rate_clamped():
    p = FakeVlcPlayer()
    a = _adapter(p)
    a.setPlaybackRate(3.0)
    assert p.rate == 2.0
    a.setPlaybackRate(0.1)
    assert p.rate == 0.5
    a.setPlaybackRate(1.25)
    assert p.rate == 1.25
    a.setPlaybackRate(float('nan'))
    assert p.rate == 1.0  # 비유한값은 1.0으로


def test_position_and_media_length_guarded():
    a = _adapter(FakeVlcPlayer(time_ms=1234, length_ms=5000))
    assert a.position() == 1234
    assert a.media_length() == 5000

    class Boom:
        def get_time(self):
            raise RuntimeError('x')

        def get_length(self):
            raise RuntimeError('x')

    boom = _adapter(Boom())
    assert boom.position() == 0
    assert boom.media_length() == 0


def test_audio_mix_effective_channels_default_layout_unknown():
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=0, channel_count=0)  # 레이아웃 미상
    amp.set_channels([1, 2])
    assert amp.effective_channels() == [1, 2]


def test_audio_mix_effective_channels_respects_source_max():
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=0, channel_count=2)  # 2ch 소스
    amp.set_channels([1, 2, 5, 6])
    assert amp.effective_channels() == [1, 2]  # 소스 초과 채널 제거


def test_audio_mix_set_channels_dedup_clamp_and_empty():
    amp = AudioMixPlayer()
    amp.set_channels([1, 1, 2, 9, 0, 3, 16, 17])  # 중복 제거 + 1..16 범위만 (UHD 16채널)
    assert amp.channels == [1, 2, 9, 3, 16]
    amp.set_channels([])  # 명시적 빈 목록은 빈 채로 유지
    assert amp.channels == []
    amp.set_channels(None)  # None은 기본 [1,2]
    assert amp.channels == [1, 2]
    amp.set_channels([17, 0])  # 전부 범위 밖이면 기본 [1,2]
    assert amp.channels == [1, 2]


def test_audio_mix_filter_maps_high_channels_single_stream():
    # UHD 1×16ch 소재에서 9·10번 선택 → pan이 c8/c9(0-기반)로 매핑돼야 한다
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=1, channel_count=16)
    amp.set_channels([9, 10])
    filt = amp._build_filter()
    assert 'c0=c8' in filt and 'c0=c9' in filt


def test_audio_mix_filter_maps_high_channels_multi_stream():
    # 16모노 스트림 소재에서 15·16번 선택 → 0:a:14 / 0:a:15 스트림 선택
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=16, channel_count=16)
    amp.set_channels([15, 16])
    src15, _ = amp._source_for_channel(15, 0)
    src16, _ = amp._source_for_channel(16, 1)
    assert src15 == '0:a:14' and src16 == '0:a:15'


def test_audio_mix_diagnostic_status_reports_channels():
    amp = AudioMixPlayer()
    amp.set_file('x.mxf', audio_stream_count=0, channel_count=2)
    amp.set_channels([1, 2])
    status = amp.diagnostic_status()
    assert status['channels'] == [1, 2]
    assert status['requested_channels'] == [1, 2]
