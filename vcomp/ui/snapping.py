"""Lightweight snapping helpers, in normalized space."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SnapResult:
    x: float
    y: float
    guides_x: list[float] = field(default_factory=list)   # vertical guide lines
    guides_y: list[float] = field(default_factory=list)   # horizontal guide lines


def snap_scalar(v: float, candidates: list[float], tol: float) -> tuple[float, float | None]:
    best = None
    bd = tol
    for c in candidates:
        d = abs(v - c)
        if d < bd:
            bd, best = d, c
    return (best, best) if best is not None else (v, None)


def snap_point(x: float, y: float, cand_x: list[float], cand_y: list[float],
               tol: float, enabled: bool = True) -> SnapResult:
    if not enabled:
        return SnapResult(x, y)
    sx, gx = snap_scalar(x, cand_x, tol)
    sy, gy = snap_scalar(y, cand_y, tol)
    return SnapResult(sx, sy,
                      [gx] if gx is not None else [],
                      [gy] if gy is not None else [])


def edges(rects: list[tuple[float, float, float, float]]) -> tuple[list[float], list[float]]:
    """Collect x and y edge/centre lines from a list of (x0,y0,x1,y1) rects."""
    xs: list[float] = []
    ys: list[float] = []
    for x0, y0, x1, y1 in rects:
        xs += [x0, x1, (x0 + x1) / 2]
        ys += [y0, y1, (y0 + y1) / 2]
    return xs, ys
