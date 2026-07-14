"""타임코드 변환 회귀 테스트 — SMPTE 드롭프레임/논드롭프레임"""
import pytest

from db_models import frames_to_tc, tc_to_frames, is_df_fps, sec_to_tc

DF2997 = 30000 / 1001
DF5994 = 60000 / 1001


@pytest.mark.parametrize("frame,fps,df,expected", [
    (1800, DF2997, True, '00:01:00;02'),
    (17982, DF2997, True, '00:10:00;00'),
    (1800, 30.0, False, '00:01:00:00'),
    (3600, DF5994, True, '00:01:00;04'),
    (35964, DF5994, True, '00:10:00;00'),
])
def test_frames_to_tc(frame, fps, df, expected):
    assert frames_to_tc(frame, fps, df) == expected


@pytest.mark.parametrize("tc,fps,df,expected", [
    ('00:01:00;02', DF2997, True, 1800),
    ('00:10:00;00', DF2997, True, 17982),
    ('00:01:00:00', 30.0, False, 1800),
    ('00:01:00;04', DF5994, True, 3600),
    ('00:10:00;00', DF5994, True, 35964),
])
def test_tc_to_frames(tc, fps, df, expected):
    assert tc_to_frames(tc, fps, df) == expected


@pytest.mark.parametrize("fps,df", [(DF2997, True), (30.0, False), (DF5994, True)])
def test_tc_roundtrip(fps, df):
    for frame in (0, 1, 29, 30, 1799, 1800, 1801, 17982, 35964):
        assert tc_to_frames(frames_to_tc(frame, fps, df), fps, df) == frame


def test_is_df_fps():
    assert is_df_fps(DF2997) is True
    assert is_df_fps(DF5994) is True
    assert is_df_fps(30.0) is False
    assert is_df_fps(60.0) is False
    assert is_df_fps(25.0) is False


def test_frames_to_tc_offset():
    # 소스 TC 오프셋(시작 프레임)이 적용된다.
    assert frames_to_tc(0, 30.0, False, offset_frames=1800) == '00:01:00:00'


def test_sec_to_tc_ndf():
    assert sec_to_tc(60.0, 30.0, False) == '00:01:00:00'


def test_tc_to_frames_malformed():
    assert tc_to_frames('', 30.0, False) == 0
    assert tc_to_frames('nonsense', 30.0, False) == 0
    assert tc_to_frames('00:00', 30.0, False) == 0
