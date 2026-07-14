# 파일 로거(player.log) 생성/로테이션과 예외 기록 헬퍼
import logging as _logging
import time
from logging.handlers import TimedRotatingFileHandler as _TRFHandler

import constants as _c

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
        _c.LOG_DIR.mkdir(parents=True, exist_ok=True)
        current = _c.LOG_DIR / 'player.log'
        if (
            current.exists()
            and not current.is_symlink()
            and current.is_file()
            and _c._path_size(current) > _LOG_MAX_BYTES
        ):
            stamp = _c._file_stamp()
            rotated = _c.LOG_DIR / f'player.log.{stamp}'
            current.replace(rotated)
            warnings.append(f'large log rotated: {rotated.name}')
        backups = []
        for candidate in _c.LOG_DIR.glob('player.log.*'):
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                backups.append(candidate)
            except Exception:
                continue
        backups.sort(key=_c._path_mtime, reverse=True)
        keep_count = max(1, _c._safe_int_value(_LOG_BACKUP_COUNT, 5))
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
        _c.LOG_DIR.mkdir(parents=True, exist_ok=True)
        rotation_warnings = _rotate_large_log_file()
        fh = _SafeTimedRotatingFileHandler(
            _c.LOG_DIR / 'player.log',
            when='midnight', interval=1, backupCount=30,
            encoding='utf-8'
        )
        fh.setLevel(_logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        for msg in rotation_warnings:
            logger.warning(msg)
    except Exception as e:
        logger.warning(f'log file disabled: {_c.LOG_DIR / "player.log"} ({e})')
    for path, err in _c._RUNTIME_DIR_ERRORS:
        logger.warning(f'runtime directory unavailable: {path} ({err})')
    return logger

log = _make_logger()

def _log_exc(label, exc=None):
    """예외를 ERROR 레벨로 기록. except 블록에서 호출"""
    import traceback
    detail = traceback.format_exc() if exc is None else f'{type(exc).__name__}: {exc}'
    log.error(f'{label}\n{detail}')
