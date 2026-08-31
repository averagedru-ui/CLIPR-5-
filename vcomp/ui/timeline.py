"""Transport / timeline bar.

M1 scope: scrub slider, play/pause, single-frame step, jump to in/out, set
in/out, loop toggle, a seconds+frames readout, and a thin cache bar showing
which frames are decoded and warm. Keyframe track lands in M5.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from vcomp.ui import theme


def _fmt(frame: int, fps: float) -> str:
    if fps <= 0:
        return "00:00:00 f0"
    total = frame / fps
    m, s = divmod(total, 60)
    ff = frame % max(1, round(fps))
    return f"{int(m):02d}:{int(s):02d} f{ff:02d}"


class CacheBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(6)
        self._count = 0
        self._warm: set[int] = set()

    def update_state(self, count: int, warm: set[int]) -> None:
        self._count = count
        self._warm = warm
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#141418"))
        if self._count <= 0:
            return
        w = self.width()
        for n in self._warm:
            x = int(n / self._count * w)
            p.fillRect(QRect(x, 0, max(1, w // self._count + 1), self.height()),
                       QColor(theme.ACCENT))


class Timeline(QWidget):
    frameChanged = Signal(int)          # user or playback moved the playhead
    inOutChanged = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self._fps = 30.0
        self._count = 0
        self._frame = 0
        self.in_point = 0
        self.out_point = 0
        self._loop = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._build()
        self.set_media(0, 30.0)

    # --------------------------------------------------------------- building
    def _build(self) -> None:
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._on_slider)

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
        lay.addWidget(self.slider)
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
        self.slider.blockSignals(True)
        self.slider.setRange(0, self.out_point)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._timer.setInterval(int(1000 / self._fps))
        self._update_label()

    @property
    def frame(self) -> int:
        return self._frame

    def seek(self, index: int) -> None:
        index = max(0, min(index, max(0, self._count - 1)))
        if index == self._frame:
            return
        self._frame = index
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        self._update_label()
        self.frameChanged.emit(index)

    def set_playing(self, on: bool) -> None:
        if on and self._count > 1:
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
        nxt = self._frame + 1
        if nxt > self.out_point:
            if self._loop:
                nxt = self.in_point
            else:
                self.set_playing(False)
                return
        self.seek(nxt)

    def _on_slider(self, v: int) -> None:
        self.seek(v)

    def _set_in(self, f: int) -> None:
        self.in_point = min(f, self.out_point)
        self.inOutChanged.emit(self.in_point, self.out_point)
        self._update_label()

    def _set_out(self, f: int) -> None:
        self.out_point = max(f, self.in_point)
        self.inOutChanged.emit(self.in_point, self.out_point)
        self._update_label()

    def _set_loop(self, on: bool) -> None:
        self._loop = on

    def _update_label(self) -> None:
        self.lbl.setText(
            f"{_fmt(self._frame, self._fps)}  /  {_fmt(max(0, self._count - 1), self._fps)}"
            f"   in {self.in_point}  out {self.out_point}"
        )
