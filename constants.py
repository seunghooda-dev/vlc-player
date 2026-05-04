"""
constants.py — 색상, 스타일, 경로, 로거
모든 모듈이 import하는 공통 상수
"""
"""
Archive Tagger - PyQt6 완전판
파일 탐색 + 비디오 플레이어 + DB + STT + 씬감지 + 검색
"""

import sys, os, json, subprocess, hashlib, csv, shutil, threading, atexit
from pathlib import Path
from datetime import datetime

# ── 색상 ──────────────────────────────────────────────────
C = {
    # 배경 계층
    'bg'     :'#111114',   # 최상위 배경
    'panel'  :'#18181c',   # 패널
    'panel2' :'#0d0d10',   # 서브패널
    'border' :'#252528',   # 구분선
    'input'  :'#1e1e22',   # 입력창
    # 강조색 — 단일 포인트 컬러 + 용도별
    'blue'   :'#4A9EFF',   # 주 강조 (선택, 포커스)
    'yellow' :'#F5C542',   # 타임코드, CUE
    'green'  :'#3DD68C',   # 재생, 완료
    'orange' :'#FF8C42',   # FPS, 경고
    'teal'   :'#2DD4BF',   # SAFE, 채널
    'red'    :'#FF5252',   # 에러
    'purple' :'#A78BFA',   # STT
    # 텍스트 계층
    'text0'  :'#E8E8EC',   # 주 텍스트
    'text1'  :'#8888A0',   # 보조 텍스트
    'text2'  :'#55556A',   # 설명 텍스트
    'text3'  :'#33333F',   # 비활성
}

STYLE = f"""
/* ── 툴팁: 연노란색 반투명 ── */
QToolTip {{
    background-color: #1e1e2e;
    color: #e0e0e0;
    border: 1px solid #4a4a6a;
    padding: 6px 12px;
    font-family: '맑은 고딕';
    font-size: 12px;
    border-radius: 5px;
}}

/* ── 기본 ── */
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['text0']};
    font-family: '맑은 고딕';
    font-size: 13px;
}}
QSplitter::handle {{
    background-color: #1a1a1a;
    width: 1px;
}}

/* ── 상태바 ── */
QStatusBar {{
    background-color: #141414;
    color: {C['text2']};
    font-family: Consolas;
    font-size: 11px;
    border-top: 1px solid #1a1a1a;
    padding: 3px 12px;
    letter-spacing: 0.5px;
}}

/* ── 탭 ── */
QTabWidget::pane {{
    border: none;
    background-color: {C['panel2']};
    border-top: 1px solid #1a1a1a;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {C['text2']};
    padding: 9px 20px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.3px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {C['text0']};
    border-bottom: 2px solid {C['blue']};
    background-color: rgba(74, 158, 255, 12);
}}
QTabBar::tab:hover {{
    color: {C['text1']};
    background-color: rgba(255,255,255,6);
}}

/* ── 리스트 ── */
QListWidget {{
    background-color: #1c1c1c;
    border: none;
    color: {C['text0']};
    outline: none;
    font-family: '맑은 고딕';
    font-size: 12px;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid #242424;
}}
QListWidget::item:selected {{
    background-color: rgba(60, 60, 60, 80);
}}
QListWidget::item:hover {{
    background-color: rgba(255,255,255,5);
}}

/* ── 입력창 ── */
QLineEdit {{
    background-color: #1c1c1c;
    border: 1px solid #2e2e2e;
    border-radius: 4px;
    color: {C['text0']};
    padding: 6px 10px;
    font-family: '맑은 고딕';
    font-size: 12px;
    selection-background-color: rgba(74,158,255,60);
}}
QLineEdit:focus {{
    border: 1px solid rgba(74,158,255,120);
    background-color: #202020;
}}

/* ── 버튼 기본 ── */
QPushButton {{
    background-color: #383838;
    color: {C['text0']};
    border: 1px solid #282828;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: #424242;
    border-color: #3a3a3a;
}}
QPushButton:pressed {{
    background-color: #2e2e2e;
    padding-top: 7px;
}}
QPushButton:disabled {{
    color: #3a3a3a;
    background-color: #242424;
    border-color: #222;
}}

/* ── 슬라이더 ── */
QSlider::groove:horizontal {{
    background: #1e1e1e;
    height: 4px;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 #00e5ff);
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #e0e0e0;
    border: none;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{
    background: white;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -6px 0;
}}

/* ── 테이블 ── */
QTableWidget {{
    background-color: #1c1c1c;
    border: none;
    color: {C['text0']};
    gridline-color: #242424;
    font-family: '맑은 고딕';
    font-size: 12px;
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid #242424;
}}
QTableWidget::item:selected {{
    background-color: rgba(74,158,255,25);
    color: {C['text0']};
}}
QHeaderView::section {{
    background-color: #1a1a1a;
    color: {C['text2']};
    border: none;
    border-right: 1px solid #242424;
    border-bottom: 1px solid #242424;
    padding: 6px 10px;
    font-family: '맑은 고딕';
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

/* ── 스크롤바 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,18);
    border-radius: 2px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255,255,255,35);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,18);
    border-radius: 2px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── 프로그레스바 ── */
QProgressBar {{
    background: #1e1e1e;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: {C['text1']};
    font-size: 10px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,x2:1,stop:0 {C['blue']},stop:1 #00e5ff);
    border-radius: 2px;
}}
"""

FFMPEG     = "ffmpeg"
FFPROBE    = "ffprobe"
FFPLAY     = "ffplay"
VIDEO_EXTS = {'.mxf','.mp4','.mov','.mts','.m2ts','.mkv','.avi'}
BASE_DIR   = Path(__file__).parent
DB_PATH    = BASE_DIR / "archive.db"
SETTINGS_PATH = BASE_DIR / "settings.json"
LOG_DIR    = BASE_DIR / "logs"
TMP_DIR    = BASE_DIR / "tmp"
LOG_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS = {
    'volume': 80,
    'playback_rate': 1.0,
    'audio_channels': [1, 2],
    'black_amount': '98',
    'black_threshold': '32',
    'mute_threshold': '-50',
    'mute_duration': '1.0',
    'last_dir': 'C:/',
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

def _check_command(name, command):
    exe = shutil.which(command)
    if not exe:
        return {
            'name': name,
            'ok': False,
            'path': '',
            'message': f'{command} 실행 파일을 PATH에서 찾을 수 없습니다.',
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
        }
    except Exception as e:
        return {
            'name': name,
            'ok': False,
            'path': exe,
            'message': str(e),
        }

def check_runtime_environment():
    items = [
        _check_command('FFmpeg', FFMPEG),
        _check_command('FFprobe', FFPROBE),
        _check_command('FFplay', FFPLAY),
    ]
    if VLC_DIR:
        items.append({
            'name': 'VLC',
            'ok': True,
            'path': str(VLC_DIR),
            'message': str(VLC_DIR / 'libvlc.dll'),
        })
    else:
        items.append({
            'name': 'VLC',
            'ok': False,
            'path': '',
            'message': r'C:\Program Files\VideoLAN\VLC\libvlc.dll 을 찾을 수 없습니다.',
        })
    missing = [item['name'] for item in items if not item['ok']]
    return {
        'ok': not missing,
        'items': items,
        'missing': missing,
    }

# ── 보조 프로세스 추적/정리 ──────────────────────────────
_CHILD_PROCS = {}
_CHILD_PROC_LOCK = threading.RLock()

def _safe_proc_log(level, message):
    try:
        globals().get('log').log(level, message)
    except Exception:
        pass

def register_child_process(proc, label='process'):
    if not proc:
        return proc
    try:
        with _CHILD_PROC_LOCK:
            _CHILD_PROCS[int(proc.pid)] = (proc, label)
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
    # 날짜별 로그 파일 (30일 보관)
    fh = _TRFHandler(
        LOG_DIR / 'player.log',
        when='midnight', interval=1, backupCount=30,
        encoding='utf-8'
    )
    fh.setLevel(_logging.DEBUG)
    fmt = _logging.Formatter(
        '[%(asctime)s] %(levelname)-5s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh.setFormatter(fmt)
    # 콘솔 출력 (WARNING 이상만)
    ch = _logging.StreamHandler()
    ch.setLevel(_logging.WARNING)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
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

def mk_label(text, color=None, family="맑은 고딕", size=10, bold=False):
    from PyQt6.QtWidgets import QLabel
    l = QLabel(text)
    w = "bold" if bold else "normal"
    l.setStyleSheet(
        f"color:{color or C['text0']};font-family:{family};"
        f"font-size:{size}px;font-weight:{w};background:transparent;")
    return l

def separator(vertical=True):
    from PyQt6.QtWidgets import QFrame
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};")
    return f
