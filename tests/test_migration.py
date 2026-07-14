# 개명(MasterQC) 데이터 마이그레이션 회귀 테스트 — 이전 폴더 복사·오버라이드 가드·무덮어쓰기
"""migrate_legacy_user_data의 개명 이전(PREVIOUS_*) 소스 동작 검증.

- 이전 기본 폴더(MXF QC Player V.1.0)의 settings/db를 새 폴더로 복사(원본 보존)
- MXF_QC_USER_DATA_DIR 오버라이드(스모크/CI) 시에는 실사용 데이터를 끌어오지 않음
- 대상 파일이 이미 있으면 덮어쓰지 않음

migration은 constants와 파사드 순환이라 실소비자처럼 constants를 먼저 초기화한다.
"""
from pathlib import Path

import constants  # noqa: F401 — 파사드 순환 부분초기화 방지
import migration


def _wire(monkeypatch, tmp_path, overridden):
    prev = tmp_path / 'prev'
    user = tmp_path / 'user'
    prev.mkdir()
    user.mkdir()
    nowhere = tmp_path / 'nowhere'
    monkeypatch.setattr(constants, 'USER_DATA_DIR_IS_OVERRIDDEN', overridden, raising=False)
    monkeypatch.setattr(constants, 'PREVIOUS_SETTINGS_PATH', prev / 'settings.json', raising=False)
    monkeypatch.setattr(constants, 'PREVIOUS_DB_PATH', prev / 'archive.db', raising=False)
    monkeypatch.setattr(constants, 'SETTINGS_PATH', user / 'settings.json', raising=False)
    monkeypatch.setattr(constants, 'DB_PATH', user / 'archive.db', raising=False)
    # repo/release 레거시 소스는 이 테스트 범위 밖 — 존재하지 않는 경로로 무력화
    monkeypatch.setattr(constants, 'LEGACY_SETTINGS_PATH', nowhere / 'settings.json', raising=False)
    monkeypatch.setattr(constants, 'LEGACY_DB_PATH', nowhere / 'archive.db', raising=False)
    return prev, user


def test_previous_app_data_is_copied_when_not_overridden(tmp_path, monkeypatch):
    prev, user = _wire(monkeypatch, tmp_path, overridden=False)
    (prev / 'settings.json').write_text('{"volume": 55}', encoding='utf-8')
    (prev / 'archive.db').write_bytes(b'db-bytes')

    migration.migrate_legacy_user_data()

    assert (user / 'settings.json').read_text(encoding='utf-8') == '{"volume": 55}'
    assert (user / 'archive.db').read_bytes() == b'db-bytes'
    # 복사(이동 아님) — 원본 보존
    assert (prev / 'settings.json').exists() and (prev / 'archive.db').exists()


def test_override_skips_previous_app_data(tmp_path, monkeypatch):
    prev, user = _wire(monkeypatch, tmp_path, overridden=True)
    (prev / 'settings.json').write_text('{"volume": 55}', encoding='utf-8')

    migration.migrate_legacy_user_data()

    # 스모크/CI 격리 폴더가 실사용 데이터를 빨아들이면 안 된다
    assert not (user / 'settings.json').exists()


def test_existing_target_is_never_overwritten(tmp_path, monkeypatch):
    prev, user = _wire(monkeypatch, tmp_path, overridden=False)
    (prev / 'settings.json').write_text('{"old": true}', encoding='utf-8')
    (user / 'settings.json').write_text('{"current": true}', encoding='utf-8')

    migration.migrate_legacy_user_data()

    assert (user / 'settings.json').read_text(encoding='utf-8') == '{"current": true}'
