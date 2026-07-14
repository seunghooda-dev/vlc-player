# 상태 타임라인(record_state_event) 기록·포맷 회귀 테스트 — CUE 텔레메트리 파이프라인 검증
"""diagnostics 상태 타임라인 테스트.

check_imports의 isoformat(milliseconds) 소스 마커를 실호출 검증으로 대체하고,
vlc_player의 CUE 텔레메트리(record_state_event('cue', 'first frame rendered', ...))가
진단 타임라인에 실제로 나타나는 형태를 고정한다. PyQt6 불필요(최소 CI 환경에서 실행됨).
"""
import re

# diagnostics를 단독 진입점으로 import하면 constants와의 순환(파사드 재노출)에서
# 부분초기화 ImportError가 난다 — 실제 소비자처럼 constants를 먼저 초기화한다.
import constants  # noqa: F401

from diagnostics import (
    record_state_event,
    runtime_state_timeline,
    format_state_timeline,
)

MS_TS = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}$')


def test_record_state_event_timestamp_has_millisecond_isoformat():
    record_state_event('test-cat', 'ms format check')
    row = runtime_state_timeline()[-1]
    assert row['category'] == 'test-cat'
    assert row['message'] == 'ms format check'
    assert MS_TS.match(row['ts']), f"밀리초 isoformat 아님: {row['ts']}"


def test_record_state_event_keeps_extra_fields():
    record_state_event('cue', 'first frame rendered', elapsed='0.49s')
    row = runtime_state_timeline()[-1]
    assert row['elapsed'] == '0.49s'


def test_runtime_state_timeline_respects_limit():
    for i in range(5):
        record_state_event('limit-test', f'row {i}')
    rows = runtime_state_timeline(limit=3)
    assert len(rows) == 3
    assert rows[-1]['message'] == 'row 4'


def test_cue_telemetry_appears_in_formatted_timeline():
    # vlc_player._preroll_tick이 남기는 이벤트 형태 그대로 — 진단 ZIP 판별 경로 고정
    record_state_event('cue', 'first frame rendered', elapsed='0.83s')
    text = format_state_timeline()
    assert 'first frame rendered' in text
    assert '0.83s' in text
