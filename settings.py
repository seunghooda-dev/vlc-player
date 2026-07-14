# 사용자 설정(settings.json) 정규화, 저장/로드, 백업 스냅샷 관리
import json
import logging
import math
import os
import shutil
import threading
import time
from pathlib import Path

import constants as _c
from process_registry import _safe_proc_log

DEFAULT_SETTINGS = {
    'volume': 80,
    'playback_rate': 1.0,
    'audio_channels': [1, 2],
    'black_amount': '98',
    'black_threshold': '32',
    'mute_threshold': '-50',
    'mute_duration': '1.0',
    'freeze_noise': '-60',
    'freeze_duration': '1.0',
    'last_dir': 'C:/',
    'recent_files': [],
    'recent_dirs': [],
    'window_size': [1400, 980],
    'splitter_sizes': [980, 420],
}

_settings_cache = None
_settings_lock = threading.RLock()

def _settings_data_copy(data):
    return json.loads(json.dumps(data))

def _default_settings_copy():
    return _settings_data_copy(DEFAULT_SETTINGS)

def _settings_str(value, default):
    try:
        text = str(value).strip()
        return text if text else str(default)
    except Exception:
        return str(default)

def _settings_int(value, default, min_value=None, max_value=None):
    try:
        raw = float(value)
        if not math.isfinite(raw):
            raise ValueError('non-finite number')
        n = int(raw)
    except Exception:
        n = int(default)
    if min_value is not None:
        n = max(int(min_value), n)
    if max_value is not None:
        n = min(int(max_value), n)
    return n

def _settings_float(value, default, min_value=None, max_value=None):
    try:
        n = float(value)
        if not math.isfinite(n):
            raise ValueError('non-finite number')
    except Exception:
        n = float(default)
    if min_value is not None:
        n = max(float(min_value), n)
    if max_value is not None:
        n = min(float(max_value), n)
    return n

def _settings_int_str(value, default, min_value, max_value):
    return str(_settings_int(value, default, min_value, max_value))

def _settings_float_str(value, default, min_value, max_value):
    return f'{_settings_float(value, default, min_value, max_value):g}'

def _settings_db_str(value, default):
    try:
        n = float(value)
        if not math.isfinite(n):
            raise ValueError('non-finite number')
    except Exception:
        n = float(default)
    if n > 0:
        n = float(default)
    return f'{max(-120.0, min(0.0, n)):g}'

def _settings_str_list(value, default, limit=50):
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        value = default
    out = []
    for item in value:
        try:
            text = str(item).strip()
        except Exception:
            continue
        if text:
            out.append(text)
        if len(out) >= int(limit):
            break
    return out

def _settings_int_pair(value, default, min_value=1, max_value=10000):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        value = default
    return [
        _settings_int(value[0], default[0], min_value, max_value),
        _settings_int(value[1], default[1], min_value, max_value),
    ]

def _settings_audio_channels(value):
    if not isinstance(value, (list, tuple)):
        value = DEFAULT_SETTINGS['audio_channels']
    out = []
    for item in value:
        try:
            raw = float(item)
            if not math.isfinite(raw):
                raise ValueError('non-finite number')
            ch = int(raw)
        except Exception:
            continue
        if 1 <= ch <= 8 and ch not in out:
            out.append(ch)
    return out or _settings_data_copy(DEFAULT_SETTINGS['audio_channels'])

def _normalize_settings(data):
    raw = data if isinstance(data, dict) else {}
    normalized = _default_settings_copy()
    normalized.update(raw)
    normalized['volume'] = _settings_int(normalized.get('volume'), DEFAULT_SETTINGS['volume'], 0, 100)
    normalized['playback_rate'] = _settings_float(
        normalized.get('playback_rate'), DEFAULT_SETTINGS['playback_rate'], 0.5, 2.0
    )
    normalized['audio_channels'] = _settings_audio_channels(normalized.get('audio_channels'))
    normalized['black_amount'] = _settings_int_str(
        normalized.get('black_amount'), DEFAULT_SETTINGS['black_amount'], 1, 100
    )
    normalized['black_threshold'] = _settings_int_str(
        normalized.get('black_threshold'), DEFAULT_SETTINGS['black_threshold'], 0, 255
    )
    normalized['mute_threshold'] = _settings_db_str(
        normalized.get('mute_threshold'), DEFAULT_SETTINGS['mute_threshold']
    )
    normalized['mute_duration'] = _settings_float_str(
        normalized.get('mute_duration'), DEFAULT_SETTINGS['mute_duration'], 0.1, 3600.0
    )
    normalized['freeze_noise'] = _settings_db_str(
        normalized.get('freeze_noise'), DEFAULT_SETTINGS['freeze_noise']
    )
    normalized['freeze_duration'] = _settings_float_str(
        normalized.get('freeze_duration'), DEFAULT_SETTINGS['freeze_duration'], 0.1, 3600.0
    )
    normalized['last_dir'] = _settings_str(normalized.get('last_dir'), DEFAULT_SETTINGS['last_dir'])
    normalized['recent_files'] = _settings_str_list(
        normalized.get('recent_files'), DEFAULT_SETTINGS['recent_files'], limit=50
    )
    normalized['recent_dirs'] = _settings_str_list(
        normalized.get('recent_dirs'), DEFAULT_SETTINGS['recent_dirs'], limit=30
    )
    normalized['window_size'] = _settings_int_pair(
        normalized.get('window_size'), DEFAULT_SETTINGS['window_size'], 640, 10000
    )
    normalized['splitter_sizes'] = _settings_int_pair(
        normalized.get('splitter_sizes'), DEFAULT_SETTINGS['splitter_sizes'], 100, 10000
    )
    return normalized

def _settings_log_warning(message):
    try:
        if '_safe_proc_log' in globals():
            _safe_proc_log(logging.WARNING, message)
            return
    except Exception:
        pass
    try:
        logger = globals().get('log')
        if logger:
            logger.warning(message)
    except Exception:
        pass

def _rotate_named_backups(prefix, keep=10):
    try:
        backups = []
        for candidate in _c.BACKUP_DIR.glob(f'{prefix}-*'):
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                backups.append(candidate)
            except Exception:
                continue
        backups.sort(key=_c._path_mtime, reverse=True)
        keep_count = max(1, _c._safe_int_value(keep, 10))
        for old in backups[keep_count:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as e:
        _settings_log_warning(f'backup rotate failed: {e}')

def backup_file_snapshot(path, prefix, min_interval_sec=300, keep=10):
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    try:
        _c.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        marker = _c.BACKUP_DIR / f'.{prefix}.last'
        last = 0.0
        if marker.exists():
            try:
                last = float(marker.read_text(encoding='utf-8') or '0')
            except Exception:
                last = 0.0
        interval = max(0.0, _c._safe_float_value(min_interval_sec, 300.0))
        if interval and now - last < interval:
            return None
        stamp = _c._file_stamp()
        backup = _c.BACKUP_DIR / f'{prefix}-{stamp}{path.suffix}'
        shutil.copy2(path, backup)
        marker_tmp = None
        try:
            marker_tmp = marker.with_name(f'.{marker.name}.{os.getpid()}.{threading.get_ident()}.tmp')
            with marker_tmp.open('w', encoding='utf-8') as fh:
                fh.write(str(now))
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            marker_tmp.replace(marker)
        except Exception:
            try:
                if marker_tmp and marker_tmp.exists():
                    marker_tmp.unlink()
            except Exception:
                pass
        _rotate_named_backups(prefix, keep=keep)
        return backup
    except Exception as e:
        _settings_log_warning(f'{prefix} backup failed: {e}')
        return None

def _backup_corrupt_settings(exc):
    if not _c.SETTINGS_PATH.exists():
        return None
    stamp = _c._file_stamp()
    backup = _c.SETTINGS_PATH.with_name(f'{_c.SETTINGS_PATH.stem}.corrupt-{stamp}{_c.SETTINGS_PATH.suffix}')
    try:
        shutil.copy2(_c.SETTINGS_PATH, backup)
        _settings_log_warning(f'settings.json corrupt; backed up to {backup.name}: {exc}')
        return backup
    except Exception as backup_exc:
        _settings_log_warning(f'settings.json corrupt; backup failed: {backup_exc}')
        return None

def _write_settings_atomic(data):
    tmp_path = _c.SETTINGS_PATH.with_name(
        f'.{_c.SETTINGS_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp'
    )
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        _c.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open('w', encoding='utf-8') as fh:
            fh.write(payload)
            fh.write('\n')
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        tmp_path.replace(_c.SETTINGS_PATH)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise

def load_settings():
    global _settings_cache
    with _settings_lock:
        if _settings_cache is not None:
            return _settings_data_copy(_settings_cache)
        data = _default_settings_copy()
        try:
            if _c.SETTINGS_PATH.exists():
                loaded = json.loads(_c.SETTINGS_PATH.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    data.update(loaded)
                else:
                    raise ValueError('settings root is not an object')
        except Exception as e:
            _backup_corrupt_settings(e)
            data = _default_settings_copy()
            try:
                _write_settings_atomic(data)
            except Exception as write_exc:
                _settings_log_warning(f'settings.json reset failed: {write_exc}')
        _settings_cache = _normalize_settings(data)
        return _settings_data_copy(_settings_cache)

def save_settings(**updates):
    global _settings_cache
    with _settings_lock:
        data = load_settings()
        data.update(updates)
        _settings_cache = _normalize_settings(data)
        try:
            backup_file_snapshot(_c.SETTINGS_PATH, 'settings-auto', min_interval_sec=300, keep=12)
            _write_settings_atomic(_settings_cache)
        except Exception as e:
            _settings_log_warning(f'settings.json save failed: {e}')
        return _settings_data_copy(_settings_cache)
