"""safe.py — 숫자 변환 안전 헬퍼 (단일 출처)

여러 모듈에 중복 정의돼 있던 _safe_int / _safe_float / _safe_count 를
한 곳으로 통합한다. 표준 라이브러리 외 의존성이 없어 어떤 모듈에서도
순환 없이 import 할 수 있다.
"""
import math

__all__ = ['safe_float', 'safe_int', 'safe_count']


def safe_float(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return int(parsed)
    except Exception:
        pass
    return default


def safe_count(value):
    return max(0, safe_int(value, 0))
