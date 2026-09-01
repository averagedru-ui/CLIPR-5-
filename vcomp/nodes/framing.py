"""Framing nodes.

Main Framing places the gameplay view on the vertical canvas. Scaling it up lets
the source overflow the canvas edges (cropped, not squished); ``pan_x/pan_y``
choose which part stays visible when it overflows.
"""
from __future__ import annotations

import math
from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_FIT = ("fit_width", "fill", "stretch", "manual")


def _fit_dest(mode: str, canvas_w: int, canvas_h: int, src_w: int, src_h: int,
              pos: tuple[float, float], scale: float,
              scale_x: float = 1.0, scale_y: float = 1.0,
              pan_x: float = 0.5, pan_y: float = 0.5
              ) -> tuple[float, float, float, float]:
    """Destination quad in canvas [0,1]. May extend past [0,1] - the compositor
    only draws the on-canvas part, so oversized content is cropped by the frame
    rather than squashed into it."""
    ca = canvas_w / canvas_h                 # ~0.5625 for 1080x1920
    sa = (src_w / src_h) if src_h else ca    # ~1.78 for 16:9

    if mode == "stretch":
        bw, bh = 1.0, 1.0
    elif mode == "fill":
        # cover: fill the canvas, overflow the long axis
        if sa > ca:
            bh, bw = 1.0, sa / ca
        else:
            bw, bh = 1.0, ca / sa
    else:
        # fit_width / manual: full-width letterbox band
        bw = 1.0
        bh = ca / sa

    bw *= scale * scale_x
    bh *= scale * scale_y

    if mode == "manual":
        cx, cy = pos
    else:
        cx, cy = 0.5, 0.5

    # when a dimension overflows, pan slides which part is visible
    cx += (0.5 - pan_x) * max(0.0, bw - 1.0)
    cy += (0.5 - pan_y) * max(0.0, bh - 1.0)

    return (cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)


@register
class MainFraming(VNode):
    type_name = "Main Framing"
    category = "Framing"
    title_default = "Main Framing"
    color = (110, 90, 140)

    def _define(self) -> None:
        self.add_param(Param("source_rect", ParamType.RECT, (0.0, 0.0, 1.0, 1.0),
                             group="Source", tooltip="Sub-rect of the source frame to use."))
        self.add_param(Param("fit_mode", ParamType.ENUM, "fit_width", choices=_FIT,
                             group="Placement"))
        self.add_param(Param("dest_position", ParamType.VEC2, (0.5, 0.5),
                             group="Placement", tooltip="Centre, canvas coords (manual fit)."))
        self.add_param(Param("dest_scale", ParamType.FLOAT, 1.0, min=0.05, max=6.0,
                             step=0.01, group="Placement", accepts_input=True,
                             tooltip="Scale up to overflow the frame edges (no squish)."))
        self.add_param(Param("dest_scale_x", ParamType.FLOAT, 1.0, min=0.05, max=6.0,
                             step=0.01, group="Placement"))
        self.add_param(Param("dest_scale_y", ParamType.FLOAT, 1.0, min=0.05, max=6.0,
                             step=0.01, group="Placement"))
        self.add_param(Param("rotation", ParamType.FLOAT, 0.0, min=-180, max=180,
                             step=0.5, group="Placement"))
        self.add_param(Param("skew_x", ParamType.FLOAT, 0.0, min=-1.0, max=1.0,
                             step=0.01, group="Placement"))
        self.add_param(Param("skew_y", ParamType.FLOAT, 0.0, min=-1.0, max=1.0,
                             step=0.01, group="Placement"))
        self.add_param(Param("pan_x", ParamType.FLOAT, 0.5, min=0.0, max=1.0,
                             step=0.005, group="Placement"))
        self.add_param(Param("pan_y", ParamType.FLOAT, 0.5, min=0.0, max=1.0,
                             step=0.005, group="Placement"))
        self.add_param(Param("corner_radius", ParamType.FLOAT, 0.0, min=0.0, max=0.5,
                             step=0.005, group="Edge"))
        self.add_param(Param("feather", ParamType.FLOAT, 0.0, min=0.0, max=64.0,
                             step=0.5, group="Edge", tooltip="Edge softness in canvas px."))
        self.add_param(Param("border_width", ParamType.FLOAT, 0.0, min=0.0, max=40.0,
                             group="Style"))
        self.add_param(Param("border_color", ParamType.COLOR, (1, 1, 1, 1), group="Style"))
        self.add_param(Param("shadow_enabled", ParamType.BOOL, False, group="Style"))

        self.add_input("image", WireType.IMAGE)
        self.add_output("image", WireType.IMAGE)
        self.add_output("dest_rect", WireType.RECT)

    def _dest_args(self) -> dict:
        return dict(
            pos=tuple(self.params["dest_position"].value),
            scale=float(self.params["dest_scale"].value),
            scale_x=float(self.params["dest_scale_x"].value),
            scale_y=float(self.params["dest_scale_y"].value),
            pan_x=float(self.params["pan_x"].value),
            pan_y=float(self.params["pan_y"].value),
        )

    def band_rect(self, canvas_w: int, canvas_h: int, src_w: int, src_h: int
                  ) -> tuple[float, float, float, float]:
        return _fit_dest(self.params["fit_mode"].value, canvas_w, canvas_h,
                         src_w or canvas_w, src_h or canvas_h, **self._dest_args())

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        fbo = ctx.acquire_fbo()
        if src is None:
            fbo.use()
            fbo.clear(0.0, 0.0, 0.0, 0.0)
            return {"image": fbo.color_attachments[0], "dest_rect": (0, 0, 1, 1)}

        cw, ch = ctx.canvas_w, ctx.canvas_h
        sw, sh = src.width, src.height
        args = self._dest_args()
        args["scale"] = float(self.p("dest_scale", ctx.t, inputs))
        dest = _fit_dest(self.params["fit_mode"].value, cw, ch, sw, sh, **args)

        sr = tuple(self.params["source_rect"].value)
        srcrect = (sr[0], sr[1], sr[0] + sr[2], sr[1] + sr[3])

        ctx.compositor.blit(
            fbo, src, dest=dest, srcrect=srcrect,
            feather=float(self.params["feather"].value) / max(cw, 1),
            radius=float(self.params["corner_radius"].value),
            rotation=math.radians(float(self.params["rotation"].value)),
            skew=(float(self.params["skew_x"].value), float(self.params["skew_y"].value)),
        )
        x0, y0, x1, y1 = dest
        return {"image": fbo.color_attachments[0],
                "dest_rect": (x0, y0, x1 - x0, y1 - y0)}
