"""Background generator nodes. All output a full-canvas Image."""
from __future__ import annotations

from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register


@register
class SolidBackground(VNode):
    type_name = "Solid Background"
    category = "Background"
    title_default = "Solid Background"
    color = (60, 90, 130)

    def _define(self) -> None:
        self.add_param(Param("color", ParamType.COLOR, (0.08, 0.08, 0.10, 1.0),
                             accepts_input=True, input_wire=WireType.COLOR,
                             tooltip="Fill colour for the whole 9:16 canvas."))
        self.add_output("image", WireType.IMAGE)

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        color = self.p("color", ctx.t, inputs)
        fbo = ctx.acquire_fbo()
        ctx.compositor.fill_solid(fbo, color)
        return {"image": fbo.color_attachments[0]}
