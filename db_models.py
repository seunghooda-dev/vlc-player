"""
db_models.py — SQLAlchemy ORM 모델, DB 초기화, 유틸 함수
"""
import sys, json, subprocess, hashlib
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Boolean, text
from sqlalchemy.orm import declarative_base, Session

from constants import BASE_DIR, DB_PATH, FFMPEG, FFPROBE, log, backup_file_snapshot

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
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
    bit_rate     = Column(Integer)
    channels     = Column(Integer)
    timecode     = Column(String)
    memo         = Column(Text, default="")
    tag_in       = Column(String)
    tag_out      = Column(String)
    stt_done     = Column(Boolean, default=False)
    scene_done   = Column(Boolean, default=False)
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
def is_df_fps(fps):
    # DF 프레임레이트: 29.97, 59.94, 23.976 등 소수점 fps
    return abs(fps - round(fps)) > 0.01

def _nominal_fps(fps):
    try:
        return max(1, int(round(float(fps or 29.97))))
    except Exception:
        return 30

def _is_drop_frame_tc(fps, df=None):
    nom = _nominal_fps(fps)
    if df is None:
        df = nom in (30, 60) and is_df_fps(float(fps or 29.97))
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
    total_f = max(0, int(round(frame or 0))) + max(0, int(offset_frames or 0))
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
    if sec is None or sec < 0:
        sec = 0.0
    try:
        frame = round(float(sec) * float(fps or 29.97))
    except Exception:
        frame = 0
    return frames_to_tc(frame, fps, df, offset_frames)

def sec_fmt(s):
    return f"{int(s//60):02d}:{int(s%60):02d}"

def probe(filepath):
    try:
        r = subprocess.run(
            [FFPROBE,"-v","quiet","-print_format","json","-show_format","-show_streams",filepath],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0: return {}
        d = json.loads(r.stdout); fmt = d.get("format",{})
        info = {"filename":Path(filepath).name,"filepath":filepath,
                "duration":float(fmt.get("duration",0)),"size":int(fmt.get("size",0)),
                "bit_rate":int(fmt.get("bit_rate",0) or 0),
                "fps":29.97,"width":0,"height":0,"codec":"","channels":0,
                "audio_stream_count":0,
                "timecode":"","format_short":Path(filepath).suffix.upper().lstrip(".")}
        for s in d.get("streams",[]):
            if s.get("codec_type")=="video":
                info["codec"]=s.get("codec_name","").upper()
                info["width"]=s.get("width",0); info["height"]=s.get("height",0)
                try:
                    n,dv=s.get("r_frame_rate","30/1").split("/")
                    fps_raw = int(n)/int(dv)
                    info["fps"]=round(fps_raw, 3)
                except Exception as e: log.debug(f'fps parse: {e}')
                tc=s.get("tags",{}).get("timecode","")
                if tc: info["timecode"]=tc
            elif s.get("codec_type")=="audio":
                info["channels"] += int(s.get("channels",0) or 0)
                info["audio_stream_count"] += 1
        if not info["timecode"]: info["timecode"]=fmt.get("tags",{}).get("timecode","")
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
        return info
    except Exception as e:
        log.warning(f'probe failed: {e}')
        return {}

def save_clip(info):
    cid = hashlib.md5(info["filepath"].encode()).hexdigest()
    with Session(engine) as s:
        if s.get(Clip, cid):
            return cid
        s.add(Clip(
            id=cid, filename=info["filename"], filepath=info["filepath"],
            format_short=info.get("format_short",""), codec=info.get("codec",""),
            width=info.get("width",0), height=info.get("height",0),
            fps=info.get("fps",29.97), duration=info.get("duration",0),
            file_size=info.get("size",0), bit_rate=info.get("bit_rate",0),
            channels=info.get("channels",0), timecode=info.get("timecode",""),
        ))
        s.commit()
    return cid

# ── 백그라운드 스레드들 ────────────────────────────────────
