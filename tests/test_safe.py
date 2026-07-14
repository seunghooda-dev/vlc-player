"""safe.py 숫자 변환 헬퍼 회귀 테스트"""
import math

from safe import safe_int, safe_float, safe_count


def test_safe_int_valid():
    assert safe_int(3) == 3
    assert safe_int("3") == 3
    assert safe_int(3.9) == 3          # int() 는 0 방향으로 버림
    assert safe_int(-3.9) == -3


def test_safe_int_invalid_returns_default():
    assert safe_int(None) == 0
    assert safe_int("abc") == 0
    assert safe_int("", 5) == 5
    assert safe_int(float("nan")) == 0
    assert safe_int(float("inf"), 7) == 7


def test_safe_float_valid():
    assert safe_float("1.5") == 1.5
    assert safe_float(2) == 2.0


def test_safe_float_invalid_returns_default():
    assert safe_float(None, 2.0) == 2.0
    assert safe_float("x") == 0.0
    assert safe_float(float("inf"), 9.0) == 9.0
    assert safe_float(float("nan"), 9.0) == 9.0


def test_safe_float_default_passthrough():
    # sanitize_qc_ranges 는 default=None 로 호출해 유효성 판정을 한다.
    assert safe_float("x", None) is None
    assert safe_float(float("nan"), None) is None


def test_safe_count_never_negative():
    assert safe_count(3) == 3
    assert safe_count("5") == 5
    assert safe_count(-4) == 0
    assert safe_count(float("nan")) == 0
    assert safe_count(None) == 0
