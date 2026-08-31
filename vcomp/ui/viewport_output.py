"""9:16 output viewport.

M2: displays the composited RGBA canvas from the render worker (aspect-fit,
checkerboard behind any transparency). Placement handles + safe-area guides
come in M4/M8.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from vcomp.ui import theme


class OutputViewport(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(180, 320)
        self._pixmap: QPixmap | None = None

    def set_frame(self, arr: np.ndarray) -> None:
        h, w = arr.shape[:2]
        buf = np.ascontiguousarray(arr)
        if arr.shape[2] == 4:
            img = QImage(buf.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
        else:
            img = QImage(buf.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(img)
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self.update()

    def _fit_rect(self) -> QRect:
        pw, ph = self._pixmap.width(), self._pixmap.height()
        scale = min(self.width() / pw, self.height() / ph)
        w, h = int(pw * scale), int(ph * scale)
        return QRect((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0d0d10"))
        if self._pixmap is None:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Output\n(load a clip)")
            return
        p.drawPixmap(self._fit_rect(), self._pixmap)
