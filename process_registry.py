"""process_registry.py — 자식 프로세스 추적/정리 및 heavy 분석 슬롯 관리

constants.py 에서 분리된 순수 leaf 모듈. 로거/상태 이벤트 기록은 constants.py 가
set_logger / set_state_event_recorder 로 주입하는 훅을 통해서만 이뤄지며, 이 모듈
자체는 constants 를 import 하지 않는다.
"""
import atexit
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

_logger = None          # constants가 로거 준비 후 set_logger(log)로 주입
_state_recorder = None  # constants가 record_state_event 정의 후 주입


def set_logger(logger):
    global _logger
    _logger = logger


def set_state_event_recorder(fn):
    global _state_recorder
    _state_recorder = fn


def _record_state(*args, **kwargs):
    if _state_recorder is None:
        return
    _state_recorder(*args, **kwargs)


_CHILD_PROCS = {}
_CHILD_PROC_LOCK = threading.RLock()
_CHILD_JOB_HANDLE = None
_CHILD_JOB_LOCK = threading.RLock()
_HEAVY_ANALYSIS_LOCK = threading.RLock()
_HEAVY_ANALYSIS_OWNER = None
_HEAVY_ANALYSIS_STARTED = 0.0


def heavy_analysis_status():
    with _HEAVY_ANALYSIS_LOCK:
        if not _HEAVY_ANALYSIS_OWNER:
            return {'running': False, 'owner': None, 'elapsed': 0.0}
        return {
            'running': True,
            'owner': _HEAVY_ANALYSIS_OWNER,
            'elapsed': max(0.0, time.monotonic() - _HEAVY_ANALYSIS_STARTED),
        }


def acquire_heavy_analysis_slot(label):
    """Allow only one heavy FFmpeg analysis at a time."""
    global _HEAVY_ANALYSIS_OWNER, _HEAVY_ANALYSIS_STARTED
    with _HEAVY_ANALYSIS_LOCK:
        if _HEAVY_ANALYSIS_OWNER:
            _record_state(
                'analysis-limit',
                'blocked',
                requested=label,
                owner=_HEAVY_ANALYSIS_OWNER,
                elapsed=f'{time.monotonic() - _HEAVY_ANALYSIS_STARTED:.1f}s',
            )
            return False
        _HEAVY_ANALYSIS_OWNER = str(label or 'analysis')
        _HEAVY_ANALYSIS_STARTED = time.monotonic()
        _record_state('analysis-limit', 'acquired', owner=_HEAVY_ANALYSIS_OWNER)
        return True


def release_heavy_analysis_slot(label=None):
    global _HEAVY_ANALYSIS_OWNER, _HEAVY_ANALYSIS_STARTED
    with _HEAVY_ANALYSIS_LOCK:
        owner = _HEAVY_ANALYSIS_OWNER
        if not owner:
            return
        if label and owner != label:
            _record_state(
                'analysis-limit',
                'release skipped',
                requested=label,
                owner=owner,
                elapsed=f'{max(0.0, time.monotonic() - _HEAVY_ANALYSIS_STARTED):.1f}s',
            )
            return
        elapsed = max(0.0, time.monotonic() - _HEAVY_ANALYSIS_STARTED)
        _record_state('analysis-limit', 'released', owner=owner, elapsed=f'{elapsed:.1f}s')
        _HEAVY_ANALYSIS_OWNER = None
        _HEAVY_ANALYSIS_STARTED = 0.0


def _safe_proc_log(level, message):
    try:
        _logger.log(level, message)
    except Exception:
        pass


def _hidden_subprocess_flags():
    return 0x08000000 if os.name == 'nt' else 0


def _windows_child_job():
    """Windows Job Object: parent가 비정상 종료돼도 등록된 보조 프로세스를 같이 종료."""
    global _CHILD_JOB_HANDLE
    if os.name != 'nt':
        return None
    with _CHILD_JOB_LOCK:
        if _CHILD_JOB_HANDLE:
            return _CHILD_JOB_HANDLE
        try:
            import ctypes
            from ctypes import wintypes

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ('PerProcessUserTimeLimit', ctypes.c_longlong),
                    ('PerJobUserTimeLimit', ctypes.c_longlong),
                    ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t),
                    ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t),
                    ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('ReadOperationCount', ctypes.c_ulonglong),
                    ('WriteOperationCount', ctypes.c_ulonglong),
                    ('OtherOperationCount', ctypes.c_ulonglong),
                    ('ReadTransferCount', ctypes.c_ulonglong),
                    ('WriteTransferCount', ctypes.c_ulonglong),
                    ('OtherTransferCount', ctypes.c_ulonglong),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ('IoInfo', IO_COUNTERS),
                    ('ProcessMemoryLimit', ctypes.c_size_t),
                    ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t),
                    ('PeakJobMemoryUsed', ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.SetInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD
            ]
            kernel32.SetInformationJobObject.restype = wintypes.BOOL

            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())

            _CHILD_JOB_HANDLE = handle
            return _CHILD_JOB_HANDLE
        except Exception as e:
            _safe_proc_log(logging.WARNING, f'child job object unavailable: {e}')
            return None


def _assign_child_to_job(proc, label='process'):
    if os.name != 'nt' or not proc:
        return
    try:
        handle = _windows_child_job()
        if not handle:
            return
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        proc_handle = wintypes.HANDLE(int(proc._handle))
        if not kernel32.AssignProcessToJobObject(handle, proc_handle):
            err = ctypes.get_last_error()
            _safe_proc_log(logging.WARNING, f'{label} job assign failed pid={getattr(proc, "pid", "?")} err={err}')
    except Exception as e:
        _safe_proc_log(logging.DEBUG, f'{label} job assign exception: {e}')


def register_child_process(proc, label='process'):
    if not proc:
        return proc
    try:
        with _CHILD_PROC_LOCK:
            _CHILD_PROCS[int(proc.pid)] = (proc, label)
        _record_state('child-process', 'start', pid=getattr(proc, 'pid', '-'), label=label)
        _assign_child_to_job(proc, label)
    except Exception:
        pass
    return proc


def unregister_child_process(proc):
    if not proc:
        return
    try:
        with _CHILD_PROC_LOCK:
            row = _CHILD_PROCS.pop(int(proc.pid), None)
        if not row:
            return
        label = row[1]
        _record_state('child-process', 'end', pid=getattr(proc, 'pid', '-'), label=label)
    except Exception:
        pass


def _short_process_command(args, limit=220):
    try:
        if isinstance(args, (list, tuple)):
            parts = []
            for i, value in enumerate(args):
                text = str(value)
                if i == 0:
                    try:
                        text = Path(text).name or text
                    except Exception:
                        pass
                parts.append(text)
            text = ' '.join(parts)
        else:
            text = str(args or '')
        text = ' '.join(text.split())
        if len(text) > limit:
            return text[:limit - 3] + '...'
        return text
    except Exception:
        return ''


def runtime_child_process_status():
    rows = []
    exited = []
    try:
        with _CHILD_PROC_LOCK:
            items = list(_CHILD_PROCS.items())
        for pid, (proc, label) in sorted(items, key=lambda item: item[0]):
            try:
                rc = proc.poll()
                if rc is not None:
                    exited.append((int(pid), proc, label))
                rows.append({
                    'pid': int(pid),
                    'label': label,
                    'state': 'running' if rc is None else f'exited({rc})',
                    'returncode': rc,
                    'command': _short_process_command(getattr(proc, 'args', '')),
                })
            except Exception as e:
                rows.append({
                    'pid': int(pid),
                    'label': label,
                    'state': 'unknown',
                    'returncode': None,
                    'command': '',
                    'error': str(e),
                })
        if exited:
            with _CHILD_PROC_LOCK:
                for pid, proc, label in exited:
                    row = _CHILD_PROCS.get(pid)
                    if row and row[0] is proc:
                        _CHILD_PROCS.pop(pid, None)
                        _record_state('child-process', 'end', pid=pid, label=label)
    except Exception as e:
        return [{'pid': 0, 'label': 'child registry', 'state': 'error', 'returncode': None, 'command': '', 'error': str(e)}]
    return rows


def _running_child_processes(rows=None):
    rows = rows if rows is not None else runtime_child_process_status()
    return [row for row in rows if row.get('state') == 'running']


def terminate_child_process(proc, label='process', timeout=0.7):
    if not proc:
        return
    try:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception as e:
                _safe_proc_log(logging.DEBUG, f'{label} terminate failed: {e}')
            try:
                proc.wait(timeout=timeout)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=timeout)
                except Exception as e:
                    _safe_proc_log(logging.DEBUG, f'{label} kill failed: {e}')
    finally:
        unregister_child_process(proc)


def cleanup_child_processes():
    before = runtime_child_process_status()
    running_before = _running_child_processes(before)
    if running_before:
        for row in running_before:
            _safe_proc_log(
                logging.INFO,
                f"child cleanup before: pid={row.get('pid')} "
                f"state={row.get('state')} label={row.get('label')} "
                f"cmd={row.get('command') or '-'}"
            )
    with _CHILD_PROC_LOCK:
        procs = list(_CHILD_PROCS.values())
    for proc, label in procs:
        terminate_child_process(proc, label)
    after = runtime_child_process_status()
    running_after = _running_child_processes(after)
    if running_after:
        for row in running_after:
            _safe_proc_log(
                logging.WARNING,
                f"child cleanup remaining: pid={row.get('pid')} "
                f"state={row.get('state')} label={row.get('label')} "
                f"cmd={row.get('command') or '-'}"
            )
    else:
        _safe_proc_log(logging.INFO, 'child cleanup complete: no registered child processes')
    return {
        'before': before,
        'after': after,
        'running_before': len(running_before),
        'running_after': len(running_after),
    }


def cleanup_orphan_audio_processes():
    """이전 버전에서 남은 ffmpeg/ffplay 오디오 믹스 고아 프로세스만 좁게 정리."""
    if os.name != 'nt':
        return 0
    script = r"""
$all = Get-CimInstance Win32_Process
$alive = @{}
foreach ($p in $all) { $alive[[int]$p.ProcessId] = $true }
$targets = @()
foreach ($p in $all) {
    $name = [string]$p.Name
    if ($name -ne 'ffplay.exe' -and $name -ne 'ffmpeg.exe') { continue }
    $cmd = [string]$p.CommandLine
    if (-not $cmd) { continue }
    $parentAlive = $alive.ContainsKey([int]$p.ParentProcessId)
    if ($parentAlive) { continue }
    $isAudioMixFfplay = (
        $name -eq 'ffplay.exe' -and
        $cmd.Contains('-nodisp') -and
        $cmd.Contains('-autoexit') -and
        $cmd.Contains('s16le') -and
        $cmd.Contains('48000') -and
        $cmd.Contains('-i -')
    )
    $isAudioMixFfmpeg = (
        $name -eq 'ffmpeg.exe' -and
        $cmd.Contains('[aout]') -and
        $cmd.Contains('pcm_s16le') -and
        $cmd.Contains('pipe:1')
    )
    if ($isAudioMixFfplay -or $isAudioMixFfmpeg) { $targets += $p }
}
foreach ($p in $targets) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "$($p.ProcessId) $($p.Name)"
}
"""
    try:
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_hidden_subprocess_flags(),
        )
        cleaned = [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]
        for line in cleaned:
            _safe_proc_log(logging.INFO, f'orphan audio process cleaned: {line}')
        if proc.returncode != 0:
            detail = (proc.stderr or '').strip()
            if detail:
                _safe_proc_log(logging.DEBUG, f'orphan audio cleanup rc={proc.returncode}: {detail[:300]}')
        return len(cleaned)
    except Exception as e:
        _safe_proc_log(logging.DEBUG, f'orphan audio cleanup skipped: {e}')
        return 0


atexit.register(cleanup_child_processes)
