"""
transport_controls.py — 트랜스포트 슬라이더 위젯
QCMarkerSlider: QC 결과(블랙/뮤트/프리즈) 오버레이가 그려지는 진행 슬라이더
"""
import math

from PyQt6.QtWidgets import QSlider
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter


class QCMarkerSlider(QSlider):
    """Progress slider with lightweight QC result overlays."""
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._qc_markers = {"black": [], "mute": [], "freeze": []}
        self._qc_duration = 0.0
        self.setMinimumHeight(18)

    @staticmethod
    def _finite_seconds(value, default=None):
        try:
            seconds = float(value)
            if math.isfinite(seconds):
                return max(0.0, seconds)
        except Exception:
            pass
        return default

    @classmethod
    def _clean_ranges(cls, ranges):
        cleaned = []
        for item in ranges or []:
            if not isinstance(item, dict):
                continue
            start = cls._finite_seconds(item.get("start"))
            if start is None:
                continue
            duration = cls._finite_seconds(item.get("duration"))
            end = cls._finite_seconds(item.get("end"))
            if end is None and duration is not None:
                end = start + duration
            if end is None:
                end = start
            if end < start:
                continue
            row = dict(item)
            row["start"] = start
            row["end"] = end
            if duration is None:
                row["duration"] = max(0.0, end - start)
            cleaned.append(row)
        return cleaned

    def set_qc_markers(self, black_ranges=None, mute_ranges=None, freeze_ranges=None, duration_sec=0.0):
        self._qc_markers = {
            "black": self._clean_ranges(black_ranges),
            "mute": self._clean_ranges(mute_ranges),
            "freeze": self._clean_ranges(freeze_ranges),
        }
        self._qc_duration = self._finite_seconds(duration_sec, 0.0) or 0.0
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.orientation() != Qt.Orientation.Horizontal or self._qc_duration <= 0:
            return
        black = self._qc_markers.get("black") or []
        mute = self._qc_markers.get("mute") or []
        freeze = self._qc_markers.get("freeze") or []
        if not black and not mute and not freeze:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        track_left = 7
        track_width = max(1, self.width() - track_left * 2)
        marker_top = max(1, int(self.height() * 0.12))
        marker_h = max(3, int((self.height() - marker_top * 2 - 2) / 3))

        def _draw_ranges(ranges, color, y):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            for r in ranges:
                start = r.get("start", 0.0)
                end = r.get("end", start)
                start = min(start, self._qc_duration)
                end = min(max(end, start + 0.001), self._qc_duration)
                x1 = track_left + int((start / self._qc_duration) * track_width)
                x2 = track_left + int((end / self._qc_duration) * track_width)
                painter.drawRect(x1, y, max(3, x2 - x1), marker_h)

        _draw_ranges(black, QColor(255, 74, 103, 210), marker_top)
        _draw_ranges(mute, QColor(255, 170, 48, 210), marker_top + marker_h + 1)
        _draw_ranges(freeze, QColor(183, 148, 244, 220), marker_top + (marker_h + 1) * 2)
        painter.end()
