"""process_registry.py heavy 분석 슬롯 회귀 테스트"""
import pytest

import process_registry as pr


@pytest.fixture(autouse=True)
def _clean_slot():
    pr.release_heavy_analysis_slot()
    pr.set_state_event_recorder(None)
    yield
    pr.release_heavy_analysis_slot()
    pr.set_state_event_recorder(None)


def test_acquire_then_release_by_same_owner():
    assert pr.acquire_heavy_analysis_slot('black-detect') is True
    status = pr.heavy_analysis_status()
    assert status['running'] is True
    assert status['owner'] == 'black-detect'

    pr.release_heavy_analysis_slot('black-detect')
    status = pr.heavy_analysis_status()
    assert status['running'] is False
    assert status['owner'] is None


def test_second_acquire_while_occupied_fails():
    assert pr.acquire_heavy_analysis_slot('freeze-detect') is True
    assert pr.acquire_heavy_analysis_slot('loudness') is False
    status = pr.heavy_analysis_status()
    assert status['owner'] == 'freeze-detect'


def test_release_with_wrong_label_is_ignored():
    pr.acquire_heavy_analysis_slot('black-detect')
    pr.release_heavy_analysis_slot('someone-else')
    status = pr.heavy_analysis_status()
    assert status['running'] is True
    assert status['owner'] == 'black-detect'


def test_release_without_label_always_clears():
    pr.acquire_heavy_analysis_slot('black-detect')
    pr.release_heavy_analysis_slot()
    assert pr.heavy_analysis_status()['running'] is False


def test_state_event_recorder_hook_is_invoked():
    events = []
    pr.set_state_event_recorder(lambda *args, **kwargs: events.append((args, kwargs)))

    pr.acquire_heavy_analysis_slot('black-detect')
    pr.release_heavy_analysis_slot('black-detect')

    assert len(events) == 2
