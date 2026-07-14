"""QC 구간 정규화(sanitize_qc_ranges) 회귀 테스트"""
from db_models import sanitize_qc_ranges


def test_start_duration_fills_end():
    out = sanitize_qc_ranges([{'start': 1.0, 'duration': 2.0}])
    assert out == [{'start': 1.0, 'duration': 2.0, 'end': 3.0}]


def test_start_end_fills_duration():
    out = sanitize_qc_ranges([{'start': 1.0, 'end': 3.5}])
    assert out[0]['duration'] == 2.5


def test_single_dict_accepted():
    out = sanitize_qc_ranges({'start': 1.0, 'end': 2.0})
    assert out[0]['start'] == 1.0 and out[0]['end'] == 2.0


def test_reversed_range_dropped():
    assert sanitize_qc_ranges([{'start': 5.0, 'end': 2.0}]) == []


def test_missing_start_dropped():
    assert sanitize_qc_ranges([{'end': 2.0}]) == []


def test_negative_start_clamped_to_zero():
    out = sanitize_qc_ranges([{'start': -5.0, 'end': 2.0}])
    assert out[0]['start'] == 0.0


def test_string_and_none_inputs_ignored():
    assert sanitize_qc_ranges("nope") == []
    assert sanitize_qc_ranges(None) == []


def test_non_dict_items_skipped():
    out = sanitize_qc_ranges([{'start': 1.0, 'end': 2.0}, "junk", 42, None])
    assert len(out) == 1


def test_limit_enforced():
    many = [{'start': float(i), 'end': float(i) + 1} for i in range(10)]
    assert len(sanitize_qc_ranges(many, limit=3)) == 3


def test_frames_and_tc_preserved():
    out = sanitize_qc_ranges([{
        'start': 1.0, 'end': 2.0, 'frames': 30,
        'tc_start': '00:00:01:00', 'tc_end': '00:00:02:00',
    }])
    row = out[0]
    assert row['frames'] == 30
    assert row['tc_start'] == '00:00:01:00'
    assert row['tc_end'] == '00:00:02:00'
