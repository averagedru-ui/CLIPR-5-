"""Shared pan/zoom image viewport.

Content lives in a normalized [0,1]x[0,1] space with a known aspect ratio; the
widget maps that to pixels with a fit transform plus user pan/zoom. Subclasses
draw overlays and handle interaction in normalized space via
``widget_to_norm`` / ``norm_to_widget``.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from vcomp.ui import theme


class ImageViewport(QWidget):
    def __init__(self, content_aspect: float = 16 / 9) -> None:
        super().__init__()
        self.setMinimumSize(240, 160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._pixmap: QPixmap | None = None
        self._aspect = content_aspect
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._panning = False
        self._space = False
        self._last_mouse = QPoint()

    # ------------------------------------------------------------- content
    def set_content_array(self, arr: np.ndarray) -> None:
        h, w = arr.shape[:2]
        buf = np.ascontiguousarray(arr)
        fmt = QImage.Format.Format_RGBA8888 if arr.shape[2] == 4 else QImage.Format.Format_RGB888
        stride = arr.shape[2] * w
        self._pixmap = QPixmap.fromImage(QImage(buf.data, w, h, stride, fmt).copy())
        self._aspect = w / h
        self.update()

    def clear_content(self) -> None:
        self._pixmap = None
        self.update()

    # -------------------------------------------------------- coord mapping
    def _fit_rect(self) -> QRectF:
        cw, ch = self.width(), self.height()
        if cw / ch > self._aspect:
            h = ch * self._zoom
            w = h * self._aspect
        else:
            w = cw * self._zoom
            h = w / self._aspect
        x = (cw - w) / 2 + self._pan.x()
        y = (ch - h) / 2 + self._pan.y()
        return QRectF(x, y, w, h)

    def norm_to_widget(self, nx: float, ny: float) -> QPointF:
        r = self._fit_rect()
        return QPointF(r.x() + nx * r.width(), r.y() + ny * r.height())

    def widget_to_norm(self, p: QPointF) -> QPointF:
        r = self._fit_rect()
        return QPointF((p.x() - r.x()) / r.width() if r.width() else 0.0,
                       (p.y() - r.y()) / r.height() if r.height() else 0.0)

    def norm_len_x(self, dx_px: float) -> float:
        r = self._fit_rect()
        return dx_px / r.width() if r.width() else 0.0

    def norm_len_y(self, dy_px: float) -> float:
        r = self._fit_rect()
        return dy_px / r.height() if r.height() else 0.0

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0d0d10"))
        if self._pixmap is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(self._fit_rect(), self._pixmap, QRectF(self._pixmap.rect()))
        else:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text())
        self.paint_overlay(p)

    def empty_text(self) -> str:
        return "No content"

    def paint_overlay(self, painter: QPainter) -> None:
        """Override."""

    # ------------------------------------------------------------- interact
    def wheelEvent(self, e) -> None:  # noqa: N802
        c = e.position()
        before = self.widget_to_norm(c)
        self._zoom = max(0.2, min(self._zoom * (1.0015 ** e.angleDelta().y()), 12.0))
        after = self.norm_to_widget(before.x(), before.y())
        self._pan += QPointF(c.x() - after.x(), c.y() - after.y())
        self.update()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space:
            self._space = True
        elif e.key() == Qt.Key.Key_F:
            self._zoom = 1.0
            self._pan = QPointF(0, 0)
            self.update()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space:
            self._space = False
        else:
            super().keyReleaseEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.MiddleButton or (
            e.button() == Qt.MouseButton.LeftButton and self._space
        ):
            self._panning = True
            self._last_mouse = e.position().toPoint()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._panning:
            d = e.position().toPoint() - self._last_mouse
            self._pan += QPointF(d.x(), d.y())
            self._last_mouse = e.position().toPoint()
            self.update()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
        else:
            super().mouseReleaseEvent(e)
