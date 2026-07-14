# 상태 이벤트 타임라인 기록과 진단 리포트(zip) 생성
import json
import os
import threading
import time
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path

import constants as _c
from process_registry import runtime_child_process_status

def _recent_log_text(path, max_lines=1000):
    try:
        p = Path(path)
        if not p.exists():
            return f'로그 파일 없음: {p}'
        lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
        picked = lines[-int(max_lines):]
        return '\n'.join(picked)
    except Exception as e:
        return f'로그 읽기 실패: {e}'

def _diagnostic_recent_files_text(limit=20):
    try:
        settings = _c.load_settings()
        rows = []
        rows.append(f'SETTINGS_PATH: {_c.SETTINGS_PATH}')
        rows.append('')
        max_rows = max(1, _c._safe_int_value(limit, 20))
        for i, fp in enumerate((settings.get('recent_files') or [])[:max_rows], start=1):
            p = Path(fp)
            state = 'exists' if p.exists() else 'missing'
            details = []
            try:
                if p.exists():
                    details.append(_c.format_bytes(_c._path_size(p)))
                    mtime = _c._path_mtime(p)
                    if mtime:
                        details.append(datetime.fromtimestamp(mtime).isoformat(timespec='seconds'))
            except Exception as e:
                details.append(f'stat-error={e}')
            rows.append(f'{i:02d}. [{state}] {p.name}')
            rows.append(f'    path={p}')
            if details:
                rows.append(f'    info={", ".join(str(x) for x in details if x)}')
        if len(rows) <= 2:
            rows.append('최근 파일 없음')
        return '\n'.join(rows)
    except Exception as e:
        return f'최근 파일 진단 생성 실패: {e}'

def _latest_report_text(patterns, max_chars=40000):
    try:
        candidates = []
        for pattern in patterns:
            candidates.extend(_c.REPORT_DIR.glob(pattern))
        candidates = [p for p in candidates if p.is_file()]
        if not candidates:
            return '관련 샘플 검증 리포트 없음'
        latest = max(candidates, key=_c._path_mtime)
        latest_mtime = _c._path_mtime(latest)
        text = latest.read_text(encoding='utf-8', errors='replace')
        modified = datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds") if latest_mtime else '-'
        header = f'LATEST_REPORT: {latest}\nMODIFIED: {modified}\n\n'
        return header + text[-max(1, _c._safe_int_value(max_chars, 40000)):]
    except Exception as e:
        return f'샘플 검증 리포트 읽기 실패: {e}'

_STATE_TIMELINE = deque(maxlen=240)
_STATE_TIMELINE_LOCK = threading.RLock()
_STATE_KEY_MAX_CHARS = 60
_STATE_MESSAGE_MAX_CHARS = 240
_STATE_FIELD_MAX_CHARS = 500

def _state_event_text(value, limit=_STATE_FIELD_MAX_CHARS):
    try:
        text = str(value)
    except Exception:
        return '<unprintable>'
    text = text.replace('\r', '\\r').replace('\n', '\\n')
    max_len = max(8, _c._safe_int_value(limit, _STATE_FIELD_MAX_CHARS))
    if len(text) > max_len:
        return text[:max_len - 3] + '...'
    return text

def record_state_event(category, message='', **fields):
    """Keep a tiny in-memory timeline for diagnosing the last moments before a hang."""
    try:
        row = {
            'ts': datetime.now().isoformat(timespec='milliseconds'),
            'category': _state_event_text(category or 'state', 80),
            'message': _state_event_text(message or '', _STATE_MESSAGE_MAX_CHARS),
        }
        for key, value in fields.items():
            safe_key = _state_event_text(key, _STATE_KEY_MAX_CHARS)
            row[safe_key] = _state_event_text(value, _STATE_FIELD_MAX_CHARS)
        with _STATE_TIMELINE_LOCK:
            _STATE_TIMELINE.append(row)
    except Exception:
        pass

def runtime_state_timeline(limit=120):
    try:
        with _STATE_TIMELINE_LOCK:
            rows = list(_STATE_TIMELINE)[-int(limit):]
        return rows
    except Exception:
        return []

def format_state_timeline(limit=120):
    rows = runtime_state_timeline(limit)
    if not rows:
        return '상태 기록 없음'
    lines = []
    for row in rows:
        base = f"{row.get('ts')} | {row.get('category')} | {row.get('message')}"
        extras = [
            f"{k}={v}" for k, v in row.items()
            if k not in ('ts', 'category', 'message') and v not in ('', None)
        ]
        lines.append(base + (f" | {' '.join(extras)}" if extras else ''))
    return '\n'.join(lines)

def _diagnostic_db_status_text():
    lines = []
    lines.append(f'DB_PATH: {_c.DB_PATH}')
    try:
        if _c.DB_PATH.exists():
            lines.append(f'EXISTS: yes')
            lines.append(f'SIZE  : {_c.format_bytes(_c._path_size(_c.DB_PATH))}')
        else:
            lines.append('EXISTS: no')
            return '\n'.join(lines)
    except Exception as e:
        lines.append(f'STAT ERROR: {e}')
    try:
        import sqlite3
        conn = sqlite3.connect(str(_c.DB_PATH), timeout=10)
        try:
            quick = conn.execute('PRAGMA quick_check').fetchone()
            journal = conn.execute('PRAGMA journal_mode').fetchone()
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            lines.append(f'QUICK_CHECK : {quick[0] if quick else "-"}')
            lines.append(f'JOURNAL_MODE: {journal[0] if journal else "-"}')
            lines.append('TABLES      : ' + ', '.join(row[0] for row in rows))
        finally:
            conn.close()
    except Exception as e:
        lines.append(f'DB CHECK ERROR: {e}')
    return '\n'.join(lines)

def _diagnostic_path_stats(path):
    path = Path(path)
    stats = {
        'path': str(path),
        'exists': path.exists(),
        'files': 0,
        'dirs': 0,
        'bytes': 0,
        'human_bytes': '0B',
        'modified': '',
        'error': '',
    }
    try:
        if not path.exists():
            return stats
        stats['modified'] = datetime.fromtimestamp(_c._path_mtime(path)).isoformat(timespec='seconds') if _c._path_mtime(path) else ''
        if path.is_file():
            stats['files'] = 1
            stats['bytes'] = _c._path_size(path)
        elif path.is_dir():
            for child in path.rglob('*'):
                try:
                    if child.is_symlink():
                        continue
                    if child.is_dir():
                        stats['dirs'] += 1
                    elif child.is_file():
                        stats['files'] += 1
                        stats['bytes'] += _c._path_size(child)
                except Exception:
                    continue
        stats['human_bytes'] = _c.format_bytes(stats['bytes'])
    except Exception as e:
        stats['error'] = str(e)
    return stats

def _diagnostic_storage_summary():
    sections = [
        ('user_data', _c.USER_DATA_DIR),
        ('settings', _c.SETTINGS_PATH),
        ('database', _c.DB_PATH),
        ('logs', _c.LOG_DIR),
        ('tmp', _c.TMP_DIR),
        ('backups', _c.BACKUP_DIR),
        ('reports', _c.REPORT_DIR),
    ]
    data = {
        'cleanup_days': _c.AUTO_CLEANUP_DAYS,
        'release_backup_keep_count': _c.RELEASE_BACKUP_KEEP_COUNT,
        'sections': {name: _diagnostic_path_stats(path) for name, path in sections},
        'release_backups': {
            'path': str(_c.BACKUP_DIR / 'release'),
            'count': 0,
            'latest_txt': '',
            'entries': [],
        },
    }
    release_root = _c.BACKUP_DIR / 'release'
    try:
        latest = release_root / 'latest.txt'
        if latest.exists():
            data['release_backups']['latest_txt'] = latest.read_text(encoding='utf-8', errors='replace').strip()
        if release_root.exists():
            dirs = [p for p in release_root.iterdir() if p.is_dir() and not p.is_symlink()]
            dirs.sort(key=lambda p: p.name, reverse=True)
            data['release_backups']['count'] = len(dirs)
            for path in dirs[:10]:
                item = _diagnostic_path_stats(path)
                item['name'] = path.name
                data['release_backups']['entries'].append(item)
    except Exception as e:
        data['release_backups']['error'] = str(e)
    return data

def _format_diagnostic_storage_summary(summary=None):
    summary = summary or _diagnostic_storage_summary()
    lines = []
    lines.append('사용자 데이터 저장소 요약')
    lines.append('=' * 52)
    lines.append(f"자동 정리 기준: {summary.get('cleanup_days')}일")
    lines.append(f"릴리즈 백업 보존: 최신 {summary.get('release_backup_keep_count')}개")
    lines.append('')
    lines.append('섹션별 용량')
    lines.append('-' * 52)
    for name, item in (summary.get('sections') or {}).items():
        lines.append(
            f"{name:10s} | files={item.get('files', 0):>5} dirs={item.get('dirs', 0):>4} "
            f"size={item.get('human_bytes', '-'):>10} exists={item.get('exists')}"
        )
        lines.append(f"  path={item.get('path')}")
        if item.get('error'):
            lines.append(f"  error={item.get('error')}")
    release = summary.get('release_backups') or {}
    lines.append('')
    lines.append('릴리즈 백업')
    lines.append('-' * 52)
    lines.append(f"path={release.get('path')}")
    lines.append(f"count={release.get('count')} latest={release.get('latest_txt') or '-'}")
    if release.get('error'):
        lines.append(f"error={release.get('error')}")
    for item in release.get('entries') or []:
        lines.append(
            f"- {item.get('name')}: {item.get('human_bytes')} "
            f"files={item.get('files')} modified={item.get('modified') or '-'}"
        )
    return '\n'.join(lines)

def create_diagnostic_report(destination=None, runtime=None, max_log_lines=1500):
    """Create a compact zip report for field troubleshooting."""
    runtime = runtime or _c.check_runtime_environment()
    stamp = _c._file_stamp()
    if destination:
        out = Path(destination)
        if out.suffix.lower() != '.zip':
            out = out / f'mxf-qc-diagnostic-{stamp}.zip'
    else:
        out = _c.REPORT_DIR / f'mxf-qc-diagnostic-{stamp}.zip'
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'app_name': _c.APP_DATA_NAME,
        'app_dir': str(_c.APP_DIR),
        'resource_dir': str(_c.RESOURCE_DIR),
        'user_data_dir': str(_c.USER_DATA_DIR),
        'report_path': str(out),
    }
    tmp_out = out.with_name(f'.{out.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        storage_summary = _diagnostic_storage_summary()
        with zipfile.ZipFile(tmp_out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr('environment.txt', _c.format_runtime_environment(runtime))
            zf.writestr('runtime.json', json.dumps(runtime, ensure_ascii=False, indent=2, default=str))
            zf.writestr('db_status.txt', _diagnostic_db_status_text())
            zf.writestr('storage_summary.json', json.dumps(storage_summary, ensure_ascii=False, indent=2, default=str))
            zf.writestr('storage_summary.txt', _format_diagnostic_storage_summary(storage_summary))
            zf.writestr('child_processes.json', json.dumps(runtime_child_process_status(), ensure_ascii=False, indent=2))
            zf.writestr('state_timeline.json', json.dumps(runtime_state_timeline(), ensure_ascii=False, indent=2))
            zf.writestr('state_timeline.txt', format_state_timeline())
            zf.writestr('recent_files.txt', _diagnostic_recent_files_text())
            zf.writestr(
                'reports/latest_broadcast_sample_report.txt',
                _latest_report_text(('broadcast-sample*.txt',)),
            )
            zf.writestr('logs/player_tail.log', _recent_log_text(_c.LOG_DIR / 'player.log', max_log_lines))
            zf.writestr('logs/migration_tail.log', _recent_log_text(_c.LOG_DIR / 'migration.log', 500))
            try:
                if _c.SETTINGS_PATH.exists():
                    zf.writestr('settings.json', _c.SETTINGS_PATH.read_text(encoding='utf-8', errors='replace'))
            except Exception as e:
                zf.writestr('settings_error.txt', str(e))
        tmp_out.replace(out)
    except Exception:
        try:
            if tmp_out.exists():
                tmp_out.unlink()
        except Exception:
            pass
        raise
    return out

def format_runtime_startup_alert(runtime=None):
    runtime = runtime or _c.check_runtime_environment()
    if runtime.get('ok'):
        return '실행 환경이 정상입니다.'
    lines = ['실행 환경에서 확인이 필요한 항목이 있습니다.', '']
    for item in runtime.get('items', []):
        if item.get('ok'):
            continue
        lines.append(f"- {item.get('name')}: {item.get('role') or '-'}")
        lines.append(f"  조치: {item.get('hint') or item.get('message') or '설치 또는 경로 확인이 필요합니다.'}")
    for item in runtime.get('storage', []):
        if item.get('ok'):
            continue
        lines.append(f"- {item.get('name')}: {item.get('role') or '-'}")
        lines.append(f"  조치: {item.get('hint') or item.get('message') or '쓰기 권한을 확인하세요.'}")
    lines.append('')
    lines.append('상단 ENV 버튼에서 전체 진단 내용을 확인하고, LOG 버튼에서 최근 오류를 볼 수 있습니다.')
    lines.append('다른 PC 배포본에서는 README.txt의 Dependencies 섹션도 함께 확인하세요.')
    return '\n'.join(lines)
