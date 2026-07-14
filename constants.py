"""
constants.py — 색상, 스타일, 경로, 로거
모든 모듈이 import하는 공통 상수
"""
"""
MXF QC Player - PyQt6 완전판
파일 탐색 + 비디오 플레이어 + DB + STT + 씬감지 + 검색
"""

import sys, os, json, subprocess, hashlib, csv, shutil, threading, time, zipfile, math
from collections import deque
from pathlib import Path
from datetime import datetime

from safe import safe_float, safe_int, safe_count

# 자식 프로세스/heavy 분석 슬롯 관리는 process_registry.py 로 분리됨. 하위 호환 재노출.
from process_registry import (
    heavy_analysis_status, acquire_heavy_analysis_slot, release_heavy_analysis_slot,
    register_child_process, unregister_child_process, terminate_child_process,
    cleanup_child_processes, cleanup_orphan_audio_processes,
    runtime_child_process_status, _running_child_processes,
    _hidden_subprocess_flags, _safe_proc_log,
)

# 색상/스타일/글꼴은 theme.py 로 분리됨. 하위 호환을 위해 재노출.
from theme import (
    APP_FONT_QT, MONO_FONT_QT, APP_FONT_CSS, MONO_FONT_CSS,
    css_font, C, STYLE,
)

VIDEO_EXTS = {'.mxf','.mp4','.mov','.mts','.m2ts','.mkv','.avi'}

def _runtime_app_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def _runtime_resource_dir():
    return Path(getattr(sys, '_MEIPASS', _runtime_app_dir())).resolve()

APP_DIR      = _runtime_app_dir()
RESOURCE_DIR = _runtime_resource_dir()
BASE_DIR     = APP_DIR

APP_DATA_NAME = "MXF QC Player V.1.0"
USER_DATA_DIR_ENV = "MXF_QC_USER_DATA_DIR"

def _default_user_data_dir():
    if os.name == 'nt':
        root = os.environ.get('LOCALAPPDATA')
        if root:
            return Path(root) / APP_DATA_NAME
        return Path.home() / 'AppData' / 'Local' / APP_DATA_NAME
    root = os.environ.get('XDG_DATA_HOME')
    if root:
        return Path(root) / APP_DATA_NAME
    return Path.home() / '.local' / 'share' / APP_DATA_NAME

def _user_data_dir():
    override = os.environ.get(USER_DATA_DIR_ENV, '').strip()
    if override:
        return Path(override).expanduser()
    return _default_user_data_dir()

USER_DATA_DIR = _user_data_dir()
USER_DB_PATH = USER_DATA_DIR / "archive.db"
USER_SETTINGS_PATH = USER_DATA_DIR / "settings.json"
USER_LOG_DIR = USER_DATA_DIR / "logs"
USER_TMP_DIR = USER_DATA_DIR / "tmp"
USER_BACKUP_DIR = USER_DATA_DIR / "backups"
USER_REPORT_DIR = USER_DATA_DIR / "reports"

def _legacy_user_data_dir():
    if not getattr(sys, 'frozen', False):
        release_dir = APP_DIR / 'release' / APP_DATA_NAME
        if release_dir.exists():
            return release_dir
    return APP_DIR

LEGACY_DATA_DIR = _legacy_user_data_dir()
LEGACY_DB_PATH = LEGACY_DATA_DIR / "archive.db"
LEGACY_SETTINGS_PATH = LEGACY_DATA_DIR / "settings.json"
LEGACY_LOG_DIR = LEGACY_DATA_DIR / "logs"
LEGACY_TMP_DIR = LEGACY_DATA_DIR / "tmp"
LEGACY_BACKUP_DIR = LEGACY_DATA_DIR / "backups"
LEGACY_ROOT_DATA_NAMES = ("settings.json", "archive.db", "logs", "tmp", "backups")

def runtime_storage_policy():
    items = [
        {
            'name': '앱 실행 파일 폴더',
            'path': str(APP_DIR),
            'role': '프로그램 파일, tools, README, 라이선스 파일',
            'status': '실행 파일 전용, 기존 데이터 파일은 보존',
        },
        {
            'name': '사용자 데이터 폴더',
            'path': str(USER_DATA_DIR),
            'role': 'settings.json, archive.db, logs, tmp, backups, reports',
            'status': '현재 설정/DB/log/tmp/backups/reports 저장 위치',
        },
    ]
    if LEGACY_DATA_DIR != APP_DIR:
        items.append({
            'name': '기존 데이터 원본',
            'path': str(LEGACY_DATA_DIR),
            'role': '개발 실행 시 release 폴더의 기존 settings.json, archive.db',
            'status': '새 사용자 데이터 폴더로 최초 복사할 원본',
        })
    return items

DB_PATH    = USER_DB_PATH
SETTINGS_PATH = USER_SETTINGS_PATH
LOG_DIR    = USER_LOG_DIR
TMP_DIR    = USER_TMP_DIR
BACKUP_DIR = USER_BACKUP_DIR
REPORT_DIR = USER_REPORT_DIR
MIGRATION_LOG_PATH = LOG_DIR / "migration.log"
MIGRATION_LOG_MAX_BYTES = 2 * 1024 * 1024
MIGRATION_LOG_BACKUP_COUNT = 10
AUTO_CLEANUP_DAYS = 7
RELEASE_BACKUP_KEEP_COUNT = 3
_RUNTIME_DIR_ERRORS = []
_RUNTIME_MIGRATION_EVENTS = []
_RUNTIME_MIGRATION_LOG_ERRORS = []

def _ensure_runtime_dir(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        _RUNTIME_DIR_ERRORS.append((str(path), str(e)))
        return False

_ensure_runtime_dir(USER_DATA_DIR)
_ensure_runtime_dir(LOG_DIR)
_ensure_runtime_dir(TMP_DIR)
_ensure_runtime_dir(BACKUP_DIR)
_ensure_runtime_dir(REPORT_DIR)

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
            rotated = LOG_DIR / f'migration.log.{stamp}'
            MIGRATION_LOG_PATH.replace(rotated)
        backups = []
        for candidate in LOG_DIR.glob('migration.log.*'):
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
        LOG_DIR.mkdir(parents=True, exist_ok=True)
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
        'app_dir': str(APP_DIR),
        'user_data_dir': str(USER_DATA_DIR),
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
    _copy_legacy_file_to_user_data('settings.json', LEGACY_SETTINGS_PATH, SETTINGS_PATH)
    _copy_legacy_file_to_user_data('archive.db', LEGACY_DB_PATH, DB_PATH)
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
        if _path_key(resolved) == _path_key(USER_DATA_DIR):
            return
        key = _path_key(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append((label, resolved))

    add(APP_DIR, '앱 실행 파일 폴더')
    add(LEGACY_DATA_DIR, '기존 데이터 원본')
    if getattr(sys, 'frozen', False):
        try:
            if APP_DIR.parent.name.lower() == 'release':
                add(APP_DIR.parent.parent, '프로젝트 루트 후보')
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
        mtime = _path_mtime(path)
        info['modified'] = datetime.fromtimestamp(mtime).isoformat(timespec='seconds') if mtime else ''
        if path.is_file():
            info['size'] = _path_size(path)
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
        for name in LEGACY_ROOT_DATA_NAMES:
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

migrate_legacy_user_data()

# 실행 도구(FFmpeg/FFprobe/FFplay/VLC) 탐색과 실행 환경 점검은 runtime_tools.py 로 분리됨. 하위 호환 재노출.
from runtime_tools import (
    FFMPEG, FFPROBE, FFPLAY, VLC_DIR,
    _tool_candidates, resolve_tool_command, _RUNTIME_TOOL_META, _runtime_search_paths, runtime_package_check,
    _runtime_tool_state, missing_runtime_tools, runtime_tools_ok, format_missing_runtime_tools,
    _candidate_vlc_dirs, resolve_vlc_dir, _classify_runtime_source, _check_command,
    check_runtime_environment, format_runtime_environment,
)

def _check_write_location(name, path, role, required=True):
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_name = f'.mxf_qc_write_probe_{os.getpid()}_{datetime.now().strftime("%H%M%S%f")}.tmp'
        probe = path / probe_name
        probe.write_text('ok', encoding='utf-8')
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            'name': name,
            'ok': True,
            'path': str(path),
            'message': '쓰기 가능',
            'role': role,
            'required': required,
            'hint': '',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': str(path),
            'message': str(e),
            'role': role,
            'required': required,
            'hint': '앱 폴더를 쓰기 가능한 위치에 두세요. Program Files처럼 권한이 막힌 위치는 피하는 것이 좋습니다.',
        }

def _check_read_location(name, path, role, required=True):
    path = Path(path)
    try:
        ok = path.exists() and path.is_dir()
        return {
            'name': name,
            'ok': ok,
            'path': str(path),
            'message': '읽기 가능' if ok else '폴더를 찾을 수 없습니다',
            'role': role,
            'required': required,
            'hint': '' if ok else '앱 실행 파일 폴더가 이동/삭제됐는지 확인하세요.',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': str(path),
            'message': str(e),
            'role': role,
            'required': required,
            'hint': '앱 실행 파일 폴더 접근 권한을 확인하세요.',
        }

def check_runtime_storage():
    return [
        _check_read_location('앱 실행 파일 폴더', BASE_DIR, '프로그램 파일, tools, README 보관 위치'),
        _check_write_location('사용자 데이터 폴더', USER_DATA_DIR, 'settings.json, archive.db, logs, tmp, backups, reports 저장 위치'),
        _check_write_location('로그 폴더', LOG_DIR, 'logs/player.log 기록'),
        _check_write_location('임시 폴더', TMP_DIR, '분석 캐시와 임시 작업 파일 생성'),
        _check_write_location('백업 폴더', BACKUP_DIR, 'settings.json, archive.db 자동 백업', required=False),
        _check_write_location('리포트 폴더', REPORT_DIR, '진단 리포트 zip 저장', required=False),
    ]

def friendly_error_text(area, detail='', filename=None, max_detail=160):
    """Convert technical VLC/FFmpeg errors into short operator-facing Korean text."""
    area_key = str(area or '').lower()
    raw = str(detail or '').strip()
    low = raw.lower()
    name = ''
    if filename:
        try:
            name = Path(filename).name
        except Exception:
            name = str(filename)

    title = '작업 중 오류가 발생했습니다'
    hint = '오류 로그를 확인하고 같은 파일에서 반복되는지 점검하세요.'

    if (
        'file_missing' in area_key
        or 'no such file' in low
        or 'cannot find the file' in low
        or 'not found' in low
        or 'does not exist' in low
    ):
        title = '파일을 찾을 수 없습니다'
        hint = '파일이 이동/삭제됐거나 외장 드라이브 연결이 끊겼는지 확인하세요.'
    elif (
        'used by another process' in low
        or 'being used by another process' in low
        or 'sharing violation' in low
        or 'locked' in low
        or '잠금' in low
    ):
        title = '파일이 다른 프로그램에서 사용 중입니다'
        hint = '편집기, 복사 작업, 네트워크 전송, 다른 플레이어가 파일을 잡고 있는지 확인한 뒤 다시 여세요.'
    elif (
        'permission' in area_key
        or 'access_denied' in area_key
        or 'access-denied' in area_key
        or 'permission' in low
        or 'access is denied' in low
        or 'access denied' in low
        or 'permission denied' in low
        or '접근' in low
    ):
        title = '파일 접근 권한이 없습니다'
        hint = '다른 프로그램이 파일을 사용 중인지, 읽기 권한이 있는 위치인지 확인하세요.'
    elif 'timeout' in low or 'timed out' in low or '시간이 초과' in low:
        title = '작업 시간이 초과되었습니다'
        hint = '파일이 크거나 저장장치 응답이 느릴 수 있습니다. 다시 시도해도 반복되면 로그를 확인하세요.'
    elif 'audio' in area_key or 'mute' in area_key or '오디오' in low:
        title = '오디오 분석에 실패했습니다'
        hint = '오디오 스트림이 없거나 파일을 읽는 중 문제가 발생했습니다. 로그에서 FFmpeg 상세 내용을 확인하세요.'
    elif 'black' in area_key or 'blackframe' in low:
        title = '블랙 검출에 실패했습니다'
        hint = '비디오 스트림을 읽지 못했거나 FFmpeg 분석 중 문제가 발생했습니다.'
    elif 'loudness' in area_key or 'lkfs' in area_key or 'ebur128' in low:
        title = '라우드니스 분석에 실패했습니다'
        hint = '1/2CH 오디오 스트림을 읽지 못했거나 FFmpeg ebur128 분석 중 문제가 발생했습니다.'
    elif (
        'vlc' in area_key
        or 'vlc could not play' in low
        or 'unsupported' in low
        or 'invalidmedia' in low
    ):
        title = 'VLC가 이 파일을 재생하지 못했습니다'
        hint = 'MXF 코덱/컨테이너 호환성, 파일 손상 여부, VLC 설치 상태를 확인하세요.'
    elif 'file_access' in area_key or 'resource' in area_key:
        title = '파일을 열 수 없습니다'
        hint = '파일이 손상됐거나 다른 프로그램에서 사용 중인지 확인하세요.'
    elif 'ffmpeg' in area_key or 'ffmpeg' in low or 'ffprobe' in low:
        title = 'FFmpeg 작업 중 오류가 발생했습니다'
        hint = 'FFmpeg/FFprobe 경로, 파일 손상 여부, 오디오/비디오 스트림 존재 여부를 확인하세요.'
    elif 'format' in area_key or '지원하지 않는' in low:
        title = '지원하지 않는 영상 형식입니다'
        hint = '이 파일의 코덱 또는 컨테이너를 VLC가 열 수 없는 상태입니다.'
    elif 'network' in area_key:
        title = '네트워크 오류가 발생했습니다'
        hint = '네트워크 경로의 파일이면 연결 상태와 권한을 확인하세요.'
    elif 'drive' in low or 'device is not ready' in low or '지정된 장치' in low:
        title = '저장장치에 접근할 수 없습니다'
        hint = '외장하드, NAS, 네트워크 드라이브 연결 상태를 확인한 뒤 다시 시도하세요.'

    hide_detail = any(pattern in low for pattern in (
        'vlc could not play this file',
        '재생 불가:',
        'unsupported format',
    ))
    lines = [title, hint]
    if name:
        lines.append(f'파일: {name}')
    if raw and not hide_detail and max_detail:
        one_line = ' '.join(raw.split())
        lines.append(f'상세: {one_line[:max_detail]}')
    return '\n'.join(lines)

def friendly_error_title(area, detail='', filename=None):
    lines = friendly_error_text(area, detail, filename).splitlines()
    return lines[0] if lines else '오류가 발생했습니다'

def format_bytes(size):
    try:
        value = float(size or 0)
    except Exception:
        value = 0.0
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f'{int(value)} {units[idx]}'
    return f'{value:.1f} {units[idx]}'

# 숫자 변환 헬퍼는 safe.py 로 통합됨. 기존 호출부 호환을 위한 별칭.
_safe_float_value = safe_float
_safe_int_value = safe_int

def _path_mtime(path, default=0.0):
    try:
        return float(Path(path).stat().st_mtime)
    except Exception:
        return default

def _path_mtime_ns(path, default=0):
    try:
        return int(Path(path).stat().st_mtime_ns)
    except Exception:
        return default

def _path_size(path, default=0):
    try:
        return int(Path(path).stat().st_size)
    except Exception:
        return default

def _path_newest_time(path, default=0.0):
    try:
        stat = Path(path).stat()
        ctime = _safe_float_value(getattr(stat, 'st_ctime', 0.0), default)
        mtime = _safe_float_value(getattr(stat, 'st_mtime', 0.0), default)
        return max(ctime, mtime)
    except Exception:
        return default

def _safe_cache_child(path):
    root = TMP_DIR.resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except Exception:
        raise ValueError(f'캐시 폴더 밖 경로는 처리하지 않습니다: {resolved}')
    if resolved == root:
        raise ValueError('캐시 루트 폴더 자체는 삭제하지 않습니다.')
    return resolved

def _cache_entry_info(path):
    original = Path(path)
    if original.is_symlink():
        return {
            'name': original.name,
            'path': str(original),
            'is_dir': False,
            'is_symlink': True,
            'files': 0,
            'dirs': 0,
            'bytes': 0,
            'modified': 0.0,
        }
    path = _safe_cache_child(path)
    files = 0
    dirs = 0
    bytes_total = 0
    modified = 0.0
    if path.is_file():
        files = 1
        bytes_total = _path_size(path)
        modified = _path_mtime(path)
    elif path.is_dir():
        dirs = 1
        for child in path.rglob('*'):
            try:
                if child.is_symlink():
                    continue
                child_resolved = _safe_cache_child(child)
                if child_resolved.is_file():
                    files += 1
                    bytes_total += _path_size(child_resolved)
                    modified = max(modified, _path_mtime(child_resolved))
                elif child_resolved.is_dir():
                    dirs += 1
            except Exception:
                continue
        modified = max(modified, _path_mtime(path))
    return {
        'name': path.name,
        'path': str(path),
        'is_dir': path.is_dir(),
        'is_symlink': False,
        'files': files,
        'dirs': dirs,
        'bytes': bytes_total,
        'modified': modified,
    }

def cache_summary():
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    entries = []
    errors = []
    try:
        children = list(TMP_DIR.iterdir()) if TMP_DIR.exists() else []
    except Exception as e:
        children = []
        errors.append(str(e))
    for child in children:
        try:
            entries.append(_cache_entry_info(child))
        except Exception as e:
            errors.append(str(e))
    total_bytes = sum(item.get('bytes', 0) for item in entries)
    total_files = sum(item.get('files', 0) for item in entries)
    total_dirs = sum(item.get('dirs', 0) for item in entries)
    entries.sort(key=lambda item: (item.get('bytes', 0), item.get('modified', 0)), reverse=True)
    return {
        'root': str(TMP_DIR),
        'exists': TMP_DIR.exists(),
        'entries': entries,
        'errors': errors,
        'total_bytes': total_bytes,
        'total_files': total_files,
        'total_dirs': total_dirs,
    }

def format_cache_summary(summary=None, max_entries=30):
    summary = summary or cache_summary()
    lines = []
    lines.append('MXF QC Player 캐시 상태')
    lines.append('=' * 42)
    lines.append(f"위치: {summary.get('root')}")
    lines.append(f"전체 용량: {format_bytes(summary.get('total_bytes', 0))}")
    lines.append(f"파일: {summary.get('total_files', 0)}개")
    lines.append(f"폴더: {summary.get('total_dirs', 0)}개")
    if summary.get('errors'):
        lines.append('')
        lines.append('읽기 오류')
        lines.append('-' * 42)
        for err in summary.get('errors', [])[:10]:
            lines.append(f"- {err}")
    lines.append('')
    lines.append('상위 캐시 항목')
    lines.append('-' * 42)
    entries = summary.get('entries', [])
    if not entries:
        lines.append('캐시 항목이 없습니다.')
    else:
        for item in entries[:max_entries]:
            if item.get('is_symlink'):
                kind = 'LINK'
                file_info = 'skipped'
            else:
                kind = 'DIR ' if item.get('is_dir') else 'FILE'
                file_info = f"{item.get('files', 0)} files" if item.get('is_dir') else '1 file'
            lines.append(f"{kind}  {format_bytes(item.get('bytes', 0)):>10}  {file_info:<10}  {item.get('name')}")
        if len(entries) > max_entries:
            lines.append(f"... {len(entries) - max_entries}개 더 있음")
    lines.append('')
    lines.append('안전 기준')
    lines.append('-' * 42)
    lines.append('캐시 정리는 위 tmp 폴더 안의 항목만 대상으로 합니다.')
    lines.append(f'앱 시작 시 tmp/logs/backups/reports의 {AUTO_CLEANUP_DAYS}일 지난 생성 항목을 자동 정리합니다.')
    lines.append('원본 MXF, 바탕화면 파일, 파일 목록은 삭제하지 않습니다.')
    return '\n'.join(lines)

def cleanup_runtime_cache():
    before = cache_summary()
    root = TMP_DIR.resolve()
    deleted_entries = 0
    deleted_files = 0
    deleted_dirs = 0
    failed = []
    skipped = []
    for item in before.get('entries', []):
        path = Path(item.get('path', ''))
        try:
            if item.get('is_symlink') or path.is_symlink():
                skipped.append(str(path))
                continue
            target = _safe_cache_child(path)
            target.relative_to(root)
            if target.is_dir():
                deleted_files += _safe_int_value(item.get('files', 0), 0)
                deleted_dirs += _safe_int_value(item.get('dirs', 0), 0)
                shutil.rmtree(target)
            elif target.is_file():
                deleted_files += 1
                target.unlink()
            deleted_entries += 1
        except Exception as e:
            failed.append(f"{path}: {e}")
    after = cache_summary()
    freed = max(
        0,
        _safe_int_value(before.get('total_bytes', 0), 0)
        - _safe_int_value(after.get('total_bytes', 0), 0)
    )
    return {
        'before': before,
        'after': after,
        'freed_bytes': freed,
        'deleted_entries': deleted_entries,
        'deleted_files': deleted_files,
        'deleted_dirs': deleted_dirs,
        'failed': failed,
        'skipped': skipped,
    }

def _safe_generated_root(path):
    root = USER_DATA_DIR.resolve()
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root)
    except Exception:
        raise ValueError(f'사용자 데이터 폴더 밖 경로는 자동 정리하지 않습니다: {resolved}')
    return resolved

def _entry_newest_timestamp(path):
    path = Path(path)
    newest = _path_newest_time(path)
    if path.is_dir():
        try:
            for child in path.rglob('*'):
                try:
                    if child.is_symlink():
                        continue
                    newest = max(newest, _path_newest_time(child))
                except Exception:
                    continue
        except Exception:
            pass
    return newest

def _entry_size(path):
    path = Path(path)
    total = 0
    try:
        if path.is_file():
            return _path_size(path)
        if path.is_dir():
            for child in path.rglob('*'):
                try:
                    if child.is_symlink():
                        continue
                    if child.is_file():
                        total += _path_size(child)
                except Exception:
                    continue
    except Exception:
        pass
    return total

def cleanup_release_backups(keep_count=RELEASE_BACKUP_KEEP_COUNT):
    """배포본 전체 백업은 tools가 커서 최신 N개만 유지한다."""
    keep_count = max(1, _safe_int_value(keep_count, RELEASE_BACKUP_KEEP_COUNT))
    deleted = []
    failed = []
    skipped = []
    try:
        root = _safe_generated_root(BACKUP_DIR / 'release')
        root.relative_to(_safe_generated_root(BACKUP_DIR))
        if not root.exists():
            return {'deleted': deleted, 'failed': failed, 'skipped': skipped, 'deleted_count': 0, 'freed_bytes': 0}
    except Exception as e:
        return {'deleted': deleted, 'failed': [f'release-backups: {e}'], 'skipped': skipped, 'deleted_count': 0, 'freed_bytes': 0}

    entries = []
    try:
        for candidate in root.iterdir():
            try:
                if candidate.is_symlink():
                    skipped.append(str(candidate))
                    continue
                if not candidate.is_dir():
                    if candidate.name.lower() != 'latest.txt':
                        skipped.append(str(candidate))
                    continue
                entries.append({
                    'path': candidate,
                    'sort_key': candidate.name,
                    'bytes': _entry_size(candidate),
                    'newest': _entry_newest_timestamp(candidate),
                })
            except Exception as e:
                failed.append(f'{candidate}: {e}')
    except Exception as e:
        failed.append(f'{root}: {e}')
        entries = []

    entries.sort(key=lambda item: str(item.get('sort_key') or ''), reverse=True)
    keep_paths = {item['path'] for item in entries[:keep_count]}
    for item in entries[keep_count:]:
        path = item.get('path')
        try:
            bytes_before = _safe_int_value(item.get('bytes'), 0)
            shutil.rmtree(path)
            newest = _safe_float_value(item.get('newest'), 0.0)
            age_days = round((time.time() - newest) / 86400.0, 1) if newest > 0 else 0
            deleted.append({
                'section': 'release-backups',
                'path': str(path),
                'bytes': bytes_before,
                'age_days': age_days,
            })
        except Exception as e:
            failed.append(f'{path}: {e}')

    try:
        remaining = [item for item in entries if item.get('path') in keep_paths and item.get('path').exists()]
        remaining.sort(key=lambda item: str(item.get('sort_key') or ''), reverse=True)
        latest = root / 'latest.txt'
        if remaining:
            latest.write_text(str(remaining[0]['path']), encoding='utf-8')
        elif latest.exists():
            latest.unlink()
    except Exception as e:
        failed.append(f'{root / "latest.txt"}: {e}')

    return {
        'deleted': deleted,
        'failed': failed,
        'skipped': skipped,
        'deleted_count': len(deleted),
        'freed_bytes': sum(_safe_int_value(item.get('bytes', 0), 0) for item in deleted),
    }

def cleanup_old_generated_files(days=AUTO_CLEANUP_DAYS):
    """사용자 데이터 폴더 안의 생성 파일만 보존기간 기준으로 자동 정리한다."""
    keep_days = max(1.0, min(3650.0, _safe_float_value(days, AUTO_CLEANUP_DAYS)))
    cutoff = time.time() - keep_days * 86400.0
    try:
        cutoff_text = datetime.fromtimestamp(cutoff).isoformat(timespec='seconds')
    except Exception:
        cutoff_text = str(cutoff)
    deleted = []
    failed = []
    skipped = []
    roots = [
        ('tmp', TMP_DIR, False),
        ('logs', LOG_DIR, True),
        ('backups', BACKUP_DIR, True),
        ('reports', REPORT_DIR, True),
    ]
    active_log_names = {'player.log', 'migration.log'}

    for label, root_path, include_root_files in roots:
        try:
            root = _safe_generated_root(root_path)
            if not root.exists():
                continue
        except Exception as e:
            failed.append(f'{label}: {e}')
            continue

        try:
            candidates = list(root.iterdir()) if root.exists() else []
        except Exception as e:
            failed.append(f'{label}: {e}')
            candidates = []

        for candidate in candidates:
            try:
                original_candidate = Path(candidate)
                if original_candidate.is_symlink():
                    skipped.append(str(original_candidate))
                    continue
                target = _safe_generated_root(candidate)
                target.relative_to(root)
                if target == root:
                    continue
                if label == 'logs' and target.name in active_log_names:
                    skipped.append(str(target))
                    continue
                if label == 'backups' and target.name == 'release' and target.is_dir():
                    skipped.append(str(target))
                    continue
                if not include_root_files and not (target.is_file() or target.is_dir()):
                    continue
                newest = _entry_newest_timestamp(target)
                if newest <= 0 or newest >= cutoff:
                    continue
                bytes_before = _entry_size(target)
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                deleted.append({
                    'section': label,
                    'path': str(target),
                    'bytes': bytes_before,
                    'age_days': round((time.time() - newest) / 86400.0, 1),
                })
            except Exception as e:
                failed.append(f'{candidate}: {e}')

    release_cleanup = cleanup_release_backups(RELEASE_BACKUP_KEEP_COUNT)
    deleted.extend(release_cleanup.get('deleted') or [])
    failed.extend(release_cleanup.get('failed') or [])
    skipped.extend(release_cleanup.get('skipped') or [])

    return {
        'days': int(keep_days),
        'cutoff': cutoff_text,
        'deleted': deleted,
        'failed': failed,
        'skipped': skipped,
        'deleted_count': len(deleted),
        'freed_bytes': sum(_safe_int_value(item.get('bytes', 0), 0) for item in deleted),
    }

# 사용자 설정 저장/로드 및 백업 스냅샷 관리는 settings.py 로 분리됨. 하위 호환 재노출.
from settings import (
    DEFAULT_SETTINGS, _settings_cache, _settings_lock,
    _settings_data_copy, _default_settings_copy, _settings_str, _settings_int, _settings_float,
    _settings_int_str, _settings_float_str, _settings_db_str, _settings_str_list, _settings_int_pair,
    _settings_audio_channels, _normalize_settings, _settings_log_warning, _rotate_named_backups,
    backup_file_snapshot, _backup_corrupt_settings, _write_settings_atomic, load_settings, save_settings,
)

# 상태 이벤트 타임라인 기록과 진단 리포트 생성은 diagnostics.py 로 분리됨. 하위 호환 재노출.
from diagnostics import (
    _recent_log_text, _diagnostic_recent_files_text, _latest_report_text,
    _STATE_TIMELINE, _STATE_TIMELINE_LOCK, _STATE_KEY_MAX_CHARS, _STATE_MESSAGE_MAX_CHARS, _STATE_FIELD_MAX_CHARS,
    _state_event_text, record_state_event, runtime_state_timeline, format_state_timeline,
    _diagnostic_db_status_text, _diagnostic_path_stats, _diagnostic_storage_summary,
    _format_diagnostic_storage_summary, create_diagnostic_report, format_runtime_startup_alert,
)

# ── 로거 ──────────────────────────────────────────────
import logging as _logging
from logging.handlers import TimedRotatingFileHandler as _TRFHandler

_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 30

class _SafeTimedRotatingFileHandler(_TRFHandler):
    """다른 MXF QC Player 프로세스가 로그를 잡고 있어도 롤오버 실패를 삼킨다."""
    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError as e:
            try:
                if self.stream:
                    self.stream.flush()
            except Exception:
                pass
            self.rolloverAt = self.computeRollover(int(time.time()))
        except OSError as e:
            try:
                self.rolloverAt = self.computeRollover(int(time.time()))
            except Exception:
                pass

def _rotate_large_log_file():
    warnings = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        current = LOG_DIR / 'player.log'
        if (
            current.exists()
            and not current.is_symlink()
            and current.is_file()
            and _path_size(current) > _LOG_MAX_BYTES
        ):
            stamp = _file_stamp()
            rotated = LOG_DIR / f'player.log.{stamp}'
            current.replace(rotated)
            warnings.append(f'large log rotated: {rotated.name}')
        backups = []
        for candidate in LOG_DIR.glob('player.log.*'):
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                backups.append(candidate)
            except Exception:
                continue
        backups.sort(key=_path_mtime, reverse=True)
        keep_count = max(1, _safe_int_value(_LOG_BACKUP_COUNT, 5))
        for old in backups[keep_count:]:
            try:
                old.unlink()
            except Exception as e:
                warnings.append(f'old log cleanup failed: {old.name} ({e})')
    except Exception as e:
        warnings.append(f'large log rotation skipped: {e}')
    return warnings

def _make_logger():
    logger = _logging.getLogger('player')
    logger.setLevel(_logging.DEBUG)
    if logger.handlers:  # 중복 방지
        return logger
    fmt = _logging.Formatter(
        '[%(asctime)s] %(levelname)-5s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # 콘솔 출력 (WARNING 이상만)
    ch = _logging.StreamHandler()
    ch.setLevel(_logging.WARNING)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    # 날짜별 로그 파일 (30일 보관)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotation_warnings = _rotate_large_log_file()
        fh = _SafeTimedRotatingFileHandler(
            LOG_DIR / 'player.log',
            when='midnight', interval=1, backupCount=30,
            encoding='utf-8'
        )
        fh.setLevel(_logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        for msg in rotation_warnings:
            logger.warning(msg)
    except Exception as e:
        logger.warning(f'log file disabled: {LOG_DIR / "player.log"} ({e})')
    for path, err in _RUNTIME_DIR_ERRORS:
        logger.warning(f'runtime directory unavailable: {path} ({err})')
    return logger

log = _make_logger()

import process_registry as _process_registry
_process_registry.set_logger(log)
_process_registry.set_state_event_recorder(record_state_event)

def _log_exc(label, exc=None):
    """예외를 ERROR 레벨로 기록. except 블록에서 호출"""
    import traceback
    detail = traceback.format_exc() if exc is None else f'{type(exc).__name__}: {exc}'
    log.error(f'{label}\n{detail}')

# ── Qt 위젯 헬퍼 ─────────────────────────────────────────
def mk_btn(text, w=None, h=26, color=None, bg=None):
    from PyQt6.QtWidgets import QPushButton
    b = QPushButton(text)
    if w: b.setFixedWidth(w)
    b.setFixedHeight(h)
    if color or bg:
        bc = bg or "qlineargradient(y1:0,y2:1,stop:0 #606060,stop:1 #3c3c3c)"
        b.setStyleSheet(
            f"QPushButton{{background:{bc};color:{color or C['text0']};"
            f"border:1px solid #1e1e1e;border-radius:2px;"
            f"font-size:18px;font-weight:bold;padding:0 8px;}}"
            f"QPushButton:hover{{background:{bc};opacity:0.8;}}")
    return b

def mk_label(text, color=None, family=APP_FONT_QT, size=10, bold=False):
    from PyQt6.QtWidgets import QLabel
    l = QLabel(text)
    w = "bold" if bold else "normal"
    l.setStyleSheet(
        f"color:{color or C['text0']};font-family:{css_font(family)};"
        f"font-size:{size}px;font-weight:{w};background:transparent;")
    return l

def separator(vertical=True):
    from PyQt6.QtWidgets import QFrame
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};")
    return f
