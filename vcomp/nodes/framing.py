"""Framing nodes. M3 ships Main Framing (fit modes + placement + rounded corners
+ feather). Border / shadow params exist but are applied from M4.
"""
from __future__ import annotations

from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_FIT = ("fit_width", "fill", "stretch", "manual")


def _fit_dest(mode: str, canvas_w: int, canvas_h: int, src_w: int, src_h: int,
              pos: tuple[float, float], scale: float) -> tuple[float, float, float, float]:
    ca = canvas_w / canvas_h
    sa = (src_w / src_h) if src_h else ca

    if mode == "stretch":
        return (0.0, 0.0, 1.0, 1.0)
    if mode == "fill":
        # cover the whole canvas, keep aspect (crop handled by srcrect elsewhere)
        return (0.0, 0.0, 1.0, 1.0)
    if mode == "manual":
        w = scale
        h = scale * sa / ca
        cx, cy = pos
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    # fit_width: full width, letterbox band, vertically centred
    band_h = (1.0 / sa) * ca
    y0 = (1.0 - band_h) / 2.0
    return (0.0, y0, 1.0, y0 + band_h)


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
        self.add_param(Param("dest_scale", ParamType.FLOAT, 1.0, min=0.05, max=4.0,
                             step=0.01, group="Placement", accepts_input=True))
        self.add_param(Param("rotation", ParamType.FLOAT, 0.0, min=-180, max=180,
                             group="Placement"))
        self.add_param(Param("pan_x", ParamType.FLOAT, 0.5, min=0.0, max=1.0, group="Placement"))
        self.add_param(Param("pan_y", ParamType.FLOAT, 0.5, min=0.0, max=1.0, group="Placement"))
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

    def band_rect(self, canvas_w: int, canvas_h: int, src_w: int, src_h: int
                  ) -> tuple[float, float, float, float]:
        """Destination quad (x0,y0,x1,y1 canvas [0,1]) - pure, for overlays."""
        return _fit_dest(self.params["fit_mode"].value, canvas_w, canvas_h,
                         src_w or canvas_w, src_h or canvas_h,
                         tuple(self.params["dest_position"].value),
                         float(self.params["dest_scale"].value))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        fbo = ctx.acquire_fbo()
        if src is None:
            fbo.use()
            fbo.clear(0.0, 0.0, 0.0, 0.0)
            return {"image": fbo.color_attachments[0], "dest_rect": (0, 0, 1, 1)}

        cw, ch = ctx.canvas_w, ctx.canvas_h
        sw, sh = src.width, src.height
        mode = self.params["fit_mode"].value
        pos = tuple(self.params["dest_position"].value)
        scale = float(self.p("dest_scale", ctx.t, inputs))
        dest = _fit_dest(mode, cw, ch, sw, sh, pos, scale)

        sr = tuple(self.params["source_rect"].value)  # x,y,w,h -> u0,v0,u1,v1
        srcrect = (sr[0], sr[1], sr[0] + sr[2], sr[1] + sr[3])

        feather_frac = float(self.params["feather"].value) / max(cw, 1)
        radius = float(self.params["corner_radius"].value)

        ctx.compositor.blit(
            fbo, src, dest=dest, srcrect=srcrect,
            feather=feather_frac, radius=radius,
        )
        x0, y0, x1, y1 = dest
        return {"image": fbo.color_attachments[0],
                "dest_rect": (x0, y0, x1 - x0, y1 - y0)}
