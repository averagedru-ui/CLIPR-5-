"""Text node. The node stays Qt-free; rasterization is delegated to
``render.text_raster`` (which uses QPainter) via the eval context.
"""
from __future__ import annotations

from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register


@register
class Text(VNode):
    type_name = "Text"
    category = "Modify"
    title_default = "Text"
    color = (120, 100, 140)

    def _define(self) -> None:
        self.add_param(Param("content", ParamType.STR, "TEXT", group="Text"))
        self.add_param(Param("font_family", ParamType.STR, "Arial", group="Text"))
        self.add_param(Param("font_size", ParamType.INT, 96, min=4, max=800, group="Text"))
        self.add_param(Param("weight", ParamType.INT, 700, min=100, max=900, step=100, group="Text"))
        self.add_param(Param("color", ParamType.COLOR, (1, 1, 1, 1), group="Text"))
        self.add_param(Param("align", ParamType.ENUM, "center",
                             choices=("left", "center", "right"), group="Text"))
        self.add_param(Param("dest_x", ParamType.FLOAT, 0.5, min=-0.5, max=1.5, step=0.005,
                             group="Placement"))
        self.add_param(Param("dest_y", ParamType.FLOAT, 0.5, min=-0.5, max=1.5, step=0.005,
                             group="Placement"))
        self.add_param(Param("letter_spacing", ParamType.FLOAT, 0.0, min=-20, max=40, group="Text"))
        self.add_param(Param("line_height", ParamType.FLOAT, 1.2, min=0.5, max=3.0, step=0.05,
                             group="Text"))
        self.add_param(Param("stroke_width", ParamType.FLOAT, 0.0, min=0, max=20, group="Text"))
        self.add_param(Param("stroke_color", ParamType.COLOR, (0, 0, 0, 1), group="Text"))
        self.add_output("image", WireType.IMAGE)

        self._cache_key = None
        self._raster = None

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        from vcomp.render.text_raster import render_text

        key = tuple(p.value for p in self.params.values())
        if key != self._cache_key:
            self._cache_key = key
            self._raster = render_text(
                str(self.params["content"].value),
                width=ctx.canvas_w, height=ctx.canvas_h,
                font_family=self.params["font_family"].value,
                font_size=self.params["font_size"].value,
                weight=self.params["weight"].value,
                color=tuple(self.params["color"].value),
                align=self.params["align"].value,
                letter_spacing=self.params["letter_spacing"].value,
                line_height=self.params["line_height"].value,
                stroke_width=self.params["stroke_width"].value,
                stroke_color=tuple(self.params["stroke_color"].value),
            )
        f = ctx.acquire_fbo()
        if self._raster is None:
            f.use()
            f.clear(0, 0, 0, 0)
            return {"image": f.color_attachments[0]}
        tex = ctx.upload(self._raster)
        dx = float(self.params["dest_x"].value) - 0.5
        dy = float(self.params["dest_y"].value) - 0.5
        ctx.compositor.sample(f, tex, translate=(dx, dy), anchor=(0.5, 0.5), fit=0)
        return {"image": f.color_attachments[0]}
