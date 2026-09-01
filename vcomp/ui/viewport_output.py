"""9:16 output viewport with placement handles for the selected HUD Region.

M4 interactions: move (drag body), uniform scale (drag a corner), rotate (drag
the stem handle above the quad). Snapping to canvas edges / centre lines / the
Main Framing band, with pink guides. Solo / Hide are driven from the main window.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from vcomp.ui import theme
from vcomp.ui.snapping import snap_point
from vcomp.ui.viewport_base import ImageViewport

_HS = 6.0


class OutputViewport(ImageViewport):
    moveDest = Signal(str, float, float, bool)     # id, dest_x, dest_y, final
    scaleDest = Signal(str, float, bool)           # id, dest_scale, final
    rotateDest = Signal(str, float, bool)          # id, rotation_deg, final

    def __init__(self) -> None:
        super().__init__(9 / 16)
        self._sel_id: str | None = None
        self._quad: tuple[float, float, float, float] | None = None   # x0y0x1y1
        self._center = (0.5, 0.5)
        self._scale = 1.0
        self._rot = 0.0
        self._band: tuple[float, float, float, float] | None = None
        self._drag = None
        self._guides = ([], [])

    def empty_text(self) -> str:
        return "Output\n(load a clip)"

    def set_frame(self, arr: np.ndarray) -> None:
        self.set_content_array(arr)

    def set_selection(self, node_id: str | None, quad, center, scale, rot, band) -> None:
        self._sel_id = node_id
        self._quad = quad
        self._center = center or (0.5, 0.5)
        self._scale = scale or 1.0
        self._rot = rot or 0.0
        self._band = band
        self.update()

    # --------------------------------------------------------------- paint
    def paint_overlay(self, p: QPainter) -> None:
        if self._band:
            x0, y0, x1, y1 = self._band
            r = QRectF(self.norm_to_widget(x0, y0), self.norm_to_widget(x1, y1))
            p.setPen(QPen(QColor("#5cff9e"), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)

        if self._sel_id and self._quad:
            x0, y0, x1, y1 = self._quad
            r = QRectF(self.norm_to_widget(x0, y0), self.norm_to_widget(x1, y1))
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            for cx, cy in self._corners(r):
                p.drawRect(QRectF(cx - _HS, cy - _HS, 2 * _HS, 2 * _HS))
            # rotate stem
            stem = QPointF(r.center().x(), r.top() - 26)
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.drawLine(QPointF(r.center().x(), r.top()), stem)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(stem, _HS, _HS)

        gx, gy = self._guides
        p.setPen(QPen(QColor("#ff5aa8"), 1, Qt.PenStyle.DashLine))
        for x in gx:
            wx = self.norm_to_widget(x, 0).x()
            p.drawLine(QPointF(wx, 0), QPointF(wx, self.height()))
        for y in gy:
            wy = self.norm_to_widget(0, y).y()
            p.drawLine(QPointF(0, wy), QPointF(self.width(), wy))

    @staticmethod
    def _corners(r: QRectF):
        return [(r.left(), r.top()), (r.right(), r.top()),
                (r.right(), r.bottom()), (r.left(), r.bottom())]

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self._space or not self._sel_id or not self._quad:
            return super().mousePressEvent(e)
        pos = e.position()
        x0, y0, x1, y1 = self._quad
        r = QRectF(self.norm_to_widget(x0, y0), self.norm_to_widget(x1, y1))

        stem = QPointF(r.center().x(), r.top() - 26)
        if (pos - stem).manhattanLength() < 16:
            self._drag = {"mode": "rotate", "start_ang": self._angle(pos, r.center()),
                          "orig": self._rot}
            return
        for cx, cy in self._corners(r):
            if abs(pos.x() - cx) <= _HS + 3 and abs(pos.y() - cy) <= _HS + 3:
                d0 = math.hypot(cx - r.center().x(), cy - r.center().y())
                self._drag = {"mode": "scale", "d0": d0, "orig": self._scale,
                              "center": r.center()}
                return
        if r.contains(pos):
            n = self.widget_to_norm(pos)
            self._drag = {"mode": "move", "start": n, "orig": self._center}
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._panning or self._drag is None:
            return super().mouseMoveEvent(e)
        pos = e.position()
        mode = self._drag["mode"]

        if mode == "move":
            n = self.widget_to_norm(pos)
            dx = n.x() - self._drag["start"].x()
            dy = n.y() - self._drag["start"].y()
            ncx = self._drag["orig"][0] + dx
            ncy = self._drag["orig"][1] + dy
            cand = [0.0, 0.5, 1.0]
            bandc = []
            if self._band:
                bandc = [self._band[1], self._band[3], (self._band[1] + self._band[3]) / 2]
            sp = snap_point(ncx, ncy, cand, cand + bandc, 0.012,
                            enabled=not (e.modifiers() & Qt.KeyboardModifier.AltModifier))
            self._guides = (sp.guides_x, sp.guides_y)
            self.moveDest.emit(self._sel_id, sp.x, sp.y, False)
        elif mode == "scale":
            d = math.hypot(pos.x() - self._drag["center"].x(),
                           pos.y() - self._drag["center"].y())
            factor = d / max(self._drag["d0"], 1e-3)
            self.scaleDest.emit(self._sel_id, max(0.02, self._drag["orig"] * factor), False)
        else:  # rotate
            ang = self._angle(pos, QPointF(*self._norm_center_px()))
            deg = self._drag["orig"] + math.degrees(ang - self._drag["start_ang"])
            self.rotateDest.emit(self._sel_id, (deg + 180) % 360 - 180, False)
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is None:
            return super().mouseReleaseEvent(e)
        mode = self._drag["mode"]
        self._drag = None
        self._guides = ([], [])
        if mode == "move":
            self.moveDest.emit(self._sel_id, self._center[0], self._center[1], True)
        elif mode == "scale":
            self.scaleDest.emit(self._sel_id, self._scale, True)
        else:
            self.rotateDest.emit(self._sel_id, self._rot, True)
        self.update()

    def _norm_center_px(self):
        p = self.norm_to_widget(*self._center)
        return (p.x(), p.y())

    @staticmethod
    def _angle(p: QPointF, c: QPointF) -> float:
        return math.atan2(p.y() - c.y(), p.x() - c.x())
