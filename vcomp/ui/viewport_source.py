"""16:9 source viewport with HUD Region source-rect editing.

Interactions (spec 7.2):
  * pan/zoom (from ImageViewport)
  * every HUD Region's source rect drawn as an overlay; selected bright, others
    dim with their label
  * 8 resize handles + move body on the selected rect
  * hold ``M`` then drag to create a new region
  * arrow-key nudge (1 px, Shift = 10 px)
  * eyedropper: arm with Alt+I, next click samples a pixel
  * snapping to source edges / other rects / a grid; hold Alt to disable
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QPushButton

from vcomp.ui import theme
from vcomp.ui.snapping import edges, snap_point
from vcomp.ui.viewport_base import ImageViewport

_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

_HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
_HS = 6.0   # handle half-size px


class SourceViewport(ImageViewport):
    createRegion = Signal(float, float, float, float)     # x,y,w,h norm
    editRect = Signal(str, tuple, bool)                   # node_id, (x,y,w,h), final
    selectRegion = Signal(str)
    pickColor = Signal(tuple)
    openClip = Signal()                                   # "Open Clip" button
    fileDropped = Signal(str)                             # a video file dropped

    def __init__(self) -> None:
        super().__init__(16 / 9)
        self._regions: list[dict] = []          # {id,label,rect,selected}
        self._frame: np.ndarray | None = None
        self._create_armed = False
        self._eyedrop = False
        self._drag = None                       # dict with mode/anchor/orig
        self._rubber: QRectF | None = None
        self._guides = ([], [])

        self.setAcceptDrops(True)
        self._open_btn = QPushButton("Open Clip…", self)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT}; color:white; border:none;"
            f" border-radius:6px; padding:10px 22px; font-size:14px;}}"
            f"QPushButton:hover{{background:#3f7ae0;}}")
        self._open_btn.clicked.connect(self.openClip)
        self._open_btn.adjustSize()
        self._position_button()

    def empty_text(self) -> str:
        return "\n\n\ndrop a video here  ·  Ctrl+O"

    def _position_button(self) -> None:
        self._open_btn.move((self.width() - self._open_btn.width()) // 2,
                            (self.height() - self._open_btn.height()) // 2)
        self._open_btn.setVisible(self._frame is None)
        if self._frame is None:
            self._open_btn.raise_()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._position_button()

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(_VIDEO_EXT) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(_VIDEO_EXT):
                self.fileDropped.emit(p)
                e.acceptProposedAction()
                return

    # ------------------------------------------------------------- external
    def set_frame(self, arr: np.ndarray) -> None:
        self._frame = arr
        self.set_content_array(arr)
        self._position_button()

    def set_regions(self, regions: list[dict]) -> None:
        self._regions = regions
        self.update()

    def arm_create(self) -> None:
        self._create_armed = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    def arm_eyedropper(self) -> None:
        self._eyedrop = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --------------------------------------------------------------- paint
    def paint_overlay(self, p: QPainter) -> None:
        for reg in self._regions:
            x, y, w, h = reg["rect"]
            tl = self.norm_to_widget(x, y)
            br = self.norm_to_widget(x + w, y + h)
            rect = QRectF(tl, br)
            sel = reg["selected"]
            p.setPen(QPen(QColor(theme.ACCENT if sel else "#889"), 2 if sel else 1,
                          Qt.PenStyle.SolidLine if sel else Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(rect)
            p.setPen(QColor(theme.TEXT if sel else theme.TEXT_DIM))
            p.drawText(rect.adjusted(3, 2, -3, -3),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, reg["label"])
            if sel:
                p.setBrush(QColor(theme.ACCENT))
                p.setPen(Qt.PenStyle.NoPen)
                for hx, hy in self._handle_points(rect):
                    p.drawRect(QRectF(hx - _HS, hy - _HS, 2 * _HS, 2 * _HS))

        if self._rubber is not None:
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(76, 141, 255, 40))
            p.drawRect(self._rubber)

        gx, gy = self._guides
        p.setPen(QPen(QColor("#ff5aa8"), 1, Qt.PenStyle.DashLine))
        for x in gx:
            wx = self.norm_to_widget(x, 0).x()
            p.drawLine(QPointF(wx, 0), QPointF(wx, self.height()))
        for y in gy:
            wy = self.norm_to_widget(0, y).y()
            p.drawLine(QPointF(0, wy), QPointF(self.width(), wy))

    def _handle_points(self, rect: QRectF):
        cx, cy = rect.center().x(), rect.center().y()
        return {
            "nw": (rect.left(), rect.top()), "n": (cx, rect.top()),
            "ne": (rect.right(), rect.top()), "e": (rect.right(), cy),
            "se": (rect.right(), rect.bottom()), "s": (cx, rect.bottom()),
            "sw": (rect.left(), rect.bottom()), "w": (rect.left(), cy),
        }.values() if False else [
            (rect.left(), rect.top()), (cx, rect.top()), (rect.right(), rect.top()),
            (rect.right(), cy), (rect.right(), rect.bottom()), (cx, rect.bottom()),
            (rect.left(), rect.bottom()), (rect.left(), cy),
        ]

    # --------------------------------------------------------------- mouse
    def _selected(self) -> dict | None:
        return next((r for r in self._regions if r["selected"]), None)

    def _hit_handle(self, pos: QPointF) -> str | None:
        reg = self._selected()
        if not reg:
            return None
        x, y, w, h = reg["rect"]
        tl = self.norm_to_widget(x, y)
        br = self.norm_to_widget(x + w, y + h)
        rect = QRectF(tl, br)
        for name, (hx, hy) in zip(_HANDLES, self._handle_points(rect)):
            if abs(pos.x() - hx) <= _HS + 2 and abs(pos.y() - hy) <= _HS + 2:
                return name
        return None

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self._space:
            return super().mousePressEvent(e)
        pos = e.position()

        if self._eyedrop and self._frame is not None:
            n = self.widget_to_norm(pos)
            h, w = self._frame.shape[:2]
            ix = int(np.clip(n.x() * w, 0, w - 1))
            iy = int(np.clip(n.y() * h, 0, h - 1))
            px = self._frame[iy, ix][:3]
            self.pickColor.emit((px[0] / 255, px[1] / 255, px[2] / 255))
            self._eyedrop = False
            self.unsetCursor()
            return

        if self._create_armed:
            n = self.widget_to_norm(pos)
            self._drag = {"mode": "create", "start": n}
            self._rubber = QRectF(pos, pos)
            return

        handle = self._hit_handle(pos)
        if handle:
            reg = self._selected()
            self._drag = {"mode": "resize", "handle": handle, "id": reg["id"],
                          "orig": reg["rect"], "startpx": pos}
            return

        # select / start move
        n = self.widget_to_norm(pos)
        hit = None
        for reg in reversed(self._regions):
            x, y, w, h = reg["rect"]
            if x <= n.x() <= x + w and y <= n.y() <= y + h:
                hit = reg
                break
        if hit:
            if not hit["selected"]:
                self.selectRegion.emit(hit["id"])
            self._drag = {"mode": "move", "id": hit["id"], "orig": hit["rect"],
                          "start": n}
        else:
            self.selectRegion.emit("")

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._panning or self._drag is None:
            return super().mouseMoveEvent(e)
        pos = e.position()
        alt = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
        mode = self._drag["mode"]

        if mode == "create":
            self._rubber = QRectF(self.norm_to_widget(*_xy(self._drag["start"])), pos).normalized()
            self.update()
            return

        n = self.widget_to_norm(pos)
        others = [(_r[0], _r[1], _r[0] + _r[2], _r[1] + _r[3])
                  for reg in self._regions if reg["id"] != self._drag["id"]
                  for _r in (reg["rect"],)]
        cx = [0.0, 0.5, 1.0] + edges(others)[0]
        cy = [0.0, 0.5, 1.0] + edges(others)[1]
        tol = 0.012

        ox, oy, ow, oh = self._drag["orig"]
        if mode == "move":
            dx = n.x() - self._drag["start"].x()
            dy = n.y() - self._drag["start"].y()
            nx, ny = ox + dx, oy + dy
            snap = snap_point(nx, ny, cx, cy, tol, enabled=not alt)
            nx, ny = snap.x, snap.y
            rect = (max(0.0, min(nx, 1 - ow)), max(0.0, min(ny, 1 - oh)), ow, oh)
            self._guides = (snap.guides_x, snap.guides_y)
        else:  # resize
            x0, y0, x1, y1 = ox, oy, ox + ow, oy + oh
            hnd = self._drag["handle"]
            if "n" in hnd:
                y0 = min(n.y(), y1 - 0.01)
            if "s" in hnd:
                y1 = max(n.y(), y0 + 0.01)
            if "w" in hnd:
                x0 = min(n.x(), x1 - 0.01)
            if "e" in hnd:
                x1 = max(n.x(), x0 + 0.01)
            sp = snap_point(x0, y0, cx, cy, tol, enabled=not alt)
            sp2 = snap_point(x1, y1, cx, cy, tol, enabled=not alt)
            if "w" in hnd:
                x0 = sp.x
            if "n" in hnd:
                y0 = sp.y
            if "e" in hnd:
                x1 = sp2.x
            if "s" in hnd:
                y1 = sp2.y
            self._guides = (sp.guides_x + sp2.guides_x, sp.guides_y + sp2.guides_y)
            rect = (max(0.0, x0), max(0.0, y0), min(1.0, x1) - max(0.0, x0),
                    min(1.0, y1) - max(0.0, y0))

        self._drag["current"] = rect
        self.editRect.emit(self._drag["id"], rect, False)
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._drag is None:
            return super().mouseReleaseEvent(e)
        drag = self._drag
        self._drag = None
        self._guides = ([], [])

        if drag["mode"] == "create":
            r = self._rubber
            self._rubber = None
            self._create_armed = False
            self.unsetCursor()
            if r and r.width() > 4 and r.height() > 4:
                a = self.widget_to_norm(r.topLeft())
                b = self.widget_to_norm(r.bottomRight())
                self.createRegion.emit(a.x(), a.y(), b.x() - a.x(), b.y() - a.y())
            self.update()
            return

        rect = drag.get("current", drag["orig"])
        self.editRect.emit(drag["id"], rect, True)
        self.update()

    # --------------------------------------------------------------- keys
    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_M:
            self.arm_create()
            return
        reg = self._selected()
        if reg and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 0.01 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.001
            x, y, w, h = reg["rect"]
            if e.key() == Qt.Key.Key_Left:
                x -= step
            elif e.key() == Qt.Key.Key_Right:
                x += step
            elif e.key() == Qt.Key.Key_Up:
                y -= step
            else:
                y += step
            rect = (max(0.0, min(x, 1 - w)), max(0.0, min(y, 1 - h)), w, h)
            self.editRect.emit(reg["id"], rect, True)
            return
        super().keyPressEvent(e)


def _xy(pt):
    return (pt.x(), pt.y())
