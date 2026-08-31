"""Parameter model.

Every node parameter is a :class:`Param`. Evaluation order at time *t*
(spec 4.2):

1. connected input port  -> upstream value
2. else keyframes        -> interpolate at *t*   (full interp arrives in M5)
3. else                  -> static ``value``

Qt-free: the properties panel reads these definitions to build widgets, but the
model itself never imports Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ParamType(str, Enum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STR = "str"
    ENUM = "enum"
    COLOR = "color"      # (r, g, b, a) floats 0..1
    RECT = "rect"        # (x, y, w, h) normalized
    VEC2 = "vec2"        # (x, y)
    FILEPATH = "filepath"


# wire types (spec 4.1)
class WireType(str, Enum):
    IMAGE = "Image"
    NUMBER = "Number"
    COLOR = "Color"
    RECT = "Rect"
    AUDIO = "Audio"


@dataclass
class Keyframe:
    t: float
    value: Any
    interp: str = "linear"   # step | linear | ease | bezier


@dataclass
class Param:
    name: str
    type: ParamType
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    ui_widget: str | None = None
    group: str = "General"
    tooltip: str = ""
    accepts_input: bool = False          # exposes an input port
    input_wire: WireType = WireType.NUMBER

    value: Any = None
    keyframes: list[Keyframe] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.value is None:
            self.value = self.default

    # ------------------------------------------------------------------ eval
    def evaluate(self, t: float, upstream: Callable[[], Any] | None = None) -> Any:
        if upstream is not None:
            return self._coerce(upstream())
        if self.keyframes:
            return self._interp(t)
        return self._coerce(self.value)

    def _interp(self, t: float) -> Any:
        ks = sorted(self.keyframes, key=lambda k: k.t)
        if t <= ks[0].t:
            return self._coerce(ks[0].value)
        if t >= ks[-1].t:
            return self._coerce(ks[-1].value)
        for a, b in zip(ks, ks[1:]):
            if a.t <= t <= b.t:
                if a.interp == "step":
                    return self._coerce(a.value)
                f = (t - a.t) / (b.t - a.t) if b.t > a.t else 0.0
                if a.interp in ("ease", "bezier"):
                    f = f * f * (3.0 - 2.0 * f)  # smoothstep placeholder
                return self._lerp(a.value, b.value, f)
        return self._coerce(ks[-1].value)

    # --------------------------------------------------------------- helpers
    def _lerp(self, a: Any, b: Any, f: float) -> Any:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            v = a + (b - a) * f
            return int(round(v)) if self.type is ParamType.INT else v
        if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
            return tuple(x + (y - x) * f for x, y in zip(a, b))
        return a if f < 0.5 else b

    def _coerce(self, v: Any) -> Any:
        try:
            if self.type is ParamType.FLOAT:
                v = float(v)
            elif self.type is ParamType.INT:
                v = int(round(float(v)))
            elif self.type is ParamType.BOOL:
                v = bool(v)
        except (TypeError, ValueError):
            return self.default
        if self.type in (ParamType.FLOAT, ParamType.INT) and v is not None:
            if self.min is not None:
                v = max(self.min, v)
            if self.max is not None:
                v = min(self.max, v)
        return v

    def set(self, v: Any) -> None:
        self.value = self._coerce(v)

    def snapshot(self) -> dict:
        return {
            "value": list(self.value) if isinstance(self.value, (tuple, list)) else self.value,
            "keyframes": [(k.t, k.value, k.interp) for k in self.keyframes],
        }

    def restore(self, data: dict) -> None:
        if "value" in data:
            self.value = tuple(data["value"]) if isinstance(data["value"], list) else data["value"]
        self.keyframes = [Keyframe(t, val, interp) for t, val, interp in data.get("keyframes", [])]
