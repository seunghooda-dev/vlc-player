"""QC 상태 요약 판정 회귀 테스트"""
from db_models import qc_summary_from_status


def test_found_labels():
    assert qc_summary_from_status('found', 'ok', 'ok') == '블랙 있음'
    assert qc_summary_from_status('ok', 'found', 'ok') == '무음 있음'
    assert qc_summary_from_status('ok', 'ok', 'found') == '프리즈 있음'
    assert qc_summary_from_status('found', 'found', 'ok') == '블랙/무음 있음'
    assert qc_summary_from_status('found', 'found', 'found') == '블랙/무음/프리즈 있음'


def test_error_takes_priority():
    assert qc_summary_from_status('error', 'ok', 'ok') == '검사 오류'
    assert qc_summary_from_status('found', 'error', 'ok') == '검사 오류'


def test_all_ok():
    assert qc_summary_from_status('ok', 'ok', 'ok') == '정상'


def test_black_mute_ok_without_freeze():
    assert qc_summary_from_status('ok', 'ok', '') == '블랙/무음 정상'


def test_unanalyzed():
    assert qc_summary_from_status('', '', '') == '미분석'
    assert qc_summary_from_status('unknown', 'weird', '') == '미분석'


def test_case_insensitive():
    assert qc_summary_from_status('FOUND', 'OK', 'ok') == '블랙 있음'
