"""
constants.py — 색상, 스타일, 경로, 로거
모든 모듈이 import하는 공통 상수
"""
"""
MXF QC Player - PyQt6 완전판
파일 탐색 + 비디오 플레이어 + DB + STT + 씬감지 + 검색
"""

import sys, os, json, subprocess, hashlib, csv, shutil, threading, atexit, time, zipfile, math
from collections import deque
from pathlib import Path
from datetime import datetime

# ── 글꼴 ──────────────────────────────────────────────────
# Windows 11 기준으로 더 현대적인 UI/숫자 글꼴을 우선 사용하고,
# 없는 환경에서는 기존 Windows 기본 글꼴로 자연스럽게 내려간다.
APP_FONT_QT = "Segoe UI Variable Text"
MONO_FONT_QT = "Cascadia Mono"
APP_FONT_CSS = "'Pretendard','Inter','Segoe UI Variable Text','Segoe UI','Noto Sans KR','Malgun Gothic'"
MONO_FONT_CSS = "'JetBrains Mono','Cascadia Mono','Consolas','D2Coding'"

def css_font(family=None):
    name = (family or APP_FONT_QT).strip()
    if name in ("맑은 고딕", "Malgun Gothic", "Segoe UI", "Segoe UI Variable Text",
                "Pretendard", "Inter", "Noto Sans KR"):
        return APP_FONT_CSS
    if name in ("Consolas", "Cascadia Mono", "JetBrains Mono", "D2Coding", "monospace"):
        return MONO_FONT_CSS
    return name

# ── 색상 ──────────────────────────────────────────────────
C = {
    # 배경 계층
    'bg'     :'#090B10',   # 최상위 배경
    'panel'  :'#121722',   # 패널
    'panel2' :'#07090D',   # 서브패널
    'panel3' :'#1A2130',   # 강조 패널
    'border' :'#252D3B',   # 구분선
    'border2':'#46536A',   # 활성 구분선
    'input'  :'#151B26',   # 입력창
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
    background-color: #171c25;
    color: {C['text0']};
    border: 1px solid #465166;
    padding: 7px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    border-radius: 7px;
}}

/* ── 기본 ── */
QMainWindow, QWidget {{
    background-color: #090B10;
    color: {C['text0']};
    font-family: {APP_FONT_CSS};
    font-size: 13px;
}}
QSplitter::handle {{
    background-color: #1E2635;
    width: 1px;
}}

/* ── 상태바 ── */
QStatusBar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #07090D,stop:0.5 #111927,stop:1 #07090D);
    color: {C['text2']};
    font-family: {MONO_FONT_CSS};
    font-size: 11px;
    border-top: 1px solid #202633;
    padding: 3px 12px;
}}

/* ── 탭 ── */
QTabWidget::pane {{
    border: none;
    background-color: #07090D;
    border-top: 1px solid #202633;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {C['text2']};
    padding: 11px 18px 10px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 600;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {C['text0']};
    border-bottom: 2px solid {C['blue']};
    background-color: rgba(90, 167, 255, 22);
}}
QTabBar::tab:hover {{
    color: {C['text0']};
    background-color: rgba(255,255,255,9);
}}

/* ── 리스트 ── */
QListWidget {{
    background-color: #07090D;
    border: none;
    color: {C['text0']};
    outline: none;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
}}
QListWidget::item {{
    padding: 9px 12px;
    border-bottom: 1px solid #202633;
}}
QListWidget::item:selected {{
    background-color: rgba(90, 167, 255, 34);
    color: {C['text0']};
}}
QListWidget::item:hover {{
    background-color: rgba(255,255,255,9);
}}

/* ── 입력창 ── */
QLineEdit {{
    background-color: #111824;
    border: 1px solid #2A3446;
    border-radius: 6px;
    color: {C['text0']};
    padding: 6px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    selection-background-color: rgba(90,167,255,70);
}}
QLineEdit:focus {{
    border: 1px solid rgba(90,167,255,150);
    background-color: #171e2b;
}}

/* ── 버튼 기본 ── */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #252D3C,stop:0.58 #19202C,stop:1 #111722);
    color: {C['text0']};
    border: 1px solid #334056;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    min-height: 28px;
}}
QPushButton:hover {{
    background: #2D374A;
    border-color: {C['blue']};
}}
QPushButton:pressed {{
    background-color: #0D121A;
    padding-top: 7px;
}}
QPushButton:disabled {{
    color: {C['text3']};
    background-color: #101218;
    border-color: #1c2029;
}}

/* ── 슬라이더 ── */
QSlider::groove:horizontal {{
    background: #202634;
    height: 3px;
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
    border: 1px solid rgba(90,167,255,210);
}}

/* ── 테이블 ── */
QTableWidget {{
    background-color: #07090D;
    border: none;
    color: {C['text0']};
    gridline-color: {C['border']};
    font-family: {APP_FONT_CSS};
    font-size: 12px;
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid #202633;
}}
QTableWidget::item:selected {{
    background-color: rgba(90,167,255,28);
    color: {C['text0']};
}}
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #182031,stop:1 #101620);
    color: {C['text2']};
    border: none;
    border-right: 1px solid #202633;
    border-bottom: 1px solid #202633;
    padding: 6px 10px;
    font-family: {APP_FONT_CSS};
    font-size: 11px;
    font-weight: 600;
}}

/* ── 스크롤바 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(167,173,190,58);
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(90,167,255,120);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(167,173,190,50);
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── 프로그레스바 ── */
QProgressBar {{
    background: #1E2635;
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

APP_DATA_NAME = "MXF QC Player V.1.0"

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

USER_DATA_DIR = _default_user_data_dir()
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
    try:
        if (
            MIGRATION_LOG_PATH.exists()
            and not MIGRATION_LOG_PATH.is_symlink()
            and MIGRATION_LOG_PATH.is_file()
            and _path_size(MIGRATION_LOG_PATH) > MIGRATION_LOG_MAX_BYTES
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
        backups.sort(key=_path_mtime, reverse=True)
        keep_count = max(1, _safe_int_value(MIGRATION_LOG_BACKUP_COUNT, 5))
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
        _record_migration_event(name, source, target, 'skip', '원본과 대상이 같아 건너뜀')
        return
    if not source.exists() or not source.is_file():
        _record_migration_event(name, source, target, 'skip', '기존 파일 없음')
        return
    if target.exists():
        _record_migration_event(name, source, target, 'skip', '새 위치에 파일이 있어 건드리지 않음')
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

_RUNTIME_TOOL_META = {
    'FFmpeg': {
        'command': lambda: FFMPEG,
        'role': '오디오 미터, 블랙/뮤트 검출, 선택 채널 믹스',
        'hint': r'ffmpeg.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'FFprobe': {
        'command': lambda: FFPROBE,
        'role': 'MXF/MP4 메타데이터, 길이, 해상도, 오디오 채널 확인',
        'hint': r'ffprobe.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'FFplay': {
        'command': lambda: FFPLAY,
        'role': '체크된 오디오 채널 실제 출력',
        'hint': r'ffplay.exe를 앱 폴더의 tools\ 안에 넣거나 Windows PATH에 등록하세요.',
    },
    'VLC': {
        'command': lambda: VLC_DIR,
        'role': 'MXF/MP4 원본 영상 재생',
        'hint': r'VLC를 설치하거나 libvlc.dll이 포함된 VLC 폴더를 앱 폴더\VLC 또는 C:\Program Files\VideoLAN\VLC에 두세요.',
    },
}

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

def runtime_package_check():
    """배포본에서 tools/저장 위치가 분리된 상태인지 안내용으로 점검한다."""
    checks = []
    frozen = bool(getattr(sys, 'frozen', False))
    checks.append({
        'name': '실행 형태',
        'ok': True,
        'message': '패키지 EXE' if frozen else '개발 실행',
        'path': str(APP_DIR),
        'hint': '',
    })
    tools_dir = APP_DIR / 'tools'
    checks.append({
        'name': 'tools 폴더',
        'ok': tools_dir.exists() and tools_dir.is_dir(),
        'message': '있음' if tools_dir.exists() else '없음',
        'path': str(tools_dir),
        'hint': r'다른 PC 배포 시 ffmpeg.exe / ffprobe.exe / ffplay.exe를 tools 폴더에 포함하는 것을 권장합니다.',
    })
    for exe_name, resolved in (
        ('ffmpeg.exe', FFMPEG),
        ('ffprobe.exe', FFPROBE),
        ('ffplay.exe', FFPLAY),
    ):
        source = _classify_runtime_source(resolved) if resolved else '찾을 수 없음'
        bundled = source in ('앱 tools 폴더', '내장 tools 폴더')
        checks.append({
            'name': exe_name,
            'ok': bool(resolved and Path(str(resolved)).exists()),
            'message': '패키지 포함' if bundled else source,
            'path': str(resolved or ''),
            'hint': '' if bundled else r'배포 안정성을 높이려면 tools 폴더에 포함하세요. PATH 의존은 PC마다 달라질 수 있습니다.',
        })
    checks.append({
        'name': 'VLC',
        'ok': bool(VLC_DIR and (Path(VLC_DIR) / 'libvlc.dll').exists()),
        'message': _classify_runtime_source(VLC_DIR) if VLC_DIR else '찾을 수 없음',
        'path': str(VLC_DIR or ''),
        'hint': r'다른 PC에는 VLC 설치 또는 libvlc.dll 포함 경로가 필요합니다.',
    })
    separated = _path_key(APP_DIR) != _path_key(USER_DATA_DIR)
    checks.append({
        'name': '사용자 데이터 분리',
        'ok': separated,
        'message': 'EXE 폴더와 사용자 데이터 폴더 분리됨' if separated else 'EXE 폴더와 사용자 데이터 폴더가 같습니다',
        'path': str(USER_DATA_DIR),
        'hint': '배포본은 설정/DB/log/tmp를 LOCALAPPDATA에 저장하는 구성이 안전합니다.',
    })
    return checks

def _runtime_tool_state(name):
    canonical = next((key for key in _RUNTIME_TOOL_META if key.lower() == str(name).lower()), str(name))
    meta = _RUNTIME_TOOL_META.get(canonical)
    if not meta:
        return {
            'name': canonical,
            'ok': False,
            'path': '',
            'role': '',
            'hint': '알 수 없는 실행 도구입니다.',
        }
    if canonical == 'VLC':
        ok = bool(VLC_DIR and (Path(VLC_DIR) / 'libvlc.dll').exists())
        return {
            'name': canonical,
            'ok': ok,
            'path': str(VLC_DIR or ''),
            'role': meta['role'],
            'hint': meta['hint'],
        }
    command = str(meta['command']() or '')
    exe = str(command) if command and Path(command).exists() else shutil.which(command)
    return {
        'name': canonical,
        'ok': bool(exe),
        'path': exe or '',
        'role': meta['role'],
        'hint': meta['hint'],
    }

def missing_runtime_tools(names):
    return [item for item in (_runtime_tool_state(name) for name in names) if not item.get('ok')]

def runtime_tools_ok(names):
    return not missing_runtime_tools(names)

def format_missing_runtime_tools(names):
    missing = missing_runtime_tools(names)
    if not missing:
        return ''
    lines = [f"필수 실행 도구가 없습니다: {', '.join(item['name'] for item in missing)}"]
    lines.append('영향:')
    for item in missing:
        lines.append(f"- {item['name']}: {item.get('role') or '-'}")
    lines.append('조치:')
    for item in missing:
        lines.append(f"- {item.get('hint') or '설치 또는 경로 등록이 필요합니다.'}")
    lines.append('상단 ENV 버튼에서 전체 실행 환경을 다시 확인할 수 있습니다.')
    return '\n'.join(lines)

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

def _safe_float_value(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default

def _safe_int_value(value, default=0):
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return int(parsed)
    except Exception:
        pass
    return default

def _path_mtime(path, default=0.0):
    try:
        return float(Path(path).stat().st_mtime)
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
                deleted_files += int(item.get('files', 0))
                deleted_dirs += int(item.get('dirs', 0))
                shutil.rmtree(target)
            elif target.is_file():
                deleted_files += 1
                target.unlink()
            deleted_entries += 1
        except Exception as e:
            failed.append(f"{path}: {e}")
    after = cache_summary()
    freed = max(0, int(before.get('total_bytes', 0)) - int(after.get('total_bytes', 0)))
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

    return {
        'days': int(keep_days),
        'cutoff': cutoff_text,
        'deleted': deleted,
        'failed': failed,
        'skipped': skipped,
        'deleted_count': len(deleted),
        'freed_bytes': sum(int(item.get('bytes', 0) or 0) for item in deleted),
    }

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
            _safe_proc_log(_logging.WARNING if '_logging' in globals() else 30, message)
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
        for candidate in BACKUP_DIR.glob(f'{prefix}-*'):
            try:
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                backups.append(candidate)
            except Exception:
                continue
        backups.sort(key=_path_mtime, reverse=True)
        keep_count = max(1, _safe_int_value(keep, 10))
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
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        marker = BACKUP_DIR / f'.{prefix}.last'
        last = 0.0
        if marker.exists():
            try:
                last = float(marker.read_text(encoding='utf-8') or '0')
            except Exception:
                last = 0.0
        interval = max(0.0, _safe_float_value(min_interval_sec, 300.0))
        if interval and now - last < interval:
            return None
        stamp = _file_stamp()
        backup = BACKUP_DIR / f'{prefix}-{stamp}{path.suffix}'
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
    if not SETTINGS_PATH.exists():
        return None
    stamp = _file_stamp()
    backup = SETTINGS_PATH.with_name(f'{SETTINGS_PATH.stem}.corrupt-{stamp}{SETTINGS_PATH.suffix}')
    try:
        shutil.copy2(SETTINGS_PATH, backup)
        _settings_log_warning(f'settings.json corrupt; backed up to {backup.name}: {exc}')
        return backup
    except Exception as backup_exc:
        _settings_log_warning(f'settings.json corrupt; backup failed: {backup_exc}')
        return None

def _write_settings_atomic(data):
    tmp_path = SETTINGS_PATH.with_name(
        f'.{SETTINGS_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp'
    )
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open('w', encoding='utf-8') as fh:
            fh.write(payload)
            fh.write('\n')
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except Exception:
                pass
        tmp_path.replace(SETTINGS_PATH)
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
            if SETTINGS_PATH.exists():
                loaded = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
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
            backup_file_snapshot(SETTINGS_PATH, 'settings-auto', min_interval_sec=300, keep=12)
            _write_settings_atomic(_settings_cache)
        except Exception as e:
            _settings_log_warning(f'settings.json save failed: {e}')
        return _settings_data_copy(_settings_cache)

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
        _check_command('FFmpeg', FFMPEG, _RUNTIME_TOOL_META['FFmpeg']['role'], True),
        _check_command('FFprobe', FFPROBE, _RUNTIME_TOOL_META['FFprobe']['role'], True),
        _check_command('FFplay', FFPLAY, _RUNTIME_TOOL_META['FFplay']['role'], True),
    ]
    if VLC_DIR:
        items.append({
            'name': 'VLC',
            'ok': True,
            'path': str(VLC_DIR),
            'message': str(VLC_DIR / 'libvlc.dll'),
            'version': str(VLC_DIR / 'libvlc.dll'),
            'source': _classify_runtime_source(VLC_DIR),
            'role': _RUNTIME_TOOL_META['VLC']['role'],
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
            'role': _RUNTIME_TOOL_META['VLC']['role'],
            'required': True,
            'hint': _RUNTIME_TOOL_META['VLC']['hint'],
        })
    missing = [item['name'] for item in items if not item['ok']]
    missing_required = [item['name'] for item in items if not item['ok'] and item.get('required')]
    storage = check_runtime_storage()
    storage_issues = [item['name'] for item in storage if not item['ok'] and item.get('required', True)]
    storage_warnings = [item['name'] for item in storage if not item['ok'] and not item.get('required', True)]
    problems = missing + storage_issues
    return {
        'ok': not problems,
        'items': items,
        'storage_policy': runtime_storage_policy(),
        'package_check': runtime_package_check(),
        'migration': runtime_migration_events(),
        'migration_log': runtime_migration_log_info(),
        'legacy_data': runtime_legacy_root_data_status(),
        'storage': storage,
        'missing': missing,
        'missing_required': missing_required,
        'storage_issues': storage_issues,
        'storage_warnings': storage_warnings,
        'problems': problems,
        'can_start': 'VLC' not in missing_required,
        'search_paths': _runtime_search_paths(),
        'child_processes': runtime_child_process_status(),
        'heavy_analysis': heavy_analysis_status(),
        'state_timeline': runtime_state_timeline(40),
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
    lines.append('저장 정책')
    lines.append('-' * 42)
    for item in runtime.get('storage_policy', []):
        lines.append(f"[{item.get('name', '')}]")
        lines.append(f"  역할: {item.get('role') or '-'}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  상태: {item.get('status') or '-'}")
        lines.append('')
    lines.append('배포 실행본 점검')
    lines.append('-' * 42)
    for item in runtime.get('package_check', []):
        mark = 'OK' if item.get('ok') else 'CHECK'
        lines.append(f"[{mark}] {item.get('name', '')}")
        lines.append(f"  위치: {item.get('path') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        if item.get('hint'):
            lines.append(f"  참고: {item.get('hint')}")
        lines.append('')
    legacy_groups = runtime.get('legacy_data') or []
    lines.append('레거시 루트 데이터')
    lines.append('-' * 42)
    if legacy_groups:
        lines.append('정책: 앱은 사용자 데이터 폴더만 사용합니다. 아래 항목은 자동 삭제/이동하지 않습니다.')
        lines.append('조치: 필요하면 사용자가 확인 후 백업 위치로 수동 이동하세요.')
        lines.append('')
        for group in legacy_groups:
            lines.append(f"[{group.get('label') or '레거시 위치'}]")
            lines.append(f"  위치: {group.get('root') or '-'}")
            lines.append(f"  정책: {group.get('policy') or '-'}")
            for item in group.get('items', []):
                details = [item.get('kind') or '항목']
                if item.get('size') is not None:
                    details.append(format_bytes(item.get('size')))
                if item.get('children') is not None:
                    details.append(f"항목 {item.get('children')}개")
                if item.get('modified'):
                    details.append(f"수정 {item.get('modified')}")
                if item.get('error'):
                    details.append(f"확인 오류: {item.get('error')}")
                lines.append(f"  - {item.get('name')}: {', '.join(details)}")
                lines.append(f"    {item.get('path')}")
            lines.append('')
    else:
        lines.append('발견된 레거시 루트 데이터 없음')
        lines.append('')
    lines.append('데이터 이전')
    lines.append('-' * 42)
    for item in runtime.get('migration', []):
        lines.append(f"[{item.get('status', '').upper()}] {item.get('name', '')}")
        lines.append(f"  시간: {item.get('timestamp') or '-'}")
        lines.append(f"  원본: {item.get('source') or '-'}")
        lines.append(f"  대상: {item.get('target') or '-'}")
        lines.append(f"  정보: {item.get('message') or '-'}")
        lines.append('')
    migration_log = runtime.get('migration_log') or {}
    lines.append('마이그레이션 로그')
    lines.append('-' * 42)
    lines.append(f"경로: {migration_log.get('path') or '-'}")
    errors = migration_log.get('errors') or []
    if errors:
        lines.append(f"상태: 기록 실패 ({'; '.join(errors)})")
    else:
        lines.append('상태: 기록 가능')
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
    audio = runtime.get('audio_mix') or {}
    lines.append('오디오 자식 프로세스')
    lines.append('-' * 42)
    if audio:
        lines.append(f"예상 상태: {'필요' if audio.get('expected') else '불필요'}")
        lines.append(f"재생 플래그: {audio.get('playing')}")
        lines.append(f"파일: {audio.get('file') or '-'}")
        lines.append(f"채널: {audio.get('channels') or '-'}")
        lines.append(f"재생 속도: {audio.get('rate')}")
        lines.append(f"볼륨: {audio.get('volume_percent')}%")
        lines.append(f"FFmpeg: {audio.get('ffmpeg')}  pid={audio.get('ffmpeg_pid') or '-'}")
        lines.append(f"FFplay: {audio.get('ffplay')}  pid={audio.get('ffplay_pid') or '-'}")
        if audio.get('last_error'):
            lines.append(f"최근 오류: {audio.get('last_error')}")
    else:
        lines.append('오디오 믹스 상태 없음')
    lines.append('')
    children = runtime.get('child_processes') or []
    lines.append('등록된 자식 프로세스')
    lines.append('-' * 42)
    if children:
        for child in children:
            lines.append(
                f"[{child.get('state')}] pid={child.get('pid')} "
                f"{child.get('label') or 'process'}"
            )
            if child.get('command'):
                lines.append(f"  명령: {child.get('command')}")
    else:
        lines.append('등록된 자식 프로세스 없음')
    lines.append('')
    heavy = runtime.get('heavy_analysis') or {}
    lines.append('무거운 분석 슬롯')
    lines.append('-' * 42)
    if heavy.get('running'):
        lines.append(f"진행 중: {heavy.get('owner') or '-'} ({_safe_float_value(heavy.get('elapsed'), 0.0):.1f}s)")
    else:
        lines.append('진행 중인 무거운 분석 없음')
    lines.append('')
    timeline = runtime.get('state_timeline') or runtime_state_timeline(20)
    lines.append('최근 상태 타임라인')
    lines.append('-' * 42)
    if timeline:
        for row in timeline[-20:]:
            extra = [
                f"{k}={v}" for k, v in row.items()
                if k not in ('ts', 'category', 'message') and v not in ('', None)
            ]
            lines.append(
                f"{row.get('ts')} | {row.get('category')} | {row.get('message')}"
                + (f" | {' '.join(extra)}" if extra else '')
            )
    else:
        lines.append('상태 기록 없음')
    lines.append('')
    lines.append('검색 위치')
    lines.append('-' * 42)
    for path in runtime.get('search_paths', []):
        lines.append(f"- {path}")
    lines.append('')
    lines.append('기능 영향')
    lines.append('-' * 42)
    lines.append('- VLC 누락: 원본 영상 재생 불가')
    lines.append('- FFmpeg 누락: 오디오 미터, 블랙/뮤트 검출, 채널 믹스 제한')
    lines.append('- FFprobe 누락: 파일 길이/해상도/채널 정보 확인 제한')
    lines.append('- FFplay 누락: 체크박스 기반 오디오 출력 제한')
    lines.append('- 저장 위치 쓰기 실패: 설정 저장, 로그 기록, 분석 캐시 생성 제한')
    return '\n'.join(lines)

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
        settings = load_settings()
        rows = []
        rows.append(f'SETTINGS_PATH: {SETTINGS_PATH}')
        rows.append('')
        max_rows = max(1, _safe_int_value(limit, 20))
        for i, fp in enumerate((settings.get('recent_files') or [])[:max_rows], start=1):
            p = Path(fp)
            state = 'exists' if p.exists() else 'missing'
            details = []
            try:
                if p.exists():
                    details.append(format_bytes(_path_size(p)))
                    mtime = _path_mtime(p)
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
            candidates.extend(REPORT_DIR.glob(pattern))
        candidates = [p for p in candidates if p.is_file()]
        if not candidates:
            return '관련 샘플 검증 리포트 없음'
        latest = max(candidates, key=_path_mtime)
        latest_mtime = _path_mtime(latest)
        text = latest.read_text(encoding='utf-8', errors='replace')
        modified = datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds") if latest_mtime else '-'
        header = f'LATEST_REPORT: {latest}\nMODIFIED: {modified}\n\n'
        return header + text[-max(1, _safe_int_value(max_chars, 40000)):]
    except Exception as e:
        return f'샘플 검증 리포트 읽기 실패: {e}'

_STATE_TIMELINE = deque(maxlen=240)
_STATE_TIMELINE_LOCK = threading.RLock()

def record_state_event(category, message='', **fields):
    """Keep a tiny in-memory timeline for diagnosing the last moments before a hang."""
    try:
        row = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'category': str(category or 'state'),
            'message': str(message or ''),
        }
        for key, value in fields.items():
            try:
                row[str(key)] = str(value)
            except Exception:
                row[str(key)] = '<unprintable>'
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
    lines.append(f'DB_PATH: {DB_PATH}')
    try:
        if DB_PATH.exists():
            lines.append(f'EXISTS: yes')
            lines.append(f'SIZE  : {format_bytes(_path_size(DB_PATH))}')
        else:
            lines.append('EXISTS: no')
            return '\n'.join(lines)
    except Exception as e:
        lines.append(f'STAT ERROR: {e}')
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
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

def create_diagnostic_report(destination=None, runtime=None, max_log_lines=1500):
    """Create a compact zip report for field troubleshooting."""
    runtime = runtime or check_runtime_environment()
    stamp = _file_stamp()
    if destination:
        out = Path(destination)
        if out.suffix.lower() != '.zip':
            out = out / f'mxf-qc-diagnostic-{stamp}.zip'
    else:
        out = REPORT_DIR / f'mxf-qc-diagnostic-{stamp}.zip'
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'app_name': APP_DATA_NAME,
        'app_dir': str(APP_DIR),
        'resource_dir': str(RESOURCE_DIR),
        'user_data_dir': str(USER_DATA_DIR),
        'report_path': str(out),
    }
    tmp_out = out.with_name(f'.{out.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        with zipfile.ZipFile(tmp_out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr('environment.txt', format_runtime_environment(runtime))
            zf.writestr('runtime.json', json.dumps(runtime, ensure_ascii=False, indent=2, default=str))
            zf.writestr('db_status.txt', _diagnostic_db_status_text())
            zf.writestr('child_processes.json', json.dumps(runtime_child_process_status(), ensure_ascii=False, indent=2))
            zf.writestr('state_timeline.json', json.dumps(runtime_state_timeline(), ensure_ascii=False, indent=2))
            zf.writestr('state_timeline.txt', format_state_timeline())
            zf.writestr('recent_files.txt', _diagnostic_recent_files_text())
            zf.writestr(
                'reports/latest_broadcast_sample_report.txt',
                _latest_report_text(('broadcast-sample*.txt',)),
            )
            zf.writestr('logs/player_tail.log', _recent_log_text(LOG_DIR / 'player.log', max_log_lines))
            zf.writestr('logs/migration_tail.log', _recent_log_text(LOG_DIR / 'migration.log', 500))
            try:
                if SETTINGS_PATH.exists():
                    zf.writestr('settings.json', SETTINGS_PATH.read_text(encoding='utf-8', errors='replace'))
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
    runtime = runtime or check_runtime_environment()
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

# ── 보조 프로세스 추적/정리 ──────────────────────────────
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
            record_state_event(
                'analysis-limit',
                'blocked',
                requested=label,
                owner=_HEAVY_ANALYSIS_OWNER,
                elapsed=f'{time.monotonic() - _HEAVY_ANALYSIS_STARTED:.1f}s',
            )
            return False
        _HEAVY_ANALYSIS_OWNER = str(label or 'analysis')
        _HEAVY_ANALYSIS_STARTED = time.monotonic()
        record_state_event('analysis-limit', 'acquired', owner=_HEAVY_ANALYSIS_OWNER)
        return True

def release_heavy_analysis_slot(label=None):
    global _HEAVY_ANALYSIS_OWNER, _HEAVY_ANALYSIS_STARTED
    with _HEAVY_ANALYSIS_LOCK:
        owner = _HEAVY_ANALYSIS_OWNER
        if not owner:
            return
        if label and owner != label:
            record_state_event(
                'analysis-limit',
                'release skipped',
                requested=label,
                owner=owner,
                elapsed=f'{max(0.0, time.monotonic() - _HEAVY_ANALYSIS_STARTED):.1f}s',
            )
            return
        elapsed = max(0.0, time.monotonic() - _HEAVY_ANALYSIS_STARTED)
        record_state_event('analysis-limit', 'released', owner=owner, elapsed=f'{elapsed:.1f}s')
        _HEAVY_ANALYSIS_OWNER = None
        _HEAVY_ANALYSIS_STARTED = 0.0

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
        record_state_event('child-process', 'start', pid=getattr(proc, 'pid', '-'), label=label)
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
        record_state_event('child-process', 'end', pid=getattr(proc, 'pid', '-'), label=label)
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
                        record_state_event('child-process', 'end', pid=pid, label=label)
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
    before = runtime_child_process_status()
    running_before = _running_child_processes(before)
    if running_before:
        for row in running_before:
            _safe_proc_log(
                _logging.INFO if '_logging' in globals() else 20,
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
                _logging.WARNING if '_logging' in globals() else 30,
                f"child cleanup remaining: pid={row.get('pid')} "
                f"state={row.get('state')} label={row.get('label')} "
                f"cmd={row.get('command') or '-'}"
            )
    else:
        _safe_proc_log(_logging.INFO if '_logging' in globals() else 20, 'child cleanup complete: no registered child processes')
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
            _safe_proc_log(_logging.INFO if '_logging' in globals() else 20,
                           f'orphan audio process cleaned: {line}')
        if proc.returncode != 0:
            detail = (proc.stderr or '').strip()
            if detail:
                _safe_proc_log(_logging.DEBUG if '_logging' in globals() else 10,
                               f'orphan audio cleanup rc={proc.returncode}: {detail[:300]}')
        return len(cleaned)
    except Exception as e:
        _safe_proc_log(_logging.DEBUG if '_logging' in globals() else 10,
                       f'orphan audio cleanup skipped: {e}')
        return 0

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

def _probe_safe_float(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default

def _probe_safe_int(value, default=0):
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return int(parsed)
    except Exception:
        pass
    return default

def _probe_safe_count(value):
    return max(0, _probe_safe_int(value, 0))

def probe(filepath):
    try:
        r = subprocess.run(
            [FFPROBE, "-v","quiet","-print_format","json",
             "-show_format","-show_streams", filepath],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=_hidden_subprocess_flags())
        if r.returncode != 0: return {}
        d   = json.loads(r.stdout or "{}")
        fmt = d.get("format", {})
        info = {
            "filename"    : Path(filepath).name,
            "filepath"    : filepath,
            "duration"    : _probe_safe_float(fmt.get("duration", 0), 0.0),
            "size"        : _probe_safe_count(fmt.get("size", 0)),
            "bit_rate"    : _probe_safe_count(fmt.get("bit_rate", 0)),
            "fps"         : 29.97,
            "width"       : 0, "height": 0,
            "codec"       : "", "channels": 0, "audio_stream_count": 0,
            "timecode"    : "",
            "format_short": Path(filepath).suffix.upper().lstrip(".")
        }
        for s in d.get("streams", []):
            if s.get("codec_type") == "video":
                info["codec"]  = s.get("codec_name", "").upper()
                info["width"]  = _probe_safe_count(s.get("width", 0))
                info["height"] = _probe_safe_count(s.get("height", 0))
                try:
                    n, dv = s.get("r_frame_rate","30/1").split("/")
                    divisor = _probe_safe_int(dv, 1) or 1
                    fps_raw = _probe_safe_int(n, 0) / divisor
                    if fps_raw > 0 and math.isfinite(fps_raw):
                        info["fps"] = round(fps_raw, 3)
                except Exception as e: log.debug(f'fps parse: {e}')
                tc = s.get("tags", {}).get("timecode", "")
                if tc: info["timecode"] = tc
            elif s.get("codec_type") == "audio":
                info["channels"] += _probe_safe_count(s.get("channels", 0))
                info["audio_stream_count"] += 1
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
