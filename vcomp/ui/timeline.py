"""Transport / timeline.

A scrubbable time ruler (click or drag anywhere to move the playhead), transport
buttons, in/out range, loop, a seconds+frames readout, and a cache bar showing
which frames are decoded. Playback runs against a wall clock and drops frames to
hold real time when rendering can't keep up.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vcomp.ui import theme


def _fmt(frame: int, fps: float) -> str:
    if fps <= 0:
        return "00:00 f00"
    total = frame / fps
    m, s = divmod(total, 60)
    ff = frame % max(1, round(fps))
    return f"{int(m):02d}:{int(s):02d} f{ff:02d}"


# ---------------------------------------------------------------- cache bar
class CacheBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(4)
        self._count = 0
        self._warm: set[int] = set()

    def update_state(self, count: int, warm: set[int]) -> None:
        self._count, self._warm = count, warm
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141418"))
        if self._count <= 0:
            return
        w = self.width()
        cw = max(1.0, w / self._count)
        col = QColor(theme.ACCENT)
        col.setAlpha(150)
        for n in self._warm:
            p.fillRect(QRectF(n / self._count * w, 0, cw + 1, self.height()), col)


# ------------------------------------------------------------------- ruler
class TimeRuler(QWidget):
    seek = Signal(int)
    setIn = Signal(int)
    setOut = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(38)
        self.setMouseTracking(True)
        self._count = 0
        self._fps = 30.0
        self._frame = 0
        self.in_point = 0
        self.out_point = 0
        self._drag = None   # 'head' | 'in' | 'out' | None

    def configure(self, count: int, fps: float) -> None:
        self._count = max(0, count)
        self._fps = fps if fps > 0 else 30.0
        self.update()

    def set_frame(self, f: int) -> None:
        self._frame = f
        self.update()

    def set_in_out(self, a: int, b: int) -> None:
        self.in_point, self.out_point = a, b
        self.update()

    # -------------------------------------------------------- geometry
    def _x(self, frame: float) -> float:
        if self._count <= 1:
            return 0.0
        return frame / (self._count - 1) * (self.width() - 1)

    def _frame_at(self, x: float) -> int:
        if self._count <= 1:
            return 0
        return int(round(x / max(1, self.width() - 1) * (self._count - 1)))

    # ------------------------------------------------------------ paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        p.fillRect(self.rect(), QColor("#1c1c22"))

        if self._count <= 1:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no clip")
            return

        # in / out shaded range
        x0, x1 = self._x(self.in_point), self._x(self.out_point)
        p.fillRect(QRectF(x0, 0, x1 - x0, h), QColor(76, 141, 255, 28))
        for x, sig in ((x0, "in"), (x1, "out")):
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, h))

        # ticks: aim for ~1 label every 90 px
        total_s = (self._count - 1) / self._fps
        px_per_s = self.width() / max(total_s, 1e-6)
        step = _nice_step(90 / max(px_per_s, 1e-6))
        p.setPen(QColor(theme.TEXT_DIM))
        t = 0.0
        while t <= total_s + 1e-6:
            x = self._x(t * self._fps)
            p.drawLine(QPointF(x, h - 10), QPointF(x, h))
            m, s = divmod(t, 60)
            p.drawText(QRectF(x + 2, 2, 60, 12), Qt.AlignmentFlag.AlignLeft,
                       f"{int(m):d}:{s:04.1f}" if step < 1 else f"{int(m):d}:{int(s):02d}")
            t += step

        # playhead
        hx = self._x(self._frame)
        p.setPen(QPen(QColor("#ff5555"), 1.5))
        p.drawLine(QPointF(hx, 0), QPointF(hx, h))
        tri = QPolygonF([QPointF(hx - 5, 0), QPointF(hx + 5, 0), QPointF(hx, 8)])
        p.setBrush(QColor("#ff5555"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(tri)

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, e) -> None:  # noqa: N802
        x = e.position().x()
        if abs(x - self._x(self.in_point)) < 6:
            self._drag = "in"
        elif abs(x - self._x(self.out_point)) < 6:
            self._drag = "out"
        else:
            self._drag = "head"
            self.seek.emit(self._frame_at(x))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._drag:
            return
        f = self._frame_at(e.position().x())
        if self._drag == "head":
            self.seek.emit(f)
        elif self._drag == "in":
            self.setIn.emit(min(f, self.out_point))
        else:
            self.setOut.emit(max(f, self.in_point))

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self._drag = None


def _nice_step(sec: float) -> float:
    for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if s >= sec:
            return float(s)
    return 900.0


# ---------------------------------------------------------------- timeline
class Timeline(QWidget):
    frameChanged = Signal(int)
    inOutChanged = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._fps = 30.0
        self._count = 0
        self._frame = 0
        self.in_point = 0
        self.out_point = 0
        self._loop = False
        self._play_t0 = 0.0
        self._play_f0 = 0

        self._timer = QTimer(self)
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)

        self._build()
        self.set_media(0, 30.0)

    def _build(self) -> None:
        self.ruler = TimeRuler()
        self.ruler.seek.connect(self.seek)
        self.ruler.setIn.connect(self._set_in)
        self.ruler.setOut.connect(self._set_out)
        self.cache_bar = CacheBar()

        self.btn_play = QPushButton("Play")
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self.set_playing)

        b_prev = QPushButton("|<")
        b_pf = QPushButton("<")
        b_nf = QPushButton(">")
        b_next = QPushButton(">|")
        b_prev.clicked.connect(lambda: self.seek(self.in_point))
        b_next.clicked.connect(lambda: self.seek(self.out_point))
        b_pf.clicked.connect(lambda: self.seek(self._frame - 1))
        b_nf.clicked.connect(lambda: self.seek(self._frame + 1))

        self.btn_in = QPushButton("Set In")
        self.btn_out = QPushButton("Set Out")
        self.btn_in.clicked.connect(lambda: self._set_in(self._frame))
        self.btn_out.clicked.connect(lambda: self._set_out(self._frame))

        self.btn_loop = QPushButton("Loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.toggled.connect(self._set_loop)

        self.lbl = QLabel("00:00 f00 / 00:00 f00")
        self.lbl.setStyleSheet(f"color:{theme.TEXT_DIM};")

        row = QHBoxLayout()
        for w in (b_prev, b_pf, self.btn_play, b_nf, b_next):
            row.addWidget(w)
        row.addSpacing(12)
        row.addWidget(self.btn_in)
        row.addWidget(self.btn_out)
        row.addWidget(self.btn_loop)
        row.addStretch(1)
        row.addWidget(self.lbl)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.addWidget(self.ruler)
        lay.addWidget(self.cache_bar)
        lay.addLayout(row)

    # ----------------------------------------------------------------- state
    def set_media(self, frame_count: int, fps: float) -> None:
        self.set_playing(False)
        self._fps = fps if fps > 0 else 30.0
        self._count = max(0, frame_count)
        self._frame = 0
        self.in_point = 0
        self.out_point = max(0, self._count - 1)
        self.ruler.configure(self._count, self._fps)
        self.ruler.set_in_out(self.in_point, self.out_point)
        self.ruler.set_frame(0)
        self._update_label()

    @property
    def frame(self) -> int:
        return self._frame

    def seek(self, index: int) -> None:
        index = max(0, min(int(index), max(0, self._count - 1)))
        if index == self._frame:
            return
        self._frame = index
        self.ruler.set_frame(index)
        self._update_label()
        self.frameChanged.emit(index)

    def set_playing(self, on: bool) -> None:
        if on and self._count > 1:
            self._play_t0 = time.monotonic()
            self._play_f0 = self._frame if self._frame < self.out_point else self.in_point
            if self._frame >= self.out_point:
                self.seek(self.in_point)
            self._timer.start()
        else:
            self._timer.stop()
        if self.btn_play.isChecked() != on:
            self.btn_play.blockSignals(True)
            self.btn_play.setChecked(on)
            self.btn_play.blockSignals(False)
        self.btn_play.setText("Pause" if on else "Play")

    def toggle_play(self) -> None:
        self.set_playing(not self._timer.isActive())

    def set_cache_state(self, warm: set[int]) -> None:
        self.cache_bar.update_state(self._count, warm)

    # ------------------------------------------------------------------ slots
    def _tick(self) -> None:
        elapsed = time.monotonic() - self._play_t0
        target = self._play_f0 + int(elapsed * self._fps)   # real-time; drops frames
        if target > self.out_point:
            if self._loop:
                self._play_t0 = time.monotonic()
                self._play_f0 = self.in_point
                target = self.in_point
            else:
                self.seek(self.out_point)
                self.set_playing(False)
                return
        self.seek(target)

    def _set_in(self, f: int) -> None:
        self.in_point = max(0, min(int(f), self.out_point))
        self.ruler.set_in_out(self.in_point, self.out_point)
        self.inOutChanged.emit(self.in_point, self.out_point)
        self._update_label()

    def _set_out(self, f: int) -> None:
        self.out_point = max(self.in_point, min(int(f), max(0, self._count - 1)))
        self.ruler.set_in_out(self.in_point, self.out_point)
        self.inOutChanged.emit(self.in_point, self.out_point)
        self._update_label()

    def _set_loop(self, on: bool) -> None:
        self._loop = on

    def _update_label(self) -> None:
        self.lbl.setText(
            f"{_fmt(self._frame, self._fps)}  /  {_fmt(max(0, self._count - 1), self._fps)}"
            f"   in {self.in_point}  out {self.out_point}"
        )
