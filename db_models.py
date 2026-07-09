"""
db_models.py — SQLAlchemy ORM 모델, DB 초기화, 유틸 함수
"""
import sys, json, subprocess, hashlib, threading, math
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Boolean, text, event
from sqlalchemy.orm import declarative_base, Session

from constants import BASE_DIR, DB_PATH, FFMPEG, FFPROBE, log, backup_file_snapshot, _hidden_subprocess_flags

SQLITE_BUSY_TIMEOUT_MS = 30000

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={
        "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000,
        "check_same_thread": False,
    },
    pool_pre_ping=True,
)

@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        journal_mode = cursor.fetchone()
        cursor.execute("PRAGMA synchronous=NORMAL")
        log.debug(
            "[DB] sqlite pragmas applied "
            f"busy_timeout={SQLITE_BUSY_TIMEOUT_MS}ms "
            f"journal_mode={journal_mode[0] if journal_mode else 'unknown'}"
        )
    except Exception as e:
        log.warning(f"[DB] sqlite pragma setup failed: {e}")
    finally:
        cursor.close()

Base   = declarative_base()

class Clip(Base):
    __tablename__ = "clips"
    id           = Column(String, primary_key=True)
    filename     = Column(String)
    filepath     = Column(String, unique=True)
    format_short = Column(String)
    codec        = Column(String)
    width        = Column(Integer)
    height       = Column(Integer)
    fps          = Column(Float)
    duration     = Column(Float)
    file_size    = Column(Integer)
    file_mtime_ns = Column(Integer)
    bit_rate     = Column(Integer)
    channels     = Column(Integer)
    audio_stream_count = Column(Integer)
    timecode     = Column(String)
    memo         = Column(Text, default="")
    tag_in       = Column(String)
    tag_out      = Column(String)
    stt_done     = Column(Boolean, default=False)
    scene_done   = Column(Boolean, default=False)
    qc_black_status = Column(String, default="")
    qc_mute_status  = Column(String, default="")
    qc_freeze_status = Column(String, default="")
    qc_black_count  = Column(Integer, default=0)
    qc_mute_count   = Column(Integer, default=0)
    qc_freeze_count = Column(Integer, default=0)
    qc_black_ranges = Column(Text, default="")
    qc_mute_ranges  = Column(Text, default="")
    qc_freeze_ranges = Column(Text, default="")
    qc_summary      = Column(String, default="")
    qc_updated_at   = Column(DateTime)
    created_at   = Column(DateTime, default=datetime.now)
    updated_at   = Column(DateTime, default=datetime.now)

class Transcript(Base):
    __tablename__ = "transcripts"
    id        = Column(String, primary_key=True)
    clip_id   = Column(String)
    text      = Column(Text)
    tc_in     = Column(String)
    tc_out    = Column(String)
    start_sec = Column(Float)
    end_sec   = Column(Float)

class Scene(Base):
    __tablename__ = "scenes"
    id          = Column(String, primary_key=True)
    clip_id     = Column(String)
    scene_index = Column(Integer)
    tc_in       = Column(String)
    start_sec   = Column(Float)

Base.metadata.create_all(engine)

def _ensure_clip_qc_columns():
    """Add lightweight QC summary columns for existing SQLite databases."""
    columns = {
        "qc_black_status": "VARCHAR",
        "qc_mute_status": "VARCHAR",
        "qc_freeze_status": "VARCHAR",
        "qc_black_count": "INTEGER DEFAULT 0",
        "qc_mute_count": "INTEGER DEFAULT 0",
        "qc_freeze_count": "INTEGER DEFAULT 0",
        "qc_black_ranges": "TEXT",
        "qc_mute_ranges": "TEXT",
        "qc_freeze_ranges": "TEXT",
        "qc_summary": "VARCHAR",
        "qc_updated_at": "DATETIME",
        "audio_stream_count": "INTEGER DEFAULT 0",
        "file_mtime_ns": "INTEGER DEFAULT 0",
    }
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(clips)")).fetchall()
            existing = {row[1] for row in rows}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE clips ADD COLUMN {name} {ddl}"))
                    log.info(f"[DB] clips column added: {name}")
    except Exception as e:
        log.warning(f"[DB] QC column migration failed: {e}")

_ensure_clip_qc_columns()

_PROBE_CACHE = {}
_PROBE_CACHE_ORDER = []
_PROBE_CACHE_LOCK = threading.RLock()
_PROBE_CACHE_LIMIT = 32

# DB 무결성 검사
def _check_db_integrity():
    try:
        from sqlalchemy import text as _text
        with engine.connect() as conn:
            result = conn.execute(_text('PRAGMA integrity_check')).fetchone()
            if result and result[0] != 'ok':
                log.warning(f'[DB WARNING] integrity_check: {result[0]}')
                backup = backup_file_snapshot(DB_PATH, 'archive-corrupt', min_interval_sec=0, keep=5)
                log.warning(f'[DB] 손상 의심 백업 저장: {backup}')
            else:
                backup = backup_file_snapshot(DB_PATH, 'archive-auto', min_interval_sec=3600, keep=12)
                if backup:
                    log.info(f'[DB] 자동 백업 저장: {backup.name}')
    except Exception as e:
        log.warning(f'[DB] 무결성 검사 실패: {e}')
_check_db_integrity()

# ── 유틸 ──────────────────────────────────────────────────
def _safe_float(value, default=0.0):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default

def _safe_int(value, default=0):
    try:
        parsed = float(value)
        if math.isfinite(parsed):
            return int(parsed)
    except Exception:
        pass
    return default

def _safe_count(value):
    return max(0, _safe_int(value, 0))

def _safe_text(value, default=""):
    text = str(value or "").strip()
    return text if text else default

def _safe_media_file_path(filepath):
    try:
        text = str(filepath or "").strip()
        if not text:
            return None
        path = Path(text)
        if path.exists() and path.is_file():
            return path
    except Exception:
        pass
    return None

def _safe_file_snapshot(filepath):
    try:
        path = Path(str(filepath or "").strip())
        if not path.is_file():
            return {"size": 0, "mtime_ns": 0}
        stat = path.stat()
        return {
            "size": _safe_count(getattr(stat, "st_size", 0)),
            "mtime_ns": _safe_count(getattr(stat, "st_mtime_ns", 0)),
        }
    except Exception:
        return {"size": 0, "mtime_ns": 0}

def _safe_resolved_path_text(filepath):
    try:
        return str(Path(filepath).resolve())
    except Exception:
        return str(Path(filepath or ""))

def is_df_fps(fps):
    # DF 프레임레이트: 29.97, 59.94, 23.976 등 소수점 fps
    fps = _safe_float(fps, 29.97)
    return abs(fps - round(fps)) > 0.01

def _nominal_fps(fps):
    return max(1, int(round(_safe_float(fps, 29.97))))

def _is_drop_frame_tc(fps, df=None):
    nom = _nominal_fps(fps)
    if df is None:
        df = nom in (30, 60) and is_df_fps(fps)
    return bool(df) and nom in (30, 60)

def _drop_frames_per_minute(fps, df=None):
    if not _is_drop_frame_tc(fps, df):
        return 0
    return 2 if _nominal_fps(fps) == 30 else 4

def tc_to_frames(tc, fps=29.97, df=None):
    """Convert a source timecode label to real frame count."""
    if not tc:
        return 0
    try:
        parts = str(tc).replace(';', ':').split(':')
        if len(parts) != 4:
            return 0
        h, m, s, f = [int(x) for x in parts]
        nom = _nominal_fps(fps)
        total_f = ((h * 3600 + m * 60 + s) * nom) + f
        drop = _drop_frames_per_minute(fps, df)
        if drop:
            total_minutes = h * 60 + m
            total_f -= drop * (total_minutes - total_minutes // 10)
        return max(0, total_f)
    except Exception as e:
        log.debug(f'tc_to_frames: {e}')
        return 0

def frames_to_tc(frame, fps=29.97, df=None, offset_frames=0):
    """Convert a real frame count to display TC, including optional source TC offset."""
    nom = _nominal_fps(fps)
    total_f = max(0, int(round(_safe_float(frame, 0.0)))) + max(0, int(round(_safe_float(offset_frames, 0.0))))
    drop = _drop_frames_per_minute(fps, df)
    if drop:
        frames_per_10min = nom * 60 * 10 - drop * 9
        frames_per_min = nom * 60 - drop
        ten_min_blocks = total_f // frames_per_10min
        remainder = total_f % frames_per_10min
        dropped_minutes = max(0, (remainder - drop) // frames_per_min)
        total_f += drop * (9 * ten_min_blocks + dropped_minutes)
    ff = total_f % nom
    ss = (total_f // nom) % 60
    mm = (total_f // nom // 60) % 60
    hh =  total_f // nom // 3600
    sep = ';' if drop else ':'
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"

def sec_to_tc(sec, fps=29.97, df=None, offset_frames=0):
    # Player display timecode. DF uses SMPTE drop-frame numbering for 29.97/59.94.
    sec = max(0.0, _safe_float(sec, 0.0))
    fps = _safe_float(fps, 29.97)
    frame = round(sec * fps)
    return frames_to_tc(frame, fps, df, offset_frames)

def sec_fmt(s):
    s = max(0.0, _safe_float(s, 0.0))
    return f"{int(s//60):02d}:{int(s%60):02d}"

def _probe_cache_key(filepath):
    snapshot = _safe_file_snapshot(filepath)
    if not snapshot["size"] and not snapshot["mtime_ns"]:
        return ''
    return f'{_safe_resolved_path_text(filepath)}|{snapshot["size"]}|{snapshot["mtime_ns"]}'

def _probe_cache_get(key):
    if not key:
        return None
    with _PROBE_CACHE_LOCK:
        cached = _PROBE_CACHE.get(key)
        if cached is None:
            return None
        try:
            _PROBE_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        _PROBE_CACHE_ORDER.append(key)
        return dict(cached)

def _probe_cache_set(key, info):
    if not key or not info:
        return
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE[key] = dict(info)
        try:
            _PROBE_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        _PROBE_CACHE_ORDER.append(key)
        while len(_PROBE_CACHE_ORDER) > _PROBE_CACHE_LIMIT:
            old = _PROBE_CACHE_ORDER.pop(0)
            _PROBE_CACHE.pop(old, None)

def probe(filepath):
    try:
        path = _safe_media_file_path(filepath)
        if path is None:
            log.debug(f'probe skipped invalid media path: {filepath}')
            return {}
        filepath = str(path)
        cache_key = _probe_cache_key(filepath)
        cached = _probe_cache_get(cache_key)
        if cached is not None:
            log.debug(f'probe cache hit: {Path(filepath).name}')
            return cached
        probe_entries = (
            "format=duration,size,bit_rate:format_tags=timecode:"
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,channels:"
            "stream_tags=timecode"
        )
        r = subprocess.run(
            [
                FFPROBE,
                "-v", "quiet",
                "-print_format", "json",
                "-show_entries", probe_entries,
                "-show_format",
                "-show_streams",
                filepath,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=_hidden_subprocess_flags())
        if r.returncode != 0: return {}
        d = json.loads(r.stdout or "{}")
        if not isinstance(d, dict):
            return {}
        fmt = d.get("format",{})
        if not isinstance(fmt, dict):
            fmt = {}
        file_snapshot = _safe_file_snapshot(filepath)
        mtime_ns = file_snapshot["mtime_ns"]
        info = {"filename":Path(filepath).name,"filepath":filepath,
                "duration":_safe_float(fmt.get("duration",0), 0.0),"size":_safe_count(fmt.get("size",0)),
                "mtime_ns":mtime_ns,
                "bit_rate":_safe_count(fmt.get("bit_rate",0)),
                "fps":29.97,"width":0,"height":0,"codec":"","channels":0,
                "audio_stream_count":0,
                "timecode":"","format_short":Path(filepath).suffix.upper().lstrip(".")}
        streams = d.get("streams", [])
        if not isinstance(streams, list):
            streams = []
        for s in streams:
            if not isinstance(s, dict):
                continue
            if s.get("codec_type")=="video":
                info["codec"]=_safe_text(s.get("codec_name","")).upper()
                info["width"]=_safe_count(s.get("width",0)); info["height"]=_safe_count(s.get("height",0))
                try:
                    n,dv=s.get("r_frame_rate","30/1").split("/")
                    fps_raw = _safe_int(n, 0)/_safe_int(dv, 1)
                    if math.isfinite(fps_raw) and fps_raw > 0:
                        info["fps"]=round(fps_raw, 3)
                except Exception as e: log.debug(f'fps parse: {e}')
                tags = s.get("tags", {})
                if not isinstance(tags, dict):
                    tags = {}
                tc=_safe_text(tags.get("timecode",""))
                if tc: info["timecode"]=tc
            elif s.get("codec_type")=="audio":
                info["channels"] += _safe_count(s.get("channels",0))
                info["audio_stream_count"] += 1
        fmt_tags = fmt.get("tags", {})
        if not isinstance(fmt_tags, dict):
            fmt_tags = {}
        if not info["timecode"]: info["timecode"]=_safe_text(fmt_tags.get("timecode",""))
        # DF/NDF 자동 판별
        fps = info["fps"]
        info["df"] = is_df_fps(fps)
        # 해상도별 기본 FPS 보정 (4K UHD=59.94, HD=29.97)
        if info["width"] >= 3840 and abs(fps - 60) < 1:
            info["fps"] = 59.94; info["df"] = True
        elif info["width"] >= 1920 and abs(fps - 30) < 1:
            info["fps"] = 29.97; info["df"] = True
        # 임베디드 타임코드 → 시작 오프셋(초) 계산
        info["tc_offset"] = 0.0
        if info["timecode"]:
            try:
                tc = info["timecode"]
                sep = ';' if ';' in tc else ':'
                parts = tc.replace(';',':').split(':')
                if len(parts) == 4:
                    h,m,s,f = int(parts[0]),int(parts[1]),int(parts[2]),int(parts[3])
                    nom = round(info["fps"])
                    info["tc_offset"] = h*3600 + m*60 + s + f/nom
            except Exception as e: log.debug(f'tc_offset parse: {e}')
        ext=Path(filepath).suffix.upper().lstrip(".")
        info["format_short"]="XDCAM" if ext=="MXF" else ext
        _probe_cache_set(cache_key, info)
        return info
    except Exception as e:
        log.warning(f'probe failed: {e}')
        return {}

def _clip_id_for_path(filepath):
    return hashlib.md5(str(filepath or "").encode()).hexdigest()

def _normalize_qc_status(value):
    value = str(value or "").strip().lower()
    return value if value in ("ok", "found", "error") else ""

def qc_summary_from_status(black_status="", mute_status="", freeze_status=""):
    black_status = _normalize_qc_status(black_status)
    mute_status = _normalize_qc_status(mute_status)
    freeze_status = _normalize_qc_status(freeze_status)
    if "error" in (black_status, mute_status, freeze_status):
        return "검사 오류"
    found = []
    if black_status == "found":
        found.append("블랙")
    if mute_status == "found":
        found.append("무음")
    if freeze_status == "found":
        found.append("프리즈")
    if found:
        return "/".join(found) + " 있음"
    if black_status == "ok" and mute_status == "ok":
        return "정상"
    return "미분석"

def _sanitize_qc_ranges(ranges, limit=2000):
    cleaned = []
    if ranges is None:
        return cleaned
    max_items = max(0, _safe_int(limit, 2000))
    if max_items <= 0:
        return cleaned
    if isinstance(ranges, dict):
        items = (ranges,)
    elif isinstance(ranges, (str, bytes)):
        return cleaned
    else:
        try:
            items = iter(ranges)
        except TypeError:
            return cleaned
    for item in items:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in ("start", "end", "duration"):
            if key in item and item.get(key) is not None:
                value = _safe_float(item.get(key), None)
                if value is not None:
                    row[key] = round(max(0.0, value), 3)
        for key in ("frames",):
            if key in item and item.get(key) is not None:
                row[key] = max(0, _safe_int(item.get(key), 0))
        for key in ("tc_start", "tc_end"):
            value = str(item.get(key) or "").strip()
            if value:
                row[key] = value[:32]
        if "start" not in row:
            continue
        if "start" in row and "end" in row and row["end"] < row["start"]:
            continue
        if row:
            cleaned.append(row)
        if len(cleaned) >= max_items:
            break
    return cleaned

def sanitize_qc_ranges(ranges, limit=2000):
    return _sanitize_qc_ranges(ranges, limit=limit)

def _encode_qc_ranges(ranges):
    try:
        return json.dumps(_sanitize_qc_ranges(ranges), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "[]"

def _decode_qc_ranges(value):
    try:
        if value is None:
            return []
        if isinstance(value, (list, tuple, dict)):
            return _sanitize_qc_ranges(value)
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        text_value = str(value or "").strip()
        if not text_value:
            return []
        decoded = json.loads(text_value)
        if not isinstance(decoded, (list, tuple, dict)):
            return []
        return _sanitize_qc_ranges(decoded)
    except Exception:
        return []

def load_qc_status(filepath):
    if not filepath:
        return {}
    cid = _clip_id_for_path(filepath)
    with Session(engine) as s:
        clip = s.get(Clip, cid)
        if not clip:
            return {}
        black = _normalize_qc_status(getattr(clip, "qc_black_status", ""))
        mute = _normalize_qc_status(getattr(clip, "qc_mute_status", ""))
        freeze = _normalize_qc_status(getattr(clip, "qc_freeze_status", ""))
        return {
            "black": black,
            "mute": mute,
            "freeze": freeze,
            "black_count": _safe_count(getattr(clip, "qc_black_count", 0)),
            "mute_count": _safe_count(getattr(clip, "qc_mute_count", 0)),
            "freeze_count": _safe_count(getattr(clip, "qc_freeze_count", 0)),
            "black_ranges": _decode_qc_ranges(getattr(clip, "qc_black_ranges", "")),
            "mute_ranges": _decode_qc_ranges(getattr(clip, "qc_mute_ranges", "")),
            "freeze_ranges": _decode_qc_ranges(getattr(clip, "qc_freeze_ranges", "")),
            "summary": getattr(clip, "qc_summary", "") or qc_summary_from_status(black, mute, freeze),
            "updated_at": getattr(clip, "qc_updated_at", None),
        }

def load_clip_metadata_hint(filepath):
    if not filepath:
        return {}
    p = _safe_media_file_path(filepath)
    if p is None:
        return {}
    filepath = str(p)
    snapshot = _safe_file_snapshot(filepath)
    current_size = snapshot["size"]
    current_mtime_ns = snapshot["mtime_ns"]
    cid = _clip_id_for_path(filepath)
    try:
        with Session(engine) as s:
            clip = s.get(Clip, cid)
            if not clip:
                return {}
            stored_size = _safe_count(getattr(clip, "file_size", 0))
            if stored_size and current_size and stored_size != current_size:
                log.debug(f"metadata hint ignored size mismatch: {p.name}")
                return {}
            stored_mtime_ns = _safe_count(getattr(clip, "file_mtime_ns", 0))
            if stored_mtime_ns and current_mtime_ns and stored_mtime_ns != current_mtime_ns:
                log.debug(f"metadata hint ignored modified-time mismatch: {p.name}")
                return {}
            duration = _safe_float(getattr(clip, "duration", 0), 0.0)
            width = _safe_count(getattr(clip, "width", 0))
            height = _safe_count(getattr(clip, "height", 0))
            if duration <= 0 and not width and not height:
                return {}
            fps = _safe_float(getattr(clip, "fps", 0), 29.97)
            ext = p.suffix.upper().lstrip(".")
            return {
                "filename": _safe_text(getattr(clip, "filename", ""), p.name),
                "filepath": str(filepath),
                "duration": duration,
                "size": stored_size or current_size,
                "mtime_ns": stored_mtime_ns or current_mtime_ns,
                "bit_rate": _safe_count(getattr(clip, "bit_rate", 0)),
                "fps": fps,
                "width": width,
                "height": height,
                "codec": _safe_text(getattr(clip, "codec", "")),
                "channels": _safe_count(getattr(clip, "channels", 0)),
                "audio_stream_count": _safe_count(getattr(clip, "audio_stream_count", 0)),
                "timecode": _safe_text(getattr(clip, "timecode", "")),
                "format_short": _safe_text(getattr(clip, "format_short", ""), "XDCAM" if ext == "MXF" else ext),
                "df": is_df_fps(fps),
                "tc_offset": 0.0,
                "metadata_hint": True,
            }
    except Exception as e:
        log.debug(f"metadata hint load failed: {p.name if filepath else '?'} | {e}")
        return {}

def update_clip_qc(
    filepath,
    black=None,
    mute=None,
    freeze=None,
    black_count=None,
    mute_count=None,
    freeze_count=None,
    black_ranges=None,
    mute_ranges=None,
    freeze_ranges=None,
):
    if not filepath:
        return {}
    cid = _clip_id_for_path(filepath)
    now = datetime.now()
    with Session(engine) as s:
        clip = s.get(Clip, cid)
        if not clip:
            p = Path(filepath)
            clip = Clip(id=cid, filename=p.name, filepath=str(filepath), created_at=now)
            s.add(clip)
        if black is not None:
            clip.qc_black_status = _normalize_qc_status(black)
        if mute is not None:
            clip.qc_mute_status = _normalize_qc_status(mute)
        if freeze is not None:
            clip.qc_freeze_status = _normalize_qc_status(freeze)
        if black_count is not None:
            clip.qc_black_count = _safe_count(black_count)
        if mute_count is not None:
            clip.qc_mute_count = _safe_count(mute_count)
        if freeze_count is not None:
            clip.qc_freeze_count = _safe_count(freeze_count)
        if black_ranges is not None:
            clip.qc_black_ranges = _encode_qc_ranges(black_ranges)
        if mute_ranges is not None:
            clip.qc_mute_ranges = _encode_qc_ranges(mute_ranges)
        if freeze_ranges is not None:
            clip.qc_freeze_ranges = _encode_qc_ranges(freeze_ranges)
        clip.qc_summary = qc_summary_from_status(clip.qc_black_status, clip.qc_mute_status, clip.qc_freeze_status)
        clip.qc_updated_at = now
        clip.updated_at = now
        s.commit()
        return {
            "black": clip.qc_black_status,
            "mute": clip.qc_mute_status,
            "freeze": clip.qc_freeze_status,
            "black_count": _safe_count(clip.qc_black_count),
            "mute_count": _safe_count(clip.qc_mute_count),
            "freeze_count": _safe_count(clip.qc_freeze_count),
            "black_ranges": _decode_qc_ranges(getattr(clip, "qc_black_ranges", "")),
            "mute_ranges": _decode_qc_ranges(getattr(clip, "qc_mute_ranges", "")),
            "freeze_ranges": _decode_qc_ranges(getattr(clip, "qc_freeze_ranges", "")),
            "summary": clip.qc_summary,
            "updated_at": clip.qc_updated_at,
        }

def save_clip(info):
    if not isinstance(info, dict):
        return ""
    filepath = _safe_text(info.get("filepath", ""))
    if not filepath:
        return ""
    cid = _clip_id_for_path(filepath)
    now = datetime.now()
    snapshot = _safe_file_snapshot(filepath)
    mtime_ns = snapshot["mtime_ns"] or _safe_count(info.get("mtime_ns", 0))
    with Session(engine) as s:
        clip = s.get(Clip, cid)
        if not clip:
            clip = Clip(id=cid, created_at=now)
            s.add(clip)
        clip.filename = _safe_text(info.get("filename", ""), Path(filepath).name)
        clip.filepath = filepath
        clip.format_short = _safe_text(info.get("format_short",""))
        clip.codec = _safe_text(info.get("codec",""))
        clip.width = _safe_count(info.get("width",0))
        clip.height = _safe_count(info.get("height",0))
        clip.fps = _safe_float(info.get("fps",29.97), 29.97)
        clip.duration = max(0.0, _safe_float(info.get("duration",0), 0.0))
        clip.file_size = _safe_count(info.get("size",0))
        clip.file_mtime_ns = mtime_ns
        clip.bit_rate = _safe_count(info.get("bit_rate",0))
        clip.channels = _safe_count(info.get("channels",0))
        clip.audio_stream_count = _safe_count(info.get("audio_stream_count",0))
        clip.timecode = _safe_text(info.get("timecode",""))
        clip.updated_at = now
        s.commit()
    return cid

# ── 백그라운드 스레드들 ────────────────────────────────────
