"""
file_list_view.py — RightPanel 파일 리스트 표시 계층
FILE_FILTER_*/FileListItemDelegate: right_panel에서 분리된 파일 리스트 필터 상수·HTML 렌더 델리게이트
"""
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QTextDocument, QTextOption

FILE_ITEM_HTML_ROLE = Qt.ItemDataRole.UserRole.value + 10
FILE_ITEM_PLAIN_ROLE = Qt.ItemDataRole.UserRole.value + 11
FILE_FILTER_KEYS = ('all', 'done', 'attention', 'pending', 'issues', 'black', 'mute', 'freeze', 'error', 'normal')
FILE_FILTER_VISIBLE_KEYS = ('all', 'attention', 'issues', 'normal')
FILE_FILTER_LABELS = {
    'all': '전체',
    'done': '완료',
    'attention': '확인',
    'pending': '미분석',
    'issues': '문제',
    'black': '블랙',
    'mute': '무음',
    'freeze': '프리즈',
    'error': '오류',
    'normal': '정상',
}
FILE_FILTER_TIPS = {
    'all': '모든 파일 보기',
    'done': '일괄 검수 기준인 블랙/무음 검사가 완료된 파일만 보기',
    'attention': '미분석, 발견, 오류, 파일 접근 문제, 메타 확인 등 확인이 필요한 파일만 보기',
    'pending': '블랙/무음 검사가 아직 완료되지 않은 파일만 보기',
    'issues': '블랙/무음/프리즈 발견, 검사 오류, 파일 접근 문제만 보기',
    'black': '블랙 구간이 발견된 파일만 보기',
    'mute': '무음 구간이 발견된 파일만 보기',
    'freeze': '정지 화면 구간이 발견된 파일만 보기',
    'error': '검사 오류가 있는 파일만 보기',
    'normal': '확인 필요가 없는 정상 또는 블랙/무음 정상 파일만 보기',
}


class FileListItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        html = index.data(FILE_ITEM_HTML_ROLE)
        if not html:
            super().paint(painter, option, index)
            return

        style = opt.widget.style() if opt.widget else None
        opt.text = ""
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        doc = QTextDocument()
        doc.setDocumentMargin(0)
        text_option = doc.defaultTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(text_option)
        doc.setDefaultFont(opt.font)
        doc.setHtml(html)
        doc.setTextWidth(max(40, opt.rect.width() - 28))

        painter.save()
        painter.translate(opt.rect.left() + 14, opt.rect.top() + 8)
        doc.drawContents(painter)
        painter.restore()
