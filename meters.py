"""
meters.py — 오디오 미터 위젯 및 레벨 측정 스레드
SideMeter, SafeAreaItem, LoudnessMeter, AudioLevelThread, MeterController
유틸 위젯: mk_btn, mk_label, separator
"""
import sys, re, subprocess
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFrame,
    QHBoxLayout, QVBoxLayout,
    QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsRectItem, QGraphicsLineItem,
)
from PyQt6.QtCore  import Qt, QTimer, QThread, pyqtSignal, QObject, QRectF
from PyQt6.QtGui   import QColor, QPainter, QPen, QBrush, QFont, QLinearGradient
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem

from constants import (
    C, FFMPEG, FFPROBE, log,
    register_child_process, unregister_child_process, terminate_child_process,
)

def mk_btn(text, w=None, h=26, color=None, bg=None):
    b = QPushButton(text)
    if w: b.setFixedWidth(w)
    b.setFixedHeight(h)
    st = ""
    if color or bg:
        bc = bg or "qlineargradient(y1:0,y2:1,stop:0 #606060,stop:1 #3c3c3c)"
        st = f"QPushButton{{background:{bc};color:{color or C['text0']};border:1px solid #1e1e1e;border-radius:2px;font-size:18px;font-weight:bold;padding:0 8px;}}"
        st += f"QPushButton:hover{{background:{bc};opacity:0.8;}}"
    if st: b.setStyleSheet(st)
    return b

def mk_label(text, color=None, family="맑은 고딕", size=10, bold=False):
    l = QLabel(text)
    c = color or C['text0']
    w = "bold" if bold else "normal"
    l.setStyleSheet(f"color:{c};font-family:{family};font-size:{size}px;font-weight:{w};background:transparent;")
    return l

def separator(vertical=True):
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C['border']};")
    return f

# ══════════════════════════════════════════════════════════
# 사이드 채널 미터 (방송 모니터 스타일)
# ══════════════════════════════════════════════════════════
class SideMeter(QWidget):
    """방송 모니터 스타일 — 사진처럼 얇은 가로 바 16행
    채널번호 박스(오렌지) + 세그먼트 레벨바
    """
    def __init__(self, left=True, channel_numbers=None, parent=None):
        super().__init__(parent)
        self.left    = left
        if channel_numbers is None:
            channel_numbers = [1,3,5,7] if left else [2,4,6,8]
        self.channel_numbers = list(channel_numbers)
        self._levels = [0.0] * len(self.channel_numbers)
        self._peaks  = [0.0] * len(self.channel_numbers)
        self.setFixedWidth(140)
        self.setFixedHeight(104)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent;")

    def set_levels(self, levels, peaks):
        count = len(self.channel_numbers)
        self._levels = list(levels[:count])
        self._peaks  = list(peaks[:count])
        self.update()

    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter, QColor, QFont
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        W = self.width(); H = self.height()

        n       = len(self.channel_numbers)
        LBL_W   = 22
        GAP     = 1
        ROW     = max(4, (H - GAP * (n - 1)) // n)
        SEG_W   = 3
        SEG_GAP = 1
        BAR_W   = W - LBL_W - 2
        seg_n   = max(1, BAR_W // (SEG_W + SEG_GAP))

        for i in range(n):
            ch_num  = self.channel_numbers[i]
            y       = i * (ROW + GAP)
            lv      = self._levels[i] if i < len(self._levels) else 0.0
            pk      = self._peaks[i]  if i < len(self._peaks)  else 0.0
            is_clip = lv > 0.92

            if self.left:
                # 왼쪽 미터: [CH번호 | 바→→→]  번호 왼쪽 가장자리
                LBL_X = 0
                BAR_X = LBL_W + 2
                # 바: 번호에서 오른쪽으로 채워짐
                def get_sx(si): return BAR_X + si * (SEG_W + SEG_GAP)
                def get_ratio(si): return si / max(1, seg_n - 1)
                def get_pk_x(pk_v): return BAR_X + int(BAR_W * pk_v)
            else:
                # 오른쪽 미터: [←←← 바 | CH번호]  번호 오른쪽 가장자리
                LBL_X = W - LBL_W
                BAR_X = 0
                # 바: 오른쪽(번호쪽)에서 왼쪽으로 채워짐
                def get_sx(si): return BAR_X + (seg_n - 1 - si) * (SEG_W + SEG_GAP)
                def get_ratio(si): return si / max(1, seg_n - 1)
                def get_pk_x(pk_v): return BAR_X + int(BAR_W * (1.0 - pk_v))

            # ── 채널 번호 박스 ──
            box_col = QColor(200, 30, 0, 210) if is_clip else QColor(180, 80, 0, 200)
            p.fillRect(LBL_X, y, LBL_W, ROW, box_col)
            if ROW >= 7:
                p.setPen(QColor('#ffffff'))
                p.setFont(QFont('Consolas', max(5, min(8, ROW - 2)), QFont.Weight.Bold))
                p.drawText(LBL_X, y, LBL_W, ROW,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    str(ch_num))

            # 바 배경 없음

            # ── 세그먼트 레벨 바 ──
            filled = int(seg_n * lv)
            for si in range(seg_n):
                sx    = get_sx(si)
                ratio = get_ratio(si)
                if ratio > 0.90:
                    on_col = QColor(255, 20, 0, 220);  off_col = QColor(0, 0, 0, 0)
                elif ratio > 0.75:
                    on_col = QColor(255, 200, 0, 220); off_col = QColor(0, 0, 0, 0)
                elif ratio > 0.45:
                    on_col = QColor(100, 255, 0, 220); off_col = QColor(0, 0, 0, 0)
                else:
                    on_col = QColor(0, 230, 60, 220);  off_col = QColor(0, 0, 0, 0)
                p.fillRect(sx, y, SEG_W, ROW, on_col if si < filled else off_col)

            # ── 피크 마커 ──
            if pk > 0.01:
                px2    = get_pk_x(pk)
                pk_col = QColor(255, 50, 0, 255) if pk > 0.90 else QColor(255, 230, 0, 255)
                p.fillRect(min(max(px2, BAR_X), BAR_X + BAR_W - 2), y, 2, ROW, pk_col)

        p.end()

# ══════════════════════════════════════════════════════════
# 라우드니스 미터
# ══════════════════════════════════════════════════════════
class SafeAreaItem:
    """QGraphicsScene에 Safe Area 가이드라인 아이템 추가/제거"""
    ACTION_RATIO = 0.90   # Action Safe 90%
    TITLE_RATIO  = 0.80   # Title Safe 80%

    def __init__(self, scene):
        self._scene  = scene
        self._items  = []
        self._visible = False

    def set_visible(self, v, W, H):
        self._visible = v
        self._redraw(W, H)

    def toggle(self, W, H):
        self._visible = not self._visible
        self._redraw(W, H)
        return self._visible

    def resize(self, W, H):
        if self._visible:
            self._redraw(W, H)

    def _redraw(self, W, H):
        from PyQt6.QtGui import QPen, QColor, QFont
        from PyQt6.QtCore import QRectF
        # 기존 아이템 제거
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

        if not self._visible:
            return

        Qt_ = __import__('PyQt6.QtCore', fromlist=['Qt']).Qt
        for ratio, alpha, label in [
            (self.ACTION_RATIO, 120, "ACTION 90%"),
            (self.TITLE_RATIO,  80,  "TITLE 80%"),
        ]:
            mx = W * (1 - ratio) / 2
            my = H * (1 - ratio) / 2
            rw = W * ratio
            rh = H * ratio
            color = QColor(200, 200, 200, alpha)
            pen = QPen(color, 1.0)
            pen.setStyle(Qt_.PenStyle.SolidLine)
            rect = self._scene.addRect(QRectF(mx, my, rw, rh), pen)
            rect.setZValue(20)
            self._items.append(rect)
            # 작은 라벨
            txt = self._scene.addText(label)
            txt.setDefaultTextColor(QColor(200, 200, 200, alpha))
            txt.setFont(QFont("Consolas", 7))
            txt.setZValue(21)
            txt.setPos(mx + 3, my + 1)
            self._items.append(txt)

        # 센터 크로스헤어 (가는 회색선)
        pen_c = QPen(QColor(180, 180, 180, 50), 1)
        cx = W / 2; cy = H / 2
        h_line = self._scene.addLine(0, cy, W, cy, pen_c)
        v_line = self._scene.addLine(cx, 0, cx, H, pen_c)
        h_line.setZValue(20); v_line.setZValue(20)
        self._items += [h_line, v_line]


# ══════════════════════════════════════════════════════════
class LoudnessMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(60)
        self.setFixedHeight(220)
        self._lkfs_m=-99.0; self._lkfs_i=-99.0; self._true_peak=-99.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent;")
    def update_lkfs(self, m, i, tp=-99.0):
        self._lkfs_m=m; self._lkfs_i=i; self._true_peak=tp; self.update()
    def reset(self):
        self._lkfs_m=-99.0; self._lkfs_i=-99.0; self._true_peak=-99.0; self.update()
    def paintEvent(self, e):
        from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QFont
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W=self.width(); H=self.height()
        # 반투명 배경
        p.fillRect(0,0,W,H,QColor(0,0,0,140))
        LMIN=-60.0; LMAX=0.0; LBL_H=18; BOT_H=38
        BAR_Y=LBL_H; BAR_H=H-LBL_H-BOT_H; BAR_X=6; BAR_W=W-12
        def ly(val):
            r=(val-LMIN)/(LMAX-LMIN); r=max(0.0,min(1.0,r))
            return int(BAR_Y+BAR_H*(1.0-r))
        # 존 배경
        p.fillRect(BAR_X,BAR_Y,BAR_W,BAR_H,QColor(20,20,20,180))
        for top,bot,col in [(0,-18,QColor(80,10,10,120)),(-18,-24,QColor(70,45,0,120)),
                            (-24,-40,QColor(0,60,20,120)),(-40,-60,QColor(0,30,15,100))]:
            ty=ly(top); by=ly(bot); p.fillRect(BAR_X,ty,BAR_W,by-ty,col)
        # 레벨 바
        if self._lkfs_m > -70.0:
            my=ly(max(self._lkfs_m, LMIN)); fh=BAR_Y+BAR_H-my
            if fh>0:
                g=QLinearGradient(BAR_X,BAR_Y,BAR_X,BAR_Y+BAR_H)
                g.setColorAt(0.0,QColor(255,17,17,220)); g.setColorAt(0.25,QColor(255,153,0,220))
                g.setColorAt(0.55,QColor(170,255,0,220)); g.setColorAt(1.0,QColor(0,204,68,220))
                p.setBrush(g); p.setPen(Qt.PenStyle.NoPen); p.drawRect(BAR_X,my,BAR_W,fh)
        for db in [-6,-18,-24,-36,-48]:
            gy=ly(db); is_ref=(db==-24)
            p.setPen(QColor('#FFD700') if is_ref else QColor('#2a2a2a'))
            p.drawLine(BAR_X-2,gy,BAR_X+BAR_W+2,gy)
            if db in [-6,-18,-24,-36]:
                p.setFont(QFont('Consolas',6,QFont.Weight.Bold if is_ref else QFont.Weight.Normal))
                p.setPen(QColor('#FFD700') if is_ref else QColor('#383838'))
                p.drawText(0,gy-6,W,12,Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignVCenter,str(db))
        # True Peak 수평선
        if self._true_peak > -99.0:
            tp_y = ly(min(self._true_peak, 0.0))
            tp_col = QColor(255,0,0,200) if self._true_peak > -1.0 else QColor(255,140,0,180)
            p.setPen(tp_col)
            from PyQt6.QtCore import Qt as _Qt
            p.drawLine(BAR_X-3, tp_y, BAR_X+BAR_W+3, tp_y)
            # TP 수치
            p.setFont(QFont('Consolas',6,QFont.Weight.Bold))
            p.drawText(0, tp_y-8, W, 8, _Qt.AlignmentFlag.AlignHCenter, f'TP{self._true_peak:.1f}')
        p.setFont(QFont('Consolas',7,QFont.Weight.Bold)); p.setPen(QColor('#444'))
        p.drawText(0,0,W,LBL_H,Qt.AlignmentFlag.AlignHCenter|Qt.AlignmentFlag.AlignVCenter,'LKFS')
        m_str=f'{self._lkfs_m:.1f}' if self._lkfs_m>LMIN else '---'
        i_str=f'{self._lkfs_i:.1f}' if self._lkfs_i>LMIN else '---'
        m_col=QColor('#ff4444') if self._lkfs_m>-18 else QColor('#ffcc00') if self._lkfs_m>-24 else QColor('#00e676')
        p.setFont(QFont('Consolas',7)); p.setPen(QColor('#555')); p.drawText(0,H-BOT_H,W,14,Qt.AlignmentFlag.AlignHCenter,'M')
        p.setPen(m_col); p.setFont(QFont('Consolas',9,QFont.Weight.Bold))
        p.drawText(0,H-BOT_H+12,W,16,Qt.AlignmentFlag.AlignHCenter,m_str)
        p.setFont(QFont('Consolas',7)); p.setPen(QColor('#888'))
        p.drawText(0,H-12,W,12,Qt.AlignmentFlag.AlignHCenter,f'I:{i_str}')
        p.end()

# ══════════════════════════════════════════════════════════
# FFmpeg 실시간 오디오 레벨 측정 스레드 (BS.1770 준수)
# ══════════════════════════════════════════════════════════
class AudioLevelThread(QThread):
    levels_ready = pyqtSignal(list, list, float, float, float)

    def __init__(self):
        super().__init__()
        self._filepath = None
        self._position = 0.0
        self._ch_count = 2
        self._audio_stream_count = 0
        self._running  = False
        self._lock     = __import__('threading').Lock()
        self._proc     = None   # 현재 실행중인 FFmpeg 프로세스
        self._lkfs_ch  = (1, 2)  # LKFS 측정 채널쌍
        self._i_hist   = []
        self._i_lufs   = -99.0

    def start_file(self, filepath, ch_count, lkfs_ch=(1,2), audio_stream_count=0):
        # 기존 프로세스 kill 후 새 파일로 재시작
        self._kill_proc()
        with self._lock:
            self._filepath = filepath
            self._ch_count = max(1, min(16, ch_count))
            self._audio_stream_count = max(0, int(audio_stream_count or 0))
            self._lkfs_ch  = lkfs_ch
            self._running  = True
            self._i_hist   = []
            self._i_lufs   = -99.0
        if not self.isRunning():
            self.start()

    def update_position(self, pos_sec):
        with self._lock:
            self._position = pos_sec

    def stop_meter(self):
        self._running  = False
        self._filepath = None   # 루프에서 fp 체크로 즉시 정지
        self._kill_proc()
        self._i_hist   = []
        self._i_lufs   = -99.0

    def _kill_proc(self):
        with self._lock:
            p = self._proc
            self._proc = None
        if p and p.poll() is None:
            terminate_child_process(p, 'audio meter ffmpeg')

    def run(self):
        import re
        peaks = [0.0] * 16
        hold  = [0]   * 16

        while self._running:
            with self._lock:
                fp       = self._filepath
                pos      = self._position
                nch      = self._ch_count
                nstreams = self._audio_stream_count
                lkfs_ch  = self._lkfs_ch

            if not fp or not self._running:
                self.msleep(100); continue

            try:
                # ebur128 Momentary는 400ms 슬라이딩 윈도우 워밍업 필요
                # → 측정 위치보다 0.4초 앞에서 시작, 0.8초 분석 → 마지막 M값이 정확한 Momentary
                ss = f'{max(0.0, pos - 0.45):.3f}'

                # ── filter_complex로 RMS/LKFS 분리 측정 ──
                # [rms]  : 전체 채널 astats → 채널별 RMS
                # [lufs] : 선택 채널쌍만 pan 추출 → ebur128 → Momentary LKFS
                c1 = min(lkfs_ch[0]-1, nch-1)  # 0-based
                c2 = min(lkfs_ch[1]-1, nch-1)

                rms_metas = ','.join(
                    f'ametadata=print:key=lavfi.astats.{i+1}.RMS_level'
                    for i in range(nch)
                )
                # RMS 브랜치: 전체 채널 그대로
                rms_branch = f'astats=metadata=1:reset=1,{rms_metas}'
                # LKFS 브랜치: 선택 채널쌍만 추출 → ebur128
                lufs_branch = (f'pan=stereo|c0=c{c1}|c1=c{c2}'
                               f',ebur128=metadata=1:peak=true'
                               f',ametadata=print:key=lavfi.r128.M'
                               f',ametadata=print:key=lavfi.r128.true_peak')

                if nstreams > 1:
                    inputs = ''.join(f'[0:a:{i}]' for i in range(min(nstreams, nch)))
                    setup = f'{inputs}amerge=inputs={min(nstreams, nch)}[merged];'
                    source = '[merged]'
                else:
                    setup = ''
                    source = '[0:a]'
                fc = f'{setup}{source}asplit=2[a1][a2];[a1]{rms_branch}[rms];[a2]{lufs_branch}[lufs]'

                cmd = [FFMPEG,'-y','-ss',ss,'-i',fp,
                       '-t','0.8','-vn',
                       '-filter_complex',fc,
                       '-map','[rms]','-map','[lufs]',
                       '-f','null','-']

                proc = register_child_process(subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=0x08000000
                ), 'audio meter ffmpeg')
                with self._lock:
                    self._proc = proc

                try:
                    _, raw = proc.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    terminate_child_process(proc, 'audio meter ffmpeg')
                    continue
                finally:
                    unregister_child_process(proc)
                    with self._lock:
                        if self._proc is proc:
                            self._proc = None

                if not self._running: break
                out = raw.decode('utf-8', errors='replace')

                # ── 채널별 RMS 파싱 ──
                rms_levels = [0.0] * 16
                ch_vals = {}
                for m in re.finditer(r'lavfi\.astats\.(\d+)\.RMS_level=([-\d.]+)', out):
                    ci = int(m.group(1)) - 1
                    try:
                        val = float(m.group(2))
                        if 0 <= ci < 16:
                            if ci not in ch_vals or val > ch_vals[ci]:
                                ch_vals[ci] = val
                    except Exception as e: log.debug(f'meter ch_vals: {e}')
                for ci, db in ch_vals.items():
                    rms_levels[ci] = max(0.0, min(1.0, (db + 60.0) / 60.0))

                # ── LKFS Momentary: 마지막 M값 (정규식 분리로 혼용 방지) ──
                lkfs_m = -99.0
                true_peak_db = -99.0
                # M과 true_peak 정규식 완전 분리 — 혼용 버그 방지
                for m in re.finditer(r'lavfi\.r128\.M=([-\d.]+)', out):
                    try: lkfs_m = float(m.group(1))  # 마지막값으로 덮어쓰기
                    except Exception as e: log.debug(f'lkfs_m parse: {e}')
                for m in re.finditer(r'lavfi\.r128\.true_peak=([-\d.]+)', out):
                    try:
                        val = float(m.group(1))
                        if val > true_peak_db: true_peak_db = val
                    except Exception as e: log.debug(f'true_peak parse: {e}')

                # ── Integrated LUFS (BS.1770 게이팅) ──
                if lkfs_m > -70.0:
                    self._i_hist.append(lkfs_m)
                    if len(self._i_hist) > 150:
                        self._i_hist.pop(0)
                if self._i_hist:
                    gated = [v for v in self._i_hist if v > -70.0]
                    if gated:
                        avg = sum(gated) / len(gated)
                        rel = [v for v in gated if v > avg - 10.0]
                        self._i_lufs = sum(rel) / len(rel) if rel else avg
                lkfs_i = self._i_lufs

                # ── 피크 홀드 (2초 = 25틱 × 80ms) ──
                for i in range(16):
                    if rms_levels[i] >= peaks[i]:
                        peaks[i] = rms_levels[i]; hold[i] = 25
                    elif hold[i] > 0:
                        hold[i] -= 1
                    else:
                        peaks[i] = max(0.0, peaks[i] - 0.015)

                if self._running:
                    self.levels_ready.emit(
                        list(rms_levels), list(peaks),
                        lkfs_m, lkfs_i, true_peak_db
                    )

            except Exception as _e:
                print('[AudioLevel ERROR]', _e)

            self.msleep(80)

# ══════════════════════════════════════════════════════════
# 미터 컨트롤러
# ══════════════════════════════════════════════════════════
class MeterController(QObject):
    def __init__(self, lm, rm, loud):
        super().__init__()
        self.lm   = lm
        self.rm   = rm
        self.loud = loud
        self._thread = AudioLevelThread()
        self._thread.levels_ready.connect(self._on_levels)
        self._pos_timer = QTimer()
        self._pos_timer.setInterval(80)

    def start_file(self, filepath, ch_count, player, lkfs_ch=(1,2), audio_stream_count=0):
        self._pos_timer.stop()
        self._thread.stop_meter()
        self._thread.start_file(filepath, ch_count, (1, 2), audio_stream_count)
        try: self._pos_timer.timeout.disconnect()
        except: pass  # 연결 없으면 정상
        self._pos_timer.timeout.connect(
            lambda: self._thread.update_position(player.position() / 1000.0))
        self._pos_timer.start()

    def set_playing(self, playing):
        if not playing:
            self._pos_timer.stop()
            self._thread.stop_meter()    # _running=False + FFmpeg kill
            self._thread._kill_proc()    # 진행 중인 프로세스 즉시 kill
            self.lm.set_levels([0]*8, [0]*8)
            self.rm.set_levels([0]*8, [0]*8)
            self.loud.reset()

    def set_channel_filter(self, selected_pairs):
        self._ch_filter = selected_pairs

    def _on_levels(self, levels, peaks, lkfs_m, lkfs_i, true_peak):
        # 오디오 미터는 항상 원본의 전체 채널 레벨을 보여준다.
        # 선택 채널은 출력 라우팅/LKFS 기준으로만 사용하고,
        # 미터 표시 자체는 숨기지 않는다.
        src_levels = list(levels[:8]) + [0.0] * max(0, 8 - len(levels[:8]))
        src_peaks  = list(peaks[:8]) + [0.0] * max(0, 8 - len(peaks[:8]))
        odd_lv = [src_levels[i] for i in range(0,8,2)]
        odd_pk = [src_peaks[i]  for i in range(0,8,2)]
        evn_lv = [src_levels[i] for i in range(1,8,2)]
        evn_pk = [src_peaks[i]  for i in range(1,8,2)]
        self.lm.set_levels(odd_lv, odd_pk)
        self.rm.set_levels(evn_lv, evn_pk)
        self.loud.update_lkfs(lkfs_m, lkfs_i, true_peak)

# ══════════════════════════════════════════════════════════
# 왼쪽: 비디오 패널
# ══════════════════════════════════════════════════════════
