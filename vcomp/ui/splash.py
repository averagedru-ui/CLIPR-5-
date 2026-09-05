"""Startup splash screen: typewriter title, subtitle, animated progress bar.

Ported from the CLIPR Studio web build's ``splash-screen.tsx`` (React) to plain
Qt widgets/timers - same beats (type "CLIPR" -> "STUDIO" tagline -> progress
0-100 -> fade out), recolored to this app's forest-green palette instead of
the original's lime accent.
"""
from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

_BG = "#0c0c10"
_GLOW = "#7fd9a0"          # bright tint of the app's forest-green accent
_TEXT_DIM = "rgba(255,255,255,70)"
_TITLE = "CLIPR"
_SUBTITLE = "STUDIO"

# The app applies a global QWidget{background:...} stylesheet; without this,
# every plain QWidget container here (row/box wrappers) paints that opaque
# color and shows up as a hard rectangular band over the custom-painted glow.
_TRANSPARENT_QSS = "QWidget { background: transparent; }"


class _ProgressBar(QWidget):
    """A thin rounded bar; ``value`` (0..100) is an animatable Qt property."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(3)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = v
        self.update()

    value = Property(float, _get_value, _set_value)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(r, 1, 1)
        w = r.width() * (self._value / 100.0)
        if w > 0:
            p.setBrush(QColor(_GLOW))
            p.drawRoundedRect(QRectF(0, 0, w, r.height()), 1, 1)


class _Cursor(QWidget):
    """Blinking type-caret: a slim solid bar, not a text glyph."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 82)
        self._on = True
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._blink)

    def start_blink(self) -> None:
        self._on = True
        self.update()
        self._timer.start(500)

    def stop_blink(self) -> None:
        self._timer.stop()
        self.hide()

    def _blink(self) -> None:
        self._on = not self._on
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        if not self._on:
            return
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_GLOW))
        p.drawRect(self.rect())


class SplashScreen(QWidget):
    """Frameless splash window. Call :meth:`start` once shown to play the
    typewriter/progress sequence, then :attr:`finished` fires."""

    finished = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setFixedSize(760, 440)
        self.setStyleSheet(_TRANSPARENT_QSS)
        self._center_on_screen()
        self._build()
        self._char_i = 0

    # ------------------------------------------------------------------ ui
    def _center_on_screen(self) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                     geo.center().y() - self.height() // 2)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addStretch(1)

        title_row = QWidget(self)
        tr_lay = QHBoxLayout(title_row)
        tr_lay.setContentsMargins(0, 0, 0, 0)
        tr_lay.setSpacing(6)
        tr_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # NOTE: the app applies a global `QWidget { font-size: 12px }` stylesheet
        # (theme.py). Once ANY stylesheet is active, Qt's CSS cascade overrides
        # plain widget.setFont() calls for properties the sheet also sets - so
        # font-size/family/weight here MUST be set via each label's own
        # stylesheet (widget-level QSS beats app-level QSS), not QFont alone.
        self.title = QLabel("", title_row)
        self.title.setStyleSheet(
            "color: white; background: transparent;"
            "font-family: 'Segoe UI', sans-serif; font-size: 92px; font-weight: 900;")
        tr_lay.addWidget(self.title)

        self.cursor = _Cursor(title_row)
        tr_lay.addWidget(self.cursor, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(title_row)

        self.subtitle = QLabel(" ".join(_SUBTITLE), self)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setStyleSheet(
            f"color: {_TEXT_DIM}; background: transparent;"
            "font-family: Consolas, monospace; font-size: 15px;")
        self._sub_fx = QGraphicsOpacityEffect(self.subtitle)
        self._sub_fx.setOpacity(0.0)
        self.subtitle.setGraphicsEffect(self._sub_fx)
        root.addSpacing(14)
        root.addWidget(self.subtitle)

        self._progress_box = QWidget(self)
        pb_lay = QVBoxLayout(self._progress_box)
        pb_lay.setContentsMargins(0, 0, 0, 0)
        pb_lay.setSpacing(12)
        self.bar = _ProgressBar(self._progress_box)
        pb_lay.addWidget(self.bar)

        row = QWidget(self._progress_box)
        row_lay = QHBoxLayout(row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        _row_font_qss = "font-family: Consolas, monospace; font-size: 11px;"
        self.lbl_stage = QLabel("INITIALIZING ENGINE", row)
        self.lbl_stage.setStyleSheet(f"color: {_TEXT_DIM}; background: transparent; {_row_font_qss}")
        self.lbl_pct = QLabel("0%", row)
        self.lbl_pct.setStyleSheet(f"color: {_GLOW}; background: transparent; {_row_font_qss}")
        row_lay.addWidget(self.lbl_stage)
        row_lay.addStretch(1)
        row_lay.addWidget(self.lbl_pct)
        pb_lay.addWidget(row)

        self._progress_box.setFixedWidth(440)
        self._prog_fx = QGraphicsOpacityEffect(self._progress_box)
        self._prog_fx.setOpacity(0.0)
        self._progress_box.setGraphicsEffect(self._prog_fx)

        wrap = QWidget(self)
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        wrap_lay.addWidget(self._progress_box)
        root.addSpacing(48)
        root.addWidget(wrap)
        root.addStretch(1)

    # --------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(_BG))

        g = QRadialGradient(self.width() * 0.5, self.height() * 0.5, self.width() * 0.55)
        c0 = QColor(_GLOW)
        c0.setAlpha(26)
        c1 = QColor(_GLOW)
        c1.setAlpha(0)
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRect(self.rect())

    # ----------------------------------------------------------- sequence
    def start(self) -> None:
        """Kick off the type -> subtitle -> progress -> fade sequence."""
        self._char_i = 0
        self.cursor.start_blink()
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_step)
        self._type_timer.start(130)

    def _type_step(self) -> None:
        self._char_i += 1
        self.title.setText(_TITLE[: self._char_i])
        if self._char_i >= len(_TITLE):
            self._type_timer.stop()
            self.cursor.stop_blink()
            QTimer.singleShot(300, self._show_subtitle)
            QTimer.singleShot(900, self._show_progress)

    def _fade_in(self, effect: QGraphicsOpacityEffect) -> None:
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(450)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._keep(anim)

    def _show_subtitle(self) -> None:
        self._fade_in(self._sub_fx)

    def _show_progress(self) -> None:
        self._fade_in(self._prog_fx)
        anim = QPropertyAnimation(self.bar, b"value", self)
        anim.setDuration(2000)
        anim.setStartValue(0.0)
        anim.setEndValue(100.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self.lbl_pct.setText(f"{int(round(v))}%"))
        anim.finished.connect(self._on_progress_done)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._keep(anim)

    def _on_progress_done(self) -> None:
        QTimer.singleShot(300, self._fade_out)

    def _fade_out(self) -> None:
        # Fade the whole top-level window via windowOpacity (compositor-level)
        # rather than a QGraphicsOpacityEffect on self - the latter re-rasterizes
        # this widget's custom-painted background through an offscreen buffer
        # and fights with the plain-QWidget children for the same pixels.
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(500)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(self.finished.emit)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._keep(anim)

    def _keep(self, obj) -> None:
        """Anonymous QPropertyAnimations get garbage-collected mid-flight
        unless something holds a ref; stash on self until they finish."""
        holder = getattr(self, "_anims", None)
        if holder is None:
            holder = []
            self._anims = holder
        holder.append(obj)
        obj.finished.connect(lambda: holder.remove(obj) if obj in holder else None)
