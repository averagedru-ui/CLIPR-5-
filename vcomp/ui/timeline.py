"""Transport / timeline.

A scrubbable time ruler, transport buttons, in/out range, loop, a timecode
readout, a render-cache bar, and - when a clip carries more than one audio
stream (OBS multi-track) - one waveform lane per track with mute / solo.
Playback runs against a wall clock and drops frames to hold real time.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vcomp.ui import theme

_ACCENT = QColor(theme.ACCENT_HI)
_PLAYHEAD = QColor("#e5484d")
_LANE_H = 44
_LABEL_BAND = 15

_LANE_BTN_QSS = f"""
QPushButton {{
    border: 1px solid {theme.BORDER_HI}; border-radius: 4px;
    background: {theme.SURFACE_3}; color: {theme.TEXT_DIM};
    font-size: 11px; font-weight: 700; padding: 0;
}}
QPushButton:hover {{ border-color: {theme.TEXT_DIM}; }}
QPushButton#mute:checked {{ background: #d1443b; border-color: #d1443b; color: white; }}
QPushButton#solo:checked {{ background: #d8a13a; border-color: #d8a13a; color: #1a1400; }}
"""


def _timecode(frame: int, fps: float) -> str:
    if fps <= 0:
        return "00:00:00"
    total = frame / fps
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    ff = frame % max(1, round(fps))
    if h >= 1:
        return f"{int(h)}:{int(m):02d}:{int(s):02d};{ff:02d}"
    return f"{int(m):02d}:{int(s):02d};{ff:02d}"


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
        p.fillRect(self.rect(), QColor(theme.SURFACE_2))
        if self._count <= 0:
            return
        w = self.width()
        cw = max(1.0, w / self._count)
        col = QColor(_ACCENT)
        col.setAlpha(170)
        for n in self._warm:
            p.fillRect(QRectF(n / self._count * w, 0, cw + 1, self.height()), col)


# ------------------------------------------------------------------- ruler
class TimeRuler(QWidget):
    seek = Signal(int)
    setIn = Signal(int)
    setOut = Signal(int)

    _H = 46
    _GRIP = _LABEL_BAND + 12     # clicks above this Y grab an in/out handle;
                                 # clicks below always scrub (so frame 0 is reachable)

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(self._H)
        self.setMouseTracking(True)
        self._count = 0
        self._fps = 30.0
        self._frame = 0
        self.in_point = 0
        self.out_point = 0
        self._drag = None

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

    def _x(self, frame: float) -> float:
        if self._count <= 1:
            return 0.0
        return frame / (self._count - 1) * (self.width() - 1)

    def _frame_at(self, x: float) -> int:
        if self._count <= 1:
            return 0
        return int(round(x / max(1, self.width() - 1) * (self._count - 1)))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.SURFACE))

        if self._count <= 1:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no clip loaded")
            return

        track_top = _LABEL_BAND

        # in / out shaded range + edges
        x0, x1 = self._x(self.in_point), self._x(self.out_point)
        shade = QColor(_ACCENT)
        shade.setAlpha(26)
        p.fillRect(QRectF(x0, track_top, x1 - x0, h - track_top), shade)
        p.setPen(QPen(QColor(_ACCENT), 2))
        for x in (x0, x1):
            p.drawLine(QPointF(x, track_top), QPointF(x, h))
        # in / out grips - a chunky bracket in the grip strip, offset outward so
        # they don't sit on top of frame 0 / the last frame
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_ACCENT))
        gy0, gy1 = track_top, self._GRIP
        p.drawPolygon(QPolygonF([QPointF(x0, gy0), QPointF(x0 + 9, gy0),
                                 QPointF(x0, gy1)]))                 # in: ▸ at left edge
        p.drawPolygon(QPolygonF([QPointF(x1, gy0), QPointF(x1 - 9, gy0),
                                 QPointF(x1, gy1)]))                 # out: ◂ at right edge

        # ticks + labels (~1 label per 100 px, kept inside the widget)
        total_s = (self._count - 1) / self._fps
        px_per_s = w / max(total_s, 1e-6)
        step = _nice_step(100 / max(px_per_s, 1e-6))
        pen_tick = QPen(QColor(theme.BORDER_HI))
        pen_text = QColor(theme.TEXT_DIM)
        t = 0.0
        while t <= total_s + 1e-6:
            x = self._x(t * self._fps)
            p.setPen(pen_tick)
            p.drawLine(QPointF(x, h - 8), QPointF(x, h))
            m, s = divmod(t, 60)
            lbl = f"{int(m):d}:{s:04.1f}" if step < 1 else f"{int(m):d}:{int(s):02d}"
            p.setPen(pen_text)
            tw = self.fontMetrics().horizontalAdvance(lbl)
            tx = min(max(0.0, x - 1), w - tw - 1)     # clamp so it never clips
            p.drawText(QRectF(tx, 0, tw + 4, _LABEL_BAND),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl)
            t += step

        # playhead
        hx = self._x(self._frame)
        p.setPen(QPen(_PLAYHEAD, 1.5))
        p.drawLine(QPointF(hx, track_top - 4), QPointF(hx, h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_PLAYHEAD)
        p.drawPolygon(QPolygonF([QPointF(hx - 5, track_top - 4),
                                 QPointF(hx + 5, track_top - 4),
                                 QPointF(hx, track_top + 4)]))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        x, y = e.position().x(), e.position().y()
        # only grab an in/out handle from the top grip strip - a click anywhere
        # in the main track scrubs, even right at the ends
        if y <= self._GRIP:
            if abs(x - self._x(self.in_point)) < 12:
                self._drag = "in"
                return
            if abs(x - self._x(self.out_point)) < 12:
                self._drag = "out"
                return
        self._drag = "head"
        self.seek.emit(self._frame_at(x))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self._drag:
            x, y = e.position().x(), e.position().y()
            near = (y <= self._GRIP and
                    (abs(x - self._x(self.in_point)) < 12
                     or abs(x - self._x(self.out_point)) < 12))
            self.setCursor(Qt.CursorShape.SizeHorCursor if near
                           else Qt.CursorShape.PointingHandCursor)
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


# ----------------------------------------------------------------- audio lane
class AudioLane(QWidget):
    changed = Signal()
    _HEADER_W = 132

    def __init__(self, index: int, name: str) -> None:
        super().__init__()
        self.index = index
        self.muted = False
        self.solo = False
        self._pix: QPixmap | None = None
        self.setMinimumHeight(_LANE_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 4, 7, 4)
        lay.setSpacing(5)

        self.btn_m = QPushButton("M")
        self.btn_m.setObjectName("mute")
        self.btn_s = QPushButton("S")
        self.btn_s.setObjectName("solo")
        for b, tip in ((self.btn_m, "Mute this track"), (self.btn_s, "Solo this track")):
            b.setCheckable(True)
            b.setFixedSize(24, 22)
            b.setToolTip(tip)
            b.setStyleSheet(_LANE_BTN_QSS)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_m.toggled.connect(self._on_mute)
        self.btn_s.toggled.connect(self._on_solo)

        self.lbl = QLabel(name)
        self.lbl.setFixedWidth(self._HEADER_W - 24 - 24 - 15)
        self.lbl.setToolTip(name)
        self.lbl.setStyleSheet(f"color:{theme.TEXT}; font-size:11px; font-weight:600;")

        lay.addWidget(self.btn_m)
        lay.addWidget(self.btn_s)
        lay.addWidget(self.lbl)
        lay.addStretch(1)
        self._wave_x = self._HEADER_W

    def _on_mute(self, on: bool) -> None:
        self.muted = on
        self.update()
        self.changed.emit()

    def _on_solo(self, on: bool) -> None:
        self.solo = on
        self.update()
        self.changed.emit()

    def set_waveform(self, path: str) -> None:
        pm = QPixmap(path)
        self._pix = pm if not pm.isNull() else None
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        bg = QColor(theme.SURFACE_2 if self.index % 2 == 0 else theme.SURFACE)
        p.fillRect(self.rect(), bg)
        # header divider
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(self._wave_x - 4, 2, self._wave_x - 4, self.height() - 2)

        wx = self._wave_x
        area = QRectF(wx, 2, self.width() - wx - 4, self.height() - 4)
        if self._pix is not None:
            p.setOpacity(0.28 if self.muted else 0.95)
            p.drawPixmap(area, self._pix, QRectF(self._pix.rect()))
            p.setOpacity(1.0)
        else:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(area, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "  analysing waveform…")
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


# ---------------------------------------------------------------- timeline
class Timeline(QWidget):
    frameChanged = Signal(int)
    inOutChanged = Signal(int, int)
    playingChanged = Signal(bool)
    audioChanged = Signal()          # mute / solo state changed
    playFrom = Signal(float)         # playback (re)started at this many seconds

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
        self._last_ui_sync = 0.0
        self._lanes: list[AudioLane] = []
        self._wave = None

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        self._build()
        self.set_media(0, 30.0)

    def _build(self) -> None:
        self.ruler = TimeRuler()
        self.ruler.seek.connect(self.seek)
        self.ruler.setIn.connect(self._set_in)
        self.ruler.setOut.connect(self._set_out)
        self.cache_bar = CacheBar()

        self._lane_host = QWidget()
        self._lane_lay = QVBoxLayout(self._lane_host)
        self._lane_lay.setContentsMargins(0, 0, 0, 0)
        self._lane_lay.setSpacing(0)
        self._lane_scroll = QScrollArea()
        self._lane_scroll.setWidgetResizable(True)
        self._lane_scroll.setWidget(self._lane_host)
        self._lane_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._lane_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lane_scroll.hide()

        self.btn_play = QPushButton("Play")
        self.btn_play.setObjectName("primary")
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self.set_playing)

        b_prev = QPushButton("|◀")
        b_pf = QPushButton("◀")
        b_nf = QPushButton("▶")
        b_next = QPushButton("▶|")
        b_prev.clicked.connect(lambda: self.seek(self.in_point))
        b_next.clicked.connect(lambda: self.seek(self.out_point))
        b_pf.clicked.connect(lambda: self.seek(self._frame - 1))
        b_nf.clicked.connect(lambda: self.seek(self._frame + 1))
        for b in (b_prev, b_pf, b_nf, b_next):
            b.setFixedWidth(34)

        self.btn_in = QPushButton("[ In")
        self.btn_out = QPushButton("Out ]")
        self.btn_in.setToolTip("Set the in point to the playhead (I)")
        self.btn_out.setToolTip("Set the out point to the playhead (O)")
        self.btn_in.clicked.connect(lambda: self._set_in(self._frame))
        self.btn_out.clicked.connect(lambda: self._set_out(self._frame))

        self.btn_loop = QPushButton("Loop")
        self.btn_loop.setCheckable(True)
        self.btn_loop.toggled.connect(self._set_loop)

        self.lbl = QLabel("00:00;00")
        self.lbl.setStyleSheet(
            f"color:{theme.TEXT}; font-family:Consolas,monospace; font-size:12px;")
        self.lbl_total = QLabel("/ 00:00;00")
        self.lbl_total.setStyleSheet(
            f"color:{theme.TEXT_DIM}; font-family:Consolas,monospace; font-size:12px;")

        row = QHBoxLayout()
        row.setSpacing(4)
        for w in (b_prev, b_pf, self.btn_play, b_nf, b_next):
            row.addWidget(w)
        row.addSpacing(10)
        row.addWidget(self.btn_in)
        row.addWidget(self.btn_out)
        row.addWidget(self.btn_loop)
        row.addStretch(1)
        row.addWidget(self.lbl)
        row.addWidget(self.lbl_total)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 6)
        lay.setSpacing(2)
        lay.addWidget(self.ruler)
        lay.addWidget(self.cache_bar)
        lay.addWidget(self._lane_scroll, 1)     # grows with the panel
        lay.addLayout(row)
        self.setMinimumHeight(92)
        self._sync_height()

    def _sync_height(self) -> None:
        n = len(self._lanes)
        self._lane_scroll.setVisible(n > 0)
        if n == 0:
            self._lane_scroll.setMinimumHeight(0)
            self.setMinimumHeight(92)
            return
        # show up to 3 lanes without scrolling; the left-panel splitter lets
        # the user drag the timeline taller to see (and enlarge) the rest
        floor = min(n, 3) * _LANE_H + 2
        self._lane_scroll.setMinimumHeight(floor)
        self.setMinimumHeight(34 + 4 + floor + 40 + 12)

    # ------------------------------------------------------------- audio
    def set_audio_tracks(self, tracks, source_path: str) -> None:
        """`tracks` is a sequence of media.probe.AudioStreamInfo."""
        for lane in self._lanes:
            lane.setParent(None)
            lane.deleteLater()
        self._lanes = []
        while self._lane_lay.count():
            self._lane_lay.takeAt(0)

        show = list(tracks) if len(tracks) > 1 else []   # single track = no lane clutter
        for tr in show:
            lane = AudioLane(tr.index, f"Track {tr.index + 1}")
            lane.changed.connect(self._on_lane_changed)
            self._lane_lay.addWidget(lane)
            self._lanes.append(lane)
        self._sync_height()

        if self._lanes and source_path:
            from vcomp.media.waveform import WaveformWorker

            if self._wave is None:
                self._wave = WaveformWorker()
                self._wave.ready.connect(self._on_wave_ready)
                self._wave.start()
            self._wave.request(source_path, [l.index for l in self._lanes])

    def _on_wave_ready(self, track: int, png: str) -> None:
        for lane in self._lanes:
            if lane.index == track:
                lane.set_waveform(png)

    def _on_lane_changed(self) -> None:
        self.audioChanged.emit()

    def active_audio_tracks(self) -> list[int]:
        """Audio-stream indices that should be mixed into the export."""
        if not self._lanes:
            return [0]                    # default: first track only
        solo = [l.index for l in self._lanes if l.solo]
        if solo:
            return solo
        return [l.index for l in self._lanes if not l.muted]

    def stop_workers(self) -> None:
        if self._wave is not None:
            self._wave.stop()
            self._wave = None

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

    @property
    def is_playing(self) -> bool:
        return self._timer.isActive()

    def seek(self, index: int) -> None:
        index = max(0, min(int(index), max(0, self._count - 1)))
        if index == self._frame:
            return
        self._frame = index
        now = time.monotonic()
        if not self._timer.isActive() or now - self._last_ui_sync > 0.05:
            self._last_ui_sync = now
            self.ruler.set_frame(index)
            self._update_label()
        self.frameChanged.emit(index)

    def set_playing(self, on: bool) -> None:
        was_active = self._timer.isActive()
        if on and self._count > 1:
            self._play_t0 = time.monotonic()
            self._play_f0 = self._frame if self._frame < self.out_point else self.in_point
            if self._frame >= self.out_point:
                self.seek(self.in_point)
            self._timer.setInterval(max(8, int(1000.0 / (self._fps * 2.0))))
            self._timer.start()
            self.playFrom.emit(self._play_f0 / self._fps)
        else:
            self._timer.stop()
            self.ruler.set_frame(self._frame)
            self._update_label()
        if self.btn_play.isChecked() != on:
            self.btn_play.blockSignals(True)
            self.btn_play.setChecked(on)
            self.btn_play.blockSignals(False)
        self.btn_play.setText("Pause" if on else "Play")
        if bool(on) != was_active:
            self.playingChanged.emit(bool(on and self._count > 1))

    def toggle_play(self) -> None:
        self.set_playing(not self._timer.isActive())

    def set_cache_state(self, warm: set[int]) -> None:
        self.cache_bar.update_state(self._count, warm)

    # ------------------------------------------------------------------ slots
    def _tick(self) -> None:
        elapsed = time.monotonic() - self._play_t0
        target = self._play_f0 + int(elapsed * self._fps)
        if target > self.out_point:
            if self._loop:
                self._play_t0 = time.monotonic()
                self._play_f0 = self.in_point
                target = self.in_point
                self.playFrom.emit(self.in_point / self._fps)
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
        self.lbl.setText(_timecode(self._frame, self._fps))
        self.lbl_total.setText(
            f"/ {_timecode(max(0, self._count - 1), self._fps)}"
            f"   in {self.in_point} · out {self.out_point}")
