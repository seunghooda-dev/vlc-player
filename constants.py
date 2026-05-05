"""
constants.py — 색상, 스타일, 경로, 로거
모든 모듈이 import하는 공통 상수
"""
"""
MXF QC Player - PyQt6 완전판
파일 탐색 + 비디오 플레이어 + DB + STT + 씬감지 + 검색
"""

import sys, os, json, subprocess, hashlib, csv, shutil, threading, atexit
from pathlib import Path
from datetime import datetime

# ── 글꼴 ──────────────────────────────────────────────────
# Windows 11 기준으로 더 현대적인 UI/숫자 글꼴을 우선 사용하고,
# 없는 환경에서는 기존 Windows 기본 글꼴로 자연스럽게 내려간다.
APP_FONT_QT = "Segoe UI Variable Text"
MONO_FONT_QT = "Cascadia Mono"
APP_FONT_CSS = "'Segoe UI Variable Text','Segoe UI','Malgun Gothic'"
MONO_FONT_CSS = "'Cascadia Mono','Consolas','D2Coding'"

def css_font(family=None):
    name = (family or APP_FONT_QT).strip()
    if name in ("맑은 고딕", "Malgun Gothic", "Segoe UI", "Segoe UI Variable Text"):
        return APP_FONT_CSS
    if name in ("Consolas", "Cascadia Mono", "D2Coding", "monospace"):
        return MONO_FONT_CSS
    return name

# ── 색상 ──────────────────────────────────────────────────
C = {
    # 배경 계층
    'bg'     :'#0f1014',   # 최상위 배경
    'panel'  :'#15171d',   # 패널
    'panel2' :'#0a0b0f',   # 서브패널
    'panel3' :'#1b1e27',   # 강조 패널
    'border' :'#272b35',   # 구분선
    'border2':'#3a4050',   # 활성 구분선
    'input'  :'#181b22',   # 입력창
    # 강조색 — 단일 포인트 컬러 + 용도별
    'blue'   :'#5AA7FF',   # 주 강조 (선택, 포커스)
    'yellow' :'#FFD166',   # 타임코드, CUE
    'green'  :'#4ADE80',   # 재생, 완료
    'orange' :'#FB923C',   # FPS, 경고
    'teal'   :'#2DD4BF',   # SAFE, 채널
    'red'    :'#FF5C7A',   # 에러
    'purple' :'#B794F4',   # STT
    # 텍스트 계층
    'text0'  :'#F3F4F8',   # 주 텍스트
    'text1'  :'#A7ADBE',   # 보조 텍스트
    'text2'  :'#6F778B',   # 설명 텍스트
    'text3'  :'#3F4555',   # 비활성
}

STYLE = f"""
/* ── 툴팁 ── */
QToolTip {{
    background-color: #20242d;
    color: {C['text0']};
    border: 1px solid {C['border2']};
    padding: 7px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    border-radius: 6px;
}}

/* ── 기본 ── */
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['text0']};
    font-family: {APP_FONT_CSS};
    font-size: 13px;
}}
QSplitter::handle {{
    background-color: {C['border']};
    width: 1px;
}}

/* ── 상태바 ── */
QStatusBar {{
    background-color: #0b0c10;
    color: {C['text2']};
    font-family: {MONO_FONT_CSS};
    font-size: 11px;
    border-top: 1px solid {C['border']};
    padding: 3px 12px;
}}

/* ── 탭 ── */
QTabWidget::pane {{
    border: none;
    background-color: {C['panel2']};
    border-top: 1px solid {C['border']};
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {C['text2']};
    padding: 10px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 500;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {C['text0']};
    border-bottom: 2px solid {C['blue']};
    background-color: rgba(90, 167, 255, 22);
}}
QTabBar::tab:hover {{
    color: {C['text0']};
    background-color: rgba(255,255,255,7);
}}

/* ── 리스트 ── */
QListWidget {{
    background-color: {C['panel2']};
    border: none;
    color: {C['text0']};
    outline: none;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {C['border']};
}}
QListWidget::item:selected {{
    background-color: rgba(90, 167, 255, 26);
    color: {C['text0']};
}}
QListWidget::item:hover {{
    background-color: rgba(255,255,255,7);
}}

/* ── 입력창 ── */
QLineEdit {{
    background-color: {C['input']};
    border: 1px solid {C['border']};
    border-radius: 5px;
    color: {C['text0']};
    padding: 6px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    selection-background-color: rgba(90,167,255,70);
}}
QLineEdit:focus {{
    border: 1px solid rgba(90,167,255,140);
    background-color: #1f2430;
}}

/* ── 버튼 기본 ── */
QPushButton {{
    background-color: {C['panel3']};
    color: {C['text0']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: #222734;
    border-color: {C['border2']};
}}
QPushButton:pressed {{
    background-color: #12151c;
    padding-top: 7px;
}}
QPushButton:disabled {{
    color: {C['text3']};
    background-color: #101218;
    border-color: #1c2029;
}}

/* ── 슬라이더 ── */
QSlider::groove:horizontal {{
    background: #242936;
    height: 4px;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 {C['teal']});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {C['text0']};
    border: 1px solid rgba(90,167,255,140);
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{
    background: #ffffff;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -6px 0;
}}

/* ── 테이블 ── */
QTableWidget {{
    background-color: {C['panel2']};
    border: none;
    color: {C['text0']};
    gridline-color: {C['border']};
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {C['border']};
}}
QTableWidget::item:selected {{
    background-color: rgba(90,167,255,28);
    color: {C['text0']};
}}
QHeaderView::section {{
    background-color: {C['panel']};
    color: {C['text2']};
    border: none;
    border-right: 1px solid {C['border']};
    border-bottom: 1px solid {C['border']};
    padding: 6px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 11px;
    font-weight: 600;
}}

/* ── 스크롤바 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(167,173,190,45);
    border-radius: 2px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(167,173,190,80);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(167,173,190,45);
    border-radius: 2px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── 프로그레스바 ── */
QProgressBar {{
    background: #242936;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: {C['text1']};
    font-size: 10px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 {C['teal']});
    border-radius: 2px;
}}
"""

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
DB_PATH    = BASE_DIR / "archive.db"
SETTINGS_PATH = BASE_DIR / "settings.json"
LOG_DIR    = BASE_DIR / "logs"
TMP_DIR    = BASE_DIR / "tmp"
_RUNTIME_DIR_ERRORS = []

def _ensure_runtime_dir(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        _RUNTIME_DIR_ERRORS.append((str(path), str(e)))
        return False

_ensure_runtime_dir(LOG_DIR)
_ensure_runtime_dir(TMP_DIR)

def _tool_candidates(name):
    exe_name = f'{name}.exe' if os.name == 'nt' and not name.lower().endswith('.exe') else name
    for root in (APP_DIR, APP_DIR / 'tools', APP_DIR / 'bin', RESOURCE_DIR, RESOURCE_DIR / 'tools', RESOURCE_DIR / 'bin'):
        yield root / name
        yield root / exe_name

def resolve_tool_command(name):
    for path in _tool_candidates(name):
        if path.exists():
            return str(path)
    found = shutil.which(name)
    return found or name

FFMPEG     = resolve_tool_command("ffmpeg")
FFPROBE    = resolve_tool_command("ffprobe")
FFPLAY     = resolve_tool_command("ffplay")

def _runtime_search_paths():
    paths = []
    seen = set()
    for path in (APP_DIR, APP_DIR / 'tools', APP_DIR / 'bin', RESOURCE_DIR, RESOURCE_DIR / 'tools', RESOURCE_DIR / 'bin'):
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            paths.append(str(path))
    paths.append('Windows PATH')
    return paths

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

def check_runtime_storage():
    return [
        _check_write_location('앱 폴더', BASE_DIR, 'archive.db, settings.json 생성/갱신'),
        _check_write_location('로그 폴더', LOG_DIR, 'logs/player.log 기록'),
        _check_write_location('임시 폴더', TMP_DIR, '분석 캐시와 임시 작업 파일 생성'),
    ]

DEFAULT_SETTINGS = {
    'volume': 80,
    'playback_rate': 1.0,
    'audio_channels': [1, 2],
    'black_amount': '98',
    'black_threshold': '32',
    'mute_threshold': '-50',
    'mute_duration': '1.0',
    'last_dir': 'C:/',
    'recent_files': [],
    'recent_dirs': [],
    'window_size': [1400, 980],
    'splitter_sizes': [980, 420],
}

_settings_cache = None
_settings_lock = threading.RLock()

def load_settings():
    global _settings_cache
    with _settings_lock:
        if _settings_cache is not None:
            return dict(_settings_cache)
        data = dict(DEFAULT_SETTINGS)
        try:
            if SETTINGS_PATH.exists():
                loaded = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    data.update(loaded)
        except Exception:
            pass
        _settings_cache = data
        return dict(_settings_cache)

def save_settings(**updates):
    global _settings_cache
    with _settings_lock:
        data = load_settings()
        data.update(updates)
        _settings_cache = data
        try:
            SETTINGS_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
        except Exception:
            pass
        return dict(data)

def _hidden_subprocess_flags():
    return 0x08000000 if os.name == 'nt' else 0

def _candidate_vlc_dirs():
    seen = set()
    candidates = []
    for env_name in ('VLC_HOME', 'VLC_PATH'):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw))
    for root in (APP_DIR, RESOURCE_DIR):
        candidates.extend([
            root,
            root / 'VLC',
            root / 'vlc',
            root / 'VideoLAN' / 'VLC',
        ])
    for env_name in ('ProgramFiles', 'ProgramFiles(x86)'):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw) / 'VideoLAN' / 'VLC')
    vlc_exe = shutil.which('vlc') or shutil.which('vlc.exe')
    if vlc_exe:
        candidates.append(Path(vlc_exe).parent)
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            yield path

def resolve_vlc_dir():
    for path in _candidate_vlc_dirs():
        if (path / 'libvlc.dll').exists():
            return path
    return None

VLC_DIR = resolve_vlc_dir()

def _classify_runtime_source(path):
    try:
        p = Path(path).resolve()
    except Exception:
        return '알 수 없음'
    checks = [
        (APP_DIR / 'tools', '앱 tools 폴더'),
        (APP_DIR / 'bin', '앱 bin 폴더'),
        (APP_DIR, '앱 폴더'),
        (RESOURCE_DIR / 'tools', '내장 tools 폴더'),
        (RESOURCE_DIR / 'bin', '내장 bin 폴더'),
        (RESOURCE_DIR, '내장 리소스 폴더'),
    ]
    for root, label in checks:
        try:
            p.relative_to(root.resolve())
            return label
        except Exception:
            pass
    return 'Windows PATH / 시스템 설치'

def _check_command(name, command, role='', required=True):
    exe = str(command) if Path(str(command)).exists() else shutil.which(command)
    if not exe:
        return {
            'name': name,
            'ok': False,
            'path': '',
            'message': f'{command} 실행 파일을 PATH 또는 앱 폴더/tools에서 찾을 수 없습니다.',
            'version': '',
            'source': '찾을 수 없음',
            'role': role,
            'required': required,
            'hint': f'{command}.exe를 앱 폴더의 tools\\ 안에 넣거나 Windows PATH에 등록하세요.',
        }
    try:
        proc = subprocess.run(
            [exe, '-version'],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_hidden_subprocess_flags(),
        )
        first_line = (proc.stdout or proc.stderr or '').splitlines()
        return {
            'name': name,
            'ok': proc.returncode == 0,
            'path': exe,
            'message': first_line[0] if first_line else exe,
            'version': first_line[0] if first_line else '',
            'source': _classify_runtime_source(exe),
            'role': role,
            'required': required,
            'hint': '',
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': exe,
            'message': str(e),
            'version': '',
            'source': _classify_runtime_source(exe),
            'role': role,
            'required': required,
            'hint': f'{exe} 실행 권한이나 손상 여부를 확인하세요.',
        }

def check_runtime_environment():
    items = [
        _check_command('FFmpeg', FFMPEG, '오디오 미터, 블랙/뮤트 검출, 선택 채널 믹스', True),
        _check_command('FFprobe', FFPROBE, 'MXF 메타데이터, 길이, 해상도, 오디오 채널 확인', True),
        _check_command('FFplay', FFPLAY, '체크된 오디오 채널 실제 출력', True),
    ]
    if VLC_DIR:
        items.append({
            'name': 'VLC',
            'ok': True,
            'path': str(VLC_DIR),
            'message': str(VLC_DIR / 'libvlc.dll'),
            'version': str(VLC_DIR / 'libvlc.dll'),
            'source': _classify_runtime_source(VLC_DIR),
            'role': 'MXF 원본 영상 재생',
            'required': True,
            'hint': '',
        })
    else:
        items.append({
            'name': 'VLC',
            'ok': False,
            'path': '',
            'message': r'C:\Program Files\VideoLAN\VLC\libvlc.dll 을 찾을 수 없습니다.',
            'version': '',
            'source': '찾을 수 없음',
            'role': 'MXF 원본 영상 재생',
            'required': True,
            'hint': r'VLC를 설치하거나 libvlc.dll이 포함된 VLC 폴더를 앱 폴더\VLC 또는 C:\Program Files\VideoLAN\VLC에 두세요.',
        })
    missing = [item['name'] for item in items if not item['ok']]
    missing_required = [item['name'] for item in items if not item['ok'] and item.get('required')]
    storage = check_runtime_storage()
    storage_issues = [item['name'] for item in storage if not item['ok']]
    problems = missing + storage_issues
    return {
        'ok': not problems,
        'items': items,
        'storage': storage,
        'missing': missing,
        'missing_required': missing_required,
        'storage_issues': storage_issues,
        'problems': problems,
        'can_start': 'VLC' not in missing_required,
        'search_paths': _runtime_search_paths(),
    }

def format_runtime_environment(runtime=None):
    runtime = runtime or check_runtime_environment()
    lines = []
    lines.append('MXF QC Player V.1.0 실행 환경 진단')
    lines.append('=' * 42)
    lines.append(f"상태: {'정상' if runtime.get('ok') else '확인 필요'}")
    if runtime.get('problems'):
        lines.append(f"문제: {', '.join(runtime.get('problems', []))}")
    else:
        lines.append('문제: 없음')
    lines.append('')
    lines.append('구성 요소')
    lines.append('-' * 42)
    for item in runtime.get('items', []):
        mark = 'OK' if item.get('ok') else 'MISSING'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  출처: {item.get('source') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  조치: {item.get('hint')}")
        lines.append('')
    lines.append('저장 위치')
    lines.append('-' * 42)
    for item in runtime.get('storage', []):
        mark = 'OK' if item.get('ok') else 'FAILED'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  조치: {item.get('hint')}")
        lines.append('')
    lines.append('검색 위치')
    lines.append('-' * 42)
    for path in runtime.get('search_paths', []):
        lines.append(f"- {path}")
    lines.append('')
    lines.append('기능 영향')
    lines.append('-' * 42)
    lines.append('- VLC 누락: MXF 영상 재생 불가')
    lines.append('- FFmpeg 누락: 오디오 미터, 블랙/뮤트 검출, 채널 믹스 제한')
    lines.append('- FFprobe 누락: 파일 길이/해상도/채널 정보 확인 제한')
    lines.append('- FFplay 누락: 체크박스 기반 오디오 출력 제한')
    lines.append('- 저장 위치 쓰기 실패: 설정 저장, 로그 기록, 분석 캐시 생성 제한')
    return '\n'.join(lines)

# ── 보조 프로세스 추적/정리 ──────────────────────────────
_CHILD_PROCS = {}
_CHILD_PROC_LOCK = threading.RLock()
_CHILD_JOB_HANDLE = None
_CHILD_JOB_LOCK = threading.RLock()

def _safe_proc_log(level, message):
    try:
        globals().get('log').log(level, message)
    except Exception:
        pass

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
            _safe_proc_log(_logging.WARNING if '_logging' in globals() else 30,
                           f'child job object unavailable: {e}')
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
            _safe_proc_log(_logging.WARNING if '_logging' in globals() else 30,
                           f'{label} job assign failed pid={getattr(proc, "pid", "?")} err={err}')
    except Exception as e:
        _safe_proc_log(_logging.DEBUG if '_logging' in globals() else 10,
                       f'{label} job assign exception: {e}')

def register_child_process(proc, label='process'):
    if not proc:
        return proc
    try:
        with _CHILD_PROC_LOCK:
            _CHILD_PROCS[int(proc.pid)] = (proc, label)
        _assign_child_to_job(proc, label)
    except Exception:
        pass
    return proc

def unregister_child_process(proc):
    if not proc:
        return
    try:
        with _CHILD_PROC_LOCK:
            _CHILD_PROCS.pop(int(proc.pid), None)
    except Exception:
        pass

def terminate_child_process(proc, label='process', timeout=0.7):
    if not proc:
        return
    try:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception as e:
                _safe_proc_log(_logging.DEBUG if '_logging' in globals() else 10,
                               f'{label} terminate failed: {e}')
            try:
                proc.wait(timeout=timeout)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=timeout)
                except Exception as e:
                    _safe_proc_log(_logging.DEBUG if '_logging' in globals() else 10,
                                   f'{label} kill failed: {e}')
    finally:
        unregister_child_process(proc)

def cleanup_child_processes():
    with _CHILD_PROC_LOCK:
        procs = list(_CHILD_PROCS.values())
    for proc, label in procs:
        terminate_child_process(proc, label)

# ── 로거 ──────────────────────────────────────────────
import logging as _logging
from logging.handlers import TimedRotatingFileHandler as _TRFHandler

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
        fh = _TRFHandler(
            LOG_DIR / 'player.log',
            when='midnight', interval=1, backupCount=30,
            encoding='utf-8'
        )
        fh.setLevel(_logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        logger.warning(f'log file disabled: {LOG_DIR / "player.log"} ({e})')
    for path, err in _RUNTIME_DIR_ERRORS:
        logger.warning(f'runtime directory unavailable: {path} ({err})')
    return logger

log = _make_logger()
atexit.register(cleanup_child_processes)

def _log_exc(label, exc=None):
    """예외를 ERROR 레벨로 기록. except 블록에서 호출"""
    import traceback
    detail = traceback.format_exc() if exc is None else f'{type(exc).__name__}: {exc}'
    log.error(f'{label}\n{detail}')

# ── 유틸 함수 ─────────────────────────────────────────────
def is_df_fps(fps):
    return abs(fps - round(fps)) > 0.01

def sec_to_tc(sec, fps=29.97, df=None):
    if sec is None or sec < 0: sec = 0.0
    if df is None: df = False
    nom = round(fps)
    if df and nom in (30, 60):
        drop = 2 if nom == 30 else 4
        total_f = round(sec * fps)
        d  = total_f // (nom * 600 - drop * 9)
        m1 = total_f %  (nom * 600 - drop * 9)
        m  = max(0, (m1 - drop) // (nom * 60 - drop))
        total_f += drop * (9 * d + m)
    else:
        total_f = round(sec * nom)
    ff = total_f % nom
    ss = (total_f // nom) % 60
    mm = (total_f // nom // 60) % 60
    hh =  total_f // nom // 3600
    sep = ';' if df else ':'
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"

def sec_fmt(s):
    return f"{int(s//60):02d}:{int(s%60):02d}"

def probe(filepath):
    try:
        r = subprocess.run(
            [FFPROBE, "-v","quiet","-print_format","json",
             "-show_format","-show_streams", filepath],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0: return {}
        d   = json.loads(r.stdout)
        fmt = d.get("format", {})
        info = {
            "filename"    : Path(filepath).name,
            "filepath"    : filepath,
            "duration"    : float(fmt.get("duration", 0)),
            "size"        : int(fmt.get("size", 0)),
            "bit_rate"    : int(fmt.get("bit_rate", 0) or 0),
            "fps"         : 29.97,
            "width"       : 0, "height": 0,
            "codec"       : "", "channels": 0,
            "timecode"    : "",
            "format_short": Path(filepath).suffix.upper().lstrip(".")
        }
        for s in d.get("streams", []):
            if s.get("codec_type") == "video":
                info["codec"]  = s.get("codec_name", "").upper()
                info["width"]  = s.get("width", 0)
                info["height"] = s.get("height", 0)
                try:
                    n, dv = s.get("r_frame_rate","30/1").split("/")
                    info["fps"] = round(int(n)/int(dv), 3)
                except Exception as e: log.debug(f'fps parse: {e}')
                tc = s.get("tags", {}).get("timecode", "")
                if tc: info["timecode"] = tc
            elif s.get("codec_type") == "audio":
                info["channels"] = max(info["channels"], s.get("channels", 0))
        if not info["timecode"]:
            info["timecode"] = fmt.get("tags", {}).get("timecode", "")
        fps = info["fps"]
        info["df"] = is_df_fps(fps)
        if info["width"] >= 3840 and abs(fps-60) < 1:
            info["fps"] = 59.94; info["df"] = True
        elif info["width"] >= 1920 and abs(fps-30) < 1:
            info["fps"] = 29.97; info["df"] = True
        info["tc_offset"] = 0.0
        if info["timecode"]:
            try:
                parts = info["timecode"].replace(";",":").split(":")
                if len(parts) == 4:
                    h,m,s,f = int(parts[0]),int(parts[1]),int(parts[2]),int(parts[3])
                    info["tc_offset"] = h*3600 + m*60 + s + f/round(info["fps"])
            except Exception as e: log.debug(f'tc_offset parse: {e}')
        ext = Path(filepath).suffix.upper().lstrip(".")
        info["format_short"] = "XDCAM" if ext == "MXF" else ext
        return info
    except Exception as e:
        log.warning(f'probe failed: {e}')
        return {}

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
