# 레거시 사용자 데이터(설정/DB) 마이그레이션과 마이그레이션 로그 관리
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import constants as _c

def _migration_log_path():
    return _c.LOG_DIR / "migration.log"

MIGRATION_LOG_PATH = _migration_log_path()
MIGRATION_LOG_MAX_BYTES = 2 * 1024 * 1024
MIGRATION_LOG_BACKUP_COUNT = 10
_RUNTIME_MIGRATION_EVENTS = []
_RUNTIME_MIGRATION_LOG_ERRORS = []

def _file_stamp():
    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')

def _rotate_migration_log():
    def _local_size(path):
        try:
            return int(Path(path).stat().st_size)
        except Exception:
            return 0

    def _local_mtime(path):
        try:
            return float(Path(path).stat().st_mtime)
        except Exception:
            return 0.0

    try:
        if (
            MIGRATION_LOG_PATH.exists()
            and not MIGRATION_LOG_PATH.is_symlink()
            and MIGRATION_LOG_PATH.is_file()
            and _local_size(MIGRATION_LOG_PATH) > MIGRATION_LOG_MAX_BYTES
        ):
            stamp = _file_stamp()
            rotated = _c.LOG_DIR / f'migration.log.{stamp}'
            MIGRATION_LOG_PATH.replace(rotated)
        backups = []
        for candidate in _c.LOG_DIR.glob('migration.log.*'):
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                backups.append(candidate)
            except Exception:
                continue
        backups.sort(key=_local_mtime, reverse=True)
        try:
            keep_count = max(1, int(MIGRATION_LOG_BACKUP_COUNT))
        except Exception:
            keep_count = 5
        for old in backups[keep_count:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as e:
        _RUNTIME_MIGRATION_LOG_ERRORS.append(f'rotate failed: {e}')

def _append_migration_log(event):
    try:
        _c.LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_migration_log()
        with MIGRATION_LOG_PATH.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(event, ensure_ascii=False))
            fh.write('\n')
    except Exception as e:
        _RUNTIME_MIGRATION_LOG_ERRORS.append(str(e))

def _record_migration_event(name, source, target, status, message=''):
    event = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'name': name,
        'source': str(source),
        'target': str(target),
        'status': status,
        'message': message,
        'app_dir': str(_c.APP_DIR),
        'user_data_dir': str(_c.USER_DATA_DIR),
    }
    _RUNTIME_MIGRATION_EVENTS.append(event)
    _append_migration_log(event)

def _copy_legacy_file_to_user_data(name, source, target):
    if source.resolve() == target.resolve():
        return
    if not source.exists() or not source.is_file():
        return
    if target.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        _record_migration_event(name, source, target, 'copied', '기존 파일을 새 사용자 데이터 폴더로 복사함; 원본 보존')
    except Exception as e:
        _record_migration_event(name, source, target, 'failed', str(e))

def migrate_legacy_user_data():
    # 개명 전 기본 폴더(MXF QC Player V.1.0)를 우선 소스로 복사 — 대상이 이미 있으면 스킵되므로
    # 아래 레거시(repo/release) 소스보다 먼저 시도해야 실사용 데이터가 우선한다.
    # 단 오버라이드(스모크/CI 격리 폴더)에서는 실사용 데이터를 끌어오면 안 되므로 건너뛴다.
    if not getattr(_c, 'USER_DATA_DIR_IS_OVERRIDDEN', False):
        _copy_legacy_file_to_user_data('settings.json', _c.PREVIOUS_SETTINGS_PATH, _c.SETTINGS_PATH)
        _copy_legacy_file_to_user_data('archive.db', _c.PREVIOUS_DB_PATH, _c.DB_PATH)
    _copy_legacy_file_to_user_data('settings.json', _c.LEGACY_SETTINGS_PATH, _c.SETTINGS_PATH)
    _copy_legacy_file_to_user_data('archive.db', _c.LEGACY_DB_PATH, _c.DB_PATH)
    return list(_RUNTIME_MIGRATION_EVENTS)

def runtime_migration_events():
    return [dict(item) for item in _RUNTIME_MIGRATION_EVENTS]

def runtime_migration_log_info():
    return {
        'path': str(MIGRATION_LOG_PATH),
        'errors': list(_RUNTIME_MIGRATION_LOG_ERRORS),
    }

def _path_key(path):
    try:
        text = str(Path(path).resolve())
    except Exception:
        text = str(path)
    return text.lower() if os.name == 'nt' else text

def _legacy_root_candidates():
    candidates = []
    seen = set()

    def add(path, label):
        try:
            resolved = Path(path).resolve()
        except Exception:
            return
        if _path_key(resolved) == _path_key(_c.USER_DATA_DIR):
            return
        key = _path_key(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append((label, resolved))

    add(_c.APP_DIR, '앱 실행 파일 폴더')
    add(_c.LEGACY_DATA_DIR, '기존 데이터 원본')
    if getattr(sys, 'frozen', False):
        try:
            if _c.APP_DIR.parent.name.lower() == 'release':
                add(_c.APP_DIR.parent.parent, '프로젝트 루트 후보')
        except Exception:
            pass
    return candidates

def _legacy_root_item_info(path):
    info = {
        'name': path.name,
        'path': str(path),
        'kind': '폴더' if path.is_dir() else '파일',
        'size': None,
        'children': None,
        'modified': '',
    }
    try:
        mtime = _c._path_mtime(path)
        info['modified'] = datetime.fromtimestamp(mtime).isoformat(timespec='seconds') if mtime else ''
        if path.is_file():
            info['size'] = _c._path_size(path)
        elif path.is_dir():
            try:
                info['children'] = sum(1 for _ in path.iterdir())
            except Exception:
                info['children'] = None
    except Exception as e:
        info['error'] = str(e)
    return info

def runtime_legacy_root_data_status():
    groups = []
    for label, root in _legacy_root_candidates():
        items = []
        for name in _c.LEGACY_ROOT_DATA_NAMES:
            path = root / name
            if path.exists():
                items.append(_legacy_root_item_info(path))
        if items:
            groups.append({
                'label': label,
                'root': str(root),
                'items': items,
                'policy': '안내만 표시; 앱은 사용자 데이터 폴더만 사용하며 자동 삭제/이동하지 않음',
            })
    return groups
