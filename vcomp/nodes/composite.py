"""Composite / output nodes."""
from __future__ import annotations

from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.render.blend import BlendMode
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register


@register
class Stack(VNode):
    type_name = "Stack"
    category = "Composite"
    title_default = "Stack"
    color = (100, 100, 115)

    def _define(self) -> None:
        self.add_input("layers", WireType.IMAGE, multi=True)
        self.add_output("image", WireType.IMAGE)
        # per-layer opacity/blend rows: simple parallel lists, index = layer order
        self.add_param(Param("opacities", ParamType.STR, "", group="Layers",
                             tooltip="Internal: comma list of per-layer opacity."))
        self.add_param(Param("blends", ParamType.STR, "", group="Layers",
                             tooltip="Internal: comma list of per-layer blend mode names."))

    def _rows(self, n: int) -> tuple[list[float], list[BlendMode]]:
        ops = [x for x in str(self.params["opacities"].value).split(",") if x != ""]
        bls = [x for x in str(self.params["blends"].value).split(",") if x != ""]
        op = [float(ops[i]) if i < len(ops) else 1.0 for i in range(n)]
        bl = []
        for i in range(n):
            try:
                bl.append(BlendMode.from_name(bls[i]) if i < len(bls) else BlendMode.NORMAL)
            except (KeyError, ValueError):
                bl.append(BlendMode.NORMAL)
        return op, bl

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        layers = [t for t in (inputs.get("layers") or []) if t is not None]
        if not layers:
            fbo = ctx.acquire_fbo()
            fbo.use()
            fbo.clear(0.0, 0.0, 0.0, 0.0)
            return {"image": fbo.color_attachments[0]}

        ops, bls = self._rows(len(layers))
        acc = layers[0]
        for i in range(1, len(layers)):
            dst = ctx.acquire_fbo()
            ctx.compositor.compose(dst, acc, layers[i],
                                   opacity=ops[i], blend=bls[i])
            acc = dst.color_attachments[0]
        return {"image": acc}


@register
class OutputNode(VNode):
    type_name = "Output"
    category = "Composite"
    title_default = "Output"
    color = (150, 70, 70)
    max_instances = 1
    deletable = False

    def _define(self) -> None:
        self.add_param(Param("canvas_width", ParamType.INT, 1080, min=16, max=8192, group="Canvas"))
        self.add_param(Param("canvas_height", ParamType.INT, 1920, min=16, max=8192, group="Canvas"))
        self.add_param(Param("fps", ParamType.ENUM, "30", choices=("30", "60", "source"),
                             group="Canvas"))
        self.add_param(Param("background_clear_color", ParamType.COLOR, (0, 0, 0, 1),
                             group="Canvas"))
        self.add_param(Param("render_scale", ParamType.FLOAT, 2.0, min=1.0, max=2.0,
                             step=0.5, group="Canvas",
                             tooltip="Supersample factor; export defaults to 2x."))
        self.add_input("image", WireType.IMAGE)
        self.add_input("audio", WireType.AUDIO)

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        img = inputs.get("image")
        clear = tuple(self.params["background_clear_color"].value)

        bg = ctx.acquire_fbo()
        ctx.compositor.fill_solid(bg, clear)
        if img is None:
            return {"result": ctx.compositor.to_numpy(bg)}

        out = ctx.acquire_fbo()
        ctx.compositor.compose(out, bg.color_attachments[0], img)
        result = ctx.compositor.to_numpy(out)

        # downsample supersampled render back to canvas resolution
        if ctx.render_scale != 1.0:
            from vcomp.render.compositor import _resize_nn

            result = _resize_nn(result, ctx.canvas_w, ctx.canvas_h)
        return {"result": result, "audio": inputs.get("audio")}
