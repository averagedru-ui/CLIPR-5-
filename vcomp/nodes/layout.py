"""Facecam and Bar Layout nodes."""
from __future__ import annotations

from typing import Any

import numpy as np

from vcomp.core import coords
from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_FC_SHAPE = {"rect": 0, "rounded": 1, "circle": 2}
_FC_PLACE = ("custom", "top-left", "top-right", "bottom-left", "bottom-right",
             "top-center", "bottom-center")


@register
class Facecam(VNode):
    """Webcam / facecam overlay lifted from a stream recording's picture-in-
    picture box and re-placed on the vertical canvas. Enable/disable the node to
    toggle it; ``placement`` snaps it to a corner or edge automatically."""
    type_name = "Facecam"
    category = "Framing"
    title_default = "Facecam"
    color = (150, 120, 110)

    def _define(self) -> None:
        self.add_input("image", WireType.IMAGE)
        self.add_param(Param("source_rect", ParamType.RECT, (0.0, 0.72, 0.22, 0.28),
                             group="Source",
                             tooltip="The webcam box inside the source frame."))
        self.add_param(Param("shape", ParamType.ENUM, "rounded", choices=tuple(_FC_SHAPE), group="Source"))
        self.add_param(Param("placement", ParamType.ENUM, "top-right", choices=_FC_PLACE,
                             group="Placement",
                             tooltip="Auto-snap to a spot on the 9:16; 'custom' uses dest_x/y."))
        self.add_param(Param("margin", ParamType.FLOAT, 0.03, min=0.0, max=0.4, step=0.005,
                             group="Placement", tooltip="Gap from the canvas edge for presets."))
        self.add_param(Param("dest_x", ParamType.FLOAT, 0.82, min=-0.5, max=1.5, step=0.005, group="Placement"))
        self.add_param(Param("dest_y", ParamType.FLOAT, 0.12, min=-0.5, max=1.5, step=0.005, group="Placement"))
        self.add_param(Param("size", ParamType.FLOAT, 0.34, min=0.02, max=1.0, step=0.01, group="Placement"))
        self.add_param(Param("border_width", ParamType.FLOAT, 3.0, min=0, max=40, group="Style"))
        self.add_param(Param("border_color", ParamType.COLOR, (1, 1, 1, 1), group="Style"))
        self.add_param(Param("feather", ParamType.FLOAT, 1.5, min=0, max=64, group="Style"))
        self.add_param(Param("opacity", ParamType.FLOAT, 1.0, min=0, max=1, step=0.01, group="Style"))
        self.add_param(Param("corner_radius", ParamType.FLOAT, 0.15, min=0, max=0.5, step=0.01, group="Style"))
        self.add_output("image", WireType.IMAGE)

    def is_time_dependent(self) -> bool:
        return True

    def dest_center(self, dw: float, dh: float) -> tuple[float, float]:
        place = self.params["placement"].value
        if place == "custom":
            return float(self.params["dest_x"].value), float(self.params["dest_y"].value)
        m = float(self.params["margin"].value)
        left = m + dw / 2
        right = 1.0 - m - dw / 2
        top = m + dh / 2
        bot = 1.0 - m - dh / 2
        return {
            "top-left": (left, top), "top-right": (right, top),
            "bottom-left": (left, bot), "bottom-right": (right, bot),
            "top-center": (0.5, top), "bottom-center": (0.5, bot),
        }.get(place, (0.5, top))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        f = ctx.acquire_fbo()
        if src is None:
            f.use()
            f.clear(0, 0, 0, 0)
            return {"image": f.color_attachments[0]}

        sx, sy, sw, sh = self.params["source_rect"].value
        srcrect = (sx, sy, sx + sw, sy + sh)
        shape = _FC_SHAPE.get(self.params["shape"].value, 1)
        gl_shape = {0: 0, 1: 1, 2: 2}[shape]
        size = float(self.params["size"].value)
        aspect = (sw * src.width) / max(1e-6, sh * src.height)   # box pixel w/h
        dw = size
        dh = size * (ctx.canvas_w / ctx.canvas_h) / max(1e-6, aspect)

        cx, cy = self.dest_center(dw, dh)
        dest = (cx - dw / 2, cy - dh / 2, cx + dw / 2, cy + dh / 2)

        ctx.compositor.region(
            f, src, dest=dest, srcrect=srcrect, shape=gl_shape,
            radii=(self.params["corner_radius"].value,) * 4,
            feather=float(self.params["feather"].value) / ctx.canvas_w,
            expand=0.0, rotation=0.0, opacity=float(self.params["opacity"].value),
            outline_w=float(self.params["border_width"].value) / ctx.canvas_w,
            outline_color=tuple(self.params["border_color"].value),
        )
        return {"image": f.color_attachments[0]}


@register
class BarLayout(VNode):
    type_name = "Bar Layout"
    category = "Framing"
    title_default = "Bar Layout"
    color = (120, 130, 150)

    def _define(self) -> None:
        self.add_input("items", WireType.IMAGE, multi=True)
        self.add_param(Param("band_rect", ParamType.RECT, (0.05, 0.02, 0.9, 0.12), group="Band"))
        self.add_param(Param("direction", ParamType.ENUM, "row", choices=("row", "column"),
                             group="Band"))
        self.add_param(Param("align", ParamType.ENUM, "space-between",
                             choices=("start", "center", "end", "space-between"), group="Band"))
        self.add_param(Param("gap", ParamType.FLOAT, 0.02, min=0, max=0.5, step=0.005, group="Band"))
        self.add_param(Param("item_scale", ParamType.FLOAT, 1.0, min=0.1, max=4, step=0.01, group="Band"))
        self.add_param(Param("uniform_scale", ParamType.BOOL, True, group="Band"))
        self.add_param(Param("padding", ParamType.FLOAT, 0.01, min=0, max=0.2, step=0.005, group="Band"))
        self.add_output("image", WireType.IMAGE)

    def is_time_dependent(self) -> bool:
        return True

    def _centroid(self, ctx, tex) -> tuple[float, float]:
        small = ctx.acquire_fbo(48, 48)
        ctx.compositor.sample(small, tex, fit=3)
        arr = ctx.compositor.to_numpy(small)
        a = arr[..., 3].astype(np.float32)
        s = a.sum()
        if s < 1e-3:
            return (0.5, 0.5)
        ys, xs = np.mgrid[0:48, 0:48]
        return (float((xs * a).sum() / s) / 48.0, float((ys * a).sum() / s) / 48.0)

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        items = [t for t in (inputs.get("items") or []) if t is not None]
        out = ctx.acquire_fbo()
        out.use()
        out.clear(0, 0, 0, 0)
        if not items:
            return {"image": out.color_attachments[0]}

        bx, by, bw, bh = self.params["band_rect"].value
        pad = float(self.params["padding"].value)
        gap = float(self.params["gap"].value)
        row = self.params["direction"].value == "row"
        n = len(items)

        inner0 = (bx + pad, by + pad) if row else (bx + pad, by + pad)
        span = (bw - 2 * pad) if row else (bh - 2 * pad)
        slot = (span - gap * (n - 1)) / n if n else span

        align = self.params["align"].value
        if align == "space-between" and n > 1:
            step = (span - slot) / (n - 1)
            starts = [(inner0[0 if row else 1]) + i * step for i in range(n)]
        else:
            block = slot * n + gap * (n - 1)
            base = inner0[0 if row else 1]
            if align == "center":
                base += (span - block) / 2
            elif align == "end":
                base += (span - block)
            starts = [base + i * (slot + gap) for i in range(n)]

        acc = out.color_attachments[0]
        for tex, s0 in zip(items, starts):
            cx0, cy0 = self._centroid(ctx, tex)
            if row:
                tx = (s0 + slot / 2) - cx0
                ty = (by + bh / 2) - cy0
            else:
                tx = (bx + bw / 2) - cx0
                ty = (s0 + slot / 2) - cy0
            shifted = ctx.acquire_fbo()
            ctx.compositor.sample(shifted, tex, translate=(tx, ty), anchor=(0.5, 0.5), fit=0)
            merged = ctx.acquire_fbo()
            ctx.compositor.compose(merged, acc, shifted.color_attachments[0])
            acc = merged.color_attachments[0]

        return {"image": acc}
