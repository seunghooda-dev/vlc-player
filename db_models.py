"""
db_models.py — SQLAlchemy ORM 모델, DB 초기화, 유틸 함수
"""
import sys, json, subprocess, hashlib
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Boolean, text
from sqlalchemy.orm import declarative_base, Session

from constants import BASE_DIR, DB_PATH, FFMPEG, FFPROBE, log

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
                print(f'[DB WARNING] integrity_check: {result[0]}')
                backup = DB_PATH.with_suffix('.db.bak')
                import shutil; shutil.copy2(DB_PATH, backup)
                print(f'[DB] 백업 저장: {backup}')
    except Exception as e:
        print(f'[DB] 무결성 검사 실패: {e}')
_check_db_integrity()

# ── 유틸 ──────────────────────────────────────────────────
def is_df_fps(fps):
    # DF 프레임레이트: 29.97, 59.94, 23.976 등 소수점 fps
    return abs(fps - round(fps)) > 0.01

def sec_to_tc(sec, fps=29.97, df=None):
    # SMPTE 12M 타임코드 — DF/NDF 자동 판별
    # HD(29.97) = DF, UHD(59.94) = DF, 정수fps = NDF
    if sec is None or sec < 0: sec = 0.0
    if df is None: df = is_df_fps(fps)
    nom = round(fps)  # 명목 FPS: 29.97->30, 59.94->60
    if df and nom in (30, 60):
        # Drop Frame 보정 (SMPTE 12M)
        # 29.97DF: 매분 2프레임 드롭, 10분 단위 제외
        # 59.94DF: 매분 4프레임 드롭, 10분 단위 제외
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
