"""LoudnessCoordinator._normalize_loudness_result 순수 로직 회귀 테스트

loudness_coordinator 는 PyQt6 를 import 하므로, PyQt6 가 없는 최소 CI 환경에서는
스킵한다(전체 import 는 import-gate 잡이 커버).
"""
import math

import pytest

pytest.importorskip("PyQt6")

from loudness_coordinator import LoudnessCoordinator


def _coordinator():
    return LoudnessCoordinator.__new__(LoudnessCoordinator)


def test_valid_numeric_integrated_is_normalized_to_float():
    result = _coordinator()._normalize_loudness_result({'integrated': -23})
    assert result == {'integrated': -23.0}
    assert isinstance(result['integrated'], float)


def test_valid_string_integrated_is_coerced_and_other_keys_preserved():
    result = _coordinator()._normalize_loudness_result({'integrated': '-18.5', 'true_peak': -1.2})
    assert result['integrated'] == -18.5
    assert result['true_peak'] == -1.2


def test_non_dict_input_returns_none():
    coord = _coordinator()
    assert coord._normalize_loudness_result(None) is None
    assert coord._normalize_loudness_result([1, 2]) is None
    assert coord._normalize_loudness_result('-23.0') is None
    assert coord._normalize_loudness_result(-23.0) is None


def test_missing_integrated_key_returns_none():
    coord = _coordinator()
    assert coord._normalize_loudness_result({}) is None
    assert coord._normalize_loudness_result({'true_peak': -1.2}) is None


def test_non_numeric_integrated_returns_none():
    assert _coordinator()._normalize_loudness_result({'integrated': 'abc'}) is None


def test_non_finite_integrated_returns_none():
    coord = _coordinator()
    assert coord._normalize_loudness_result({'integrated': float('nan')}) is None
    assert coord._normalize_loudness_result({'integrated': float('inf')}) is None
    assert coord._normalize_loudness_result({'integrated': float('-inf')}) is None


def test_normalize_does_not_mutate_caller_dict():
    original = {'integrated': -23, 'true_peak': -1.2}
    result = _coordinator()._normalize_loudness_result(original)
    assert original['integrated'] == -23
    assert isinstance(original['integrated'], int)
    assert result is not original
    assert math.isclose(result['integrated'], -23.0)
