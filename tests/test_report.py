"""QC 리포트 CSV 수식 인젝션 방지(_csv_safe_cell) 테스트

right_panel 은 PyQt6 를 import 하므로, PyQt6 가 없는 최소 CI 환경에서는
스킵한다(전체 import 는 import-gate 잡이 커버).
"""
import pytest

pytest.importorskip("PyQt6")

from right_panel import _csv_safe_cell


def test_formula_prefixes_neutralized():
    assert _csv_safe_cell('=SUM(A1:A9)') == "'=SUM(A1:A9)"
    assert _csv_safe_cell('@cmd') == "'@cmd"
    assert _csv_safe_cell('\tTAB') == "'\tTAB"
    assert _csv_safe_cell('\rCR') == "'\rCR"


def test_formula_like_plus_minus_neutralized():
    assert _csv_safe_cell('-1+1') == "'-1+1"
    assert _csv_safe_cell('+cmd|calc') == "'+cmd|calc"


def test_plain_numbers_preserved():
    # 무음/프리즈 dB 임계값 같은 순수 숫자는 그대로 둔다.
    assert _csv_safe_cell('-20') == '-20'
    assert _csv_safe_cell('-2.5') == '-2.5'
    assert _csv_safe_cell('+3') == '+3'


def test_ordinary_values_untouched():
    assert _csv_safe_cell('news_clip.mxf') == 'news_clip.mxf'
    assert _csv_safe_cell('00:01:00;02') == '00:01:00;02'
    assert _csv_safe_cell('') == ''
    assert _csv_safe_cell(None) is None
    assert _csv_safe_cell(3) == 3


def test_dangerous_filename_neutralized():
    assert _csv_safe_cell('=HYPERLINK("http://x")') == "'=HYPERLINK(\"http://x\")"
