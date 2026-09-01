"""Reusable property widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QSlider, QWidget

_TICKS = 1000


class ScrubSlider(QWidget):
    """Horizontal slider + numeric field bound to a ``[minimum, maximum]`` range.

    Emits ``valueChanged(float)`` while dragging and on spin-box edits. Used for
    every ranged float / int parameter so position, size, rotation, skew, etc.
    are all drag-scrubbable.
    """

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, value: float,
                 step: float = 0.0, decimals: int = 3, integer: bool = False) -> None:
        super().__init__()
        self._min = float(minimum)
        self._max = float(maximum) if maximum > minimum else minimum + 1.0
        self._integer = integer
        self._guard = False

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _TICKS)
        self.slider.valueChanged.connect(self._from_slider)

        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(0 if integer else decimals)
        self.spin.setRange(self._min, self._max)
        self.spin.setSingleStep(step or ((self._max - self._min) / 100.0))
        self.spin.setKeyboardTracking(False)
        self.spin.valueChanged.connect(self._from_spin)
        self.spin.setFixedWidth(84)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin, 0)

        self.set_value(value)

    # ------------------------------------------------------------------ API
    def set_value(self, v: float) -> None:
        v = max(self._min, min(self._max, float(v)))
        self._guard = True
        self.spin.setValue(v)
        self.slider.setValue(self._to_tick(v))
        self._guard = False

    def value(self) -> float:
        return round(self.spin.value()) if self._integer else self.spin.value()

    # -------------------------------------------------------------- internal
    def _to_tick(self, v: float) -> int:
        return int(round((v - self._min) / (self._max - self._min) * _TICKS))

    def _to_value(self, tick: int) -> float:
        v = self._min + (tick / _TICKS) * (self._max - self._min)
        return round(v) if self._integer else v

    def _from_slider(self, tick: int) -> None:
        if self._guard:
            return
        v = self._to_value(tick)
        self._guard = True
        self.spin.setValue(v)
        self._guard = False
        self.valueChanged.emit(v)

    def _from_spin(self, v: float) -> None:
        if self._guard:
            return
        self._guard = True
        self.slider.setValue(self._to_tick(v))
        self._guard = False
        self.valueChanged.emit(self.value())
