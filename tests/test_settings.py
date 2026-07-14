"""설정 정규화(_normalize_settings) 회귀 테스트"""
from constants import _normalize_settings, DEFAULT_SETTINGS


def test_empty_returns_defaults():
    out = _normalize_settings({})
    assert out['volume'] == DEFAULT_SETTINGS['volume']
    assert out['playback_rate'] == DEFAULT_SETTINGS['playback_rate']


def test_non_dict_input_returns_defaults():
    out = _normalize_settings("garbage")
    assert out['volume'] == DEFAULT_SETTINGS['volume']


def test_volume_clamped():
    assert _normalize_settings({'volume': 999})['volume'] == 100
    assert _normalize_settings({'volume': -5})['volume'] == 0


def test_playback_rate_clamped():
    assert _normalize_settings({'playback_rate': 5.0})['playback_rate'] == 2.0
    assert _normalize_settings({'playback_rate': 0.1})['playback_rate'] == 0.5


def test_audio_channels_filtered_and_deduped():
    out = _normalize_settings({'audio_channels': [1, 2, 99, 2, -1, 'x']})
    assert out['audio_channels'] == [1, 2]


def test_audio_channels_invalid_falls_back():
    out = _normalize_settings({'audio_channels': ['x', 99, 0]})
    assert out['audio_channels'] == DEFAULT_SETTINGS['audio_channels']
