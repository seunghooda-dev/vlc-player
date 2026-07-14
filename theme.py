"""theme.py — UI 색상/스타일/글꼴 (constants 에서 분리)

C(색상 팔레트), STYLE(Qt 스타일시트), 글꼴 상수를 모은 순수 레이어.
외부 모듈을 전혀 import 하지 않아 어느 모듈이든 안전하게 가져다 쓴다.
constants.py 는 하위 호환을 위해 이 심볼들을 그대로 재노출한다.
"""
__all__ = ['APP_FONT_QT', 'MONO_FONT_QT', 'APP_FONT_CSS', 'MONO_FONT_CSS',
           'css_font', 'C', 'STYLE']

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
