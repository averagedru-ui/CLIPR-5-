"""16:9 source viewport.

M1: aspect-fit display of the current decoded frame with a letterboxed dark
background and a small HUD line (resolution / frame). Mask overlay handles,
zoom, pan and drag-to-create arrive in M4.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from vcomp.ui import theme


class SourceViewport(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 180)
        self.setAutoFillBackground(True)
        self._pixmap: QPixmap | None = None
        self._overlay_text = ""

    def set_frame(self, arr: np.ndarray) -> None:
        h, w, _ = arr.shape
        # QImage needs a buffer that outlives the object -> keep a copy.
        buf = np.ascontiguousarray(arr)
        img = QImage(buf.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(img)
        self._overlay_text = f"{w}x{h}"
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def _fit_rect(self) -> QRect:
        if self._pixmap is None:
            return QRect()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        scale = min(self.width() / pw, self.height() / ph)
        w, h = int(pw * scale), int(ph * scale)
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101014"))
        if self._pixmap is None:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No clip loaded\nFile > Open  (Ctrl+O)")
            return
        target = self._fit_rect()
        p.drawPixmap(target, self._pixmap)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(target.adjusted(6, 4, -6, -4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                   self._overlay_text)
