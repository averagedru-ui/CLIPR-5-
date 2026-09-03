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
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QPushButton

from vcomp.ui import theme
from vcomp.ui.snapping import edges, snap_point
from vcomp.ui.viewport_base import ImageViewport

_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")

_HANDLES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
_HS = 6.0   # handle half-size px


class SourceViewport(ImageViewport):
    createRegion = Signal(float, float, float, float)     # x,y,w,h norm
    createPolygon = Signal(list)                          # [(x,y), ...] source-norm
    editRect = Signal(str, tuple, bool)                   # node_id, (x,y,w,h), final
    editPolygon = Signal(str, list, bool)                 # node_id, [(x,y),...], final
    selectRegion = Signal(str)
    pickColor = Signal(tuple)
    openClip = Signal()                                   # "Open Clip" button
    fileDropped = Signal(str)                             # a video file dropped

    def __init__(self) -> None:
        super().__init__(16 / 9)
        self._regions: list[dict] = []          # {id,label,rect,selected,shape,points}
        self._frame: np.ndarray | None = None
        self._create_armed = False
        self._poly_pts: list[QPointF] | None = None   # in-progress polygon (norm)
        self._cursor_n = QPointF(0.0, 0.0)
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
        self._cancel_polygon()
        self._create_armed = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    def arm_polygon(self) -> None:
        """Start a click-to-place polygon mask. Click to add points, click the
        first point (or Enter / double-click) to close, Esc to cancel."""
        self._create_armed = False
        self._poly_pts = []
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus()
        self.update()

    def _cancel_polygon(self) -> None:
        if self._poly_pts is not None:
            self._poly_pts = None
            self.unsetCursor()
            self.update()

    def _finish_polygon(self) -> None:
        pts = self._poly_pts or []
        self._poly_pts = None
        self.unsetCursor()
        if len(pts) >= 3:
            self.createPolygon.emit([(p.x(), p.y()) for p in pts])
        self.update()

    def arm_eyedropper(self) -> None:
        self._eyedrop = True
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --------------------------------------------------------------- paint
    def paint_overlay(self, p: QPainter) -> None:
        for reg in self._regions:
            sel = reg["selected"]
            pts = reg.get("points") or []
            is_poly = reg.get("shape") == "polygon" and len(pts) >= 3
            x, y, w, h = reg["rect"]
            tl = self.norm_to_widget(x, y)
            br = self.norm_to_widget(x + w, y + h)
            rect = QRectF(tl, br)

            p.setPen(QPen(QColor(theme.ACCENT if sel else "#889"), 2 if sel else 1,
                          Qt.PenStyle.SolidLine if sel else Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if is_poly:
                poly = QPolygonF([self.norm_to_widget(px, py) for px, py in pts])
                p.drawPolygon(poly)
            else:
                p.drawRect(rect)

            p.setPen(QColor(theme.TEXT if sel else theme.TEXT_DIM))
            p.drawText(rect.adjusted(3, 2, -3, -3),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, reg["label"])

            if sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT))
                if is_poly:
                    for px, py in pts:
                        c = self.norm_to_widget(px, py)
                        p.drawEllipse(c, _HS, _HS)
                else:
                    for hx, hy in self._handle_points(rect):
                        p.drawRect(QRectF(hx - _HS, hy - _HS, 2 * _HS, 2 * _HS))

        if self._poly_pts is not None:
            self._paint_poly_draft(p)

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

    def _paint_poly_draft(self, p: QPainter) -> None:
        pw = [self.norm_to_widget(pt.x(), pt.y()) for pt in self._poly_pts]
        cur = self.norm_to_widget(self._cursor_n.x(), self._cursor_n.y())
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.setBrush(QColor(76, 141, 255, 40))
        if len(pw) >= 2:
            p.drawPolyline(QPolygonF(pw))
        if pw:
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.PenStyle.DashLine))
            p.drawLine(pw[-1], cur)
            if len(pw) >= 2:
                p.drawLine(cur, pw[0])          # preview closing edge
        p.setPen(Qt.PenStyle.NoPen)
        for i, c in enumerate(pw):
            p.setBrush(QColor("#fff") if i == 0 else QColor(theme.ACCENT))
            p.drawEllipse(c, _HS, _HS)

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

    def _hit_poly_vertex(self, pos: QPointF):
        """(region, vertex_index) if ``pos`` is on a vertex of the selected
        polygon region, else None."""
        reg = self._selected()
        if not reg or reg.get("shape") != "polygon":
            return None
        for i, (px, py) in enumerate(reg.get("points") or []):
            if _dist(pos, self.norm_to_widget(px, py)) <= _HS + 3:
                return (reg, i)
        return None

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        if self._poly_pts is not None:
            self._finish_polygon()
            return
        super().mouseDoubleClickEvent(e)

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
        pos = e.position()

        # right-click removes a polygon vertex
        if (e.button() == Qt.MouseButton.RightButton and self._poly_pts is None):
            hit = self._hit_poly_vertex(pos)
            if hit is not None:
                reg, idx = hit
                pts = list(reg["points"])
                if len(pts) > 3:
                    del pts[idx]
                    self.editPolygon.emit(reg["id"], pts, True)
                return
            return super().mousePressEvent(e)

        if e.button() != Qt.MouseButton.LeftButton or self._space:
            return super().mousePressEvent(e)

        # placing points for a new polygon
        if self._poly_pts is not None:
            n = self.widget_to_norm(pos)
            if self._poly_pts:
                first = self.norm_to_widget(self._poly_pts[0].x(), self._poly_pts[0].y())
                if len(self._poly_pts) >= 3 and _dist(pos, first) < 12:
                    self._finish_polygon()
                    return
            self._poly_pts.append(QPointF(min(1.0, max(0.0, n.x())),
                                          min(1.0, max(0.0, n.y()))))
            self.update()
            return

        # dragging a vertex of the selected polygon region
        hit = self._hit_poly_vertex(pos)
        if hit is not None:
            reg, idx = hit
            self._drag = {"mode": "poly_vert", "id": reg["id"],
                          "pts": list(reg["points"]), "idx": idx}
            return

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
            if hit.get("shape") == "polygon" and hit.get("points"):
                self._drag = {"mode": "poly_move", "id": hit["id"],
                              "pts": list(hit["points"]), "start": n}
            else:
                self._drag = {"mode": "move", "id": hit["id"], "orig": hit["rect"],
                              "start": n}
        else:
            self.selectRegion.emit("")

    def mouseMoveEvent(self, e):  # noqa: N802
        pos = e.position()

        if self._poly_pts is not None:
            self._cursor_n = self.widget_to_norm(pos)
            self.update()
            return

        if self._panning or self._drag is None:
            return super().mouseMoveEvent(e)
        alt = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)
        mode = self._drag["mode"]

        if mode == "poly_vert":
            n = self.widget_to_norm(pos)
            pts = list(self._drag["pts"])
            pts[self._drag["idx"]] = (min(1.0, max(0.0, n.x())),
                                      min(1.0, max(0.0, n.y())))
            self._drag["current"] = pts
            self.editPolygon.emit(self._drag["id"], pts, False)
            self.update()
            return

        if mode == "poly_move":
            n = self.widget_to_norm(pos)
            dx = n.x() - self._drag["start"].x()
            dy = n.y() - self._drag["start"].y()
            pts = [(min(1.0, max(0.0, x + dx)), min(1.0, max(0.0, y + dy)))
                   for x, y in self._drag["pts"]]
            self._drag["current"] = pts
            self.editPolygon.emit(self._drag["id"], pts, False)
            self.update()
            return

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

        if drag["mode"] in ("poly_vert", "poly_move"):
            pts = drag.get("current", drag["pts"])
            self.editPolygon.emit(drag["id"], pts, True)
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
        if e.key() == Qt.Key.Key_P:
            self.arm_polygon()
            return
        if self._poly_pts is not None:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish_polygon()
                return
            if e.key() == Qt.Key.Key_Escape:
                self._cancel_polygon()
                return
            if e.key() == Qt.Key.Key_Backspace and self._poly_pts:
                self._poly_pts.pop()
                self.update()
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


def _dist(a: QPointF, b: QPointF) -> float:
    return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
