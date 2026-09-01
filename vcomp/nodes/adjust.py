"""Modifier nodes: Transform, Color Adjust, Blur, Key, Opacity.

All are Image -> Image and pass their input straight through when disabled.
"""
from __future__ import annotations

import math
from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_KEY_MODE = {"none": 0, "luma": 1, "chroma": 2}
_BLUR_TYPE = {"gaussian": 0, "box": 1, "directional": 2, "radial": 3}


class _Modifier(VNode):
    category = "Modify"
    bypass_when_disabled = True

    def _io(self) -> None:
        self.add_input("image", WireType.IMAGE)
        self.add_output("image", WireType.IMAGE)

    def _empty(self, ctx):
        f = ctx.acquire_fbo()
        f.use()
        f.clear(0, 0, 0, 0)
        return {"image": f.color_attachments[0]}


@register
class Transform(_Modifier):
    type_name = "Transform"
    title_default = "Transform"
    color = (100, 120, 120)

    def _define(self) -> None:
        self._io()
        self.add_param(Param("translate_x", ParamType.FLOAT, 0.0, min=-1, max=1, step=0.005,
                             group="Transform", accepts_input=True))
        self.add_param(Param("translate_y", ParamType.FLOAT, 0.0, min=-1, max=1, step=0.005,
                             group="Transform", accepts_input=True))
        self.add_param(Param("scale_x", ParamType.FLOAT, 1.0, min=0.02, max=8, step=0.01, group="Transform"))
        self.add_param(Param("scale_y", ParamType.FLOAT, 1.0, min=0.02, max=8, step=0.01, group="Transform"))
        self.add_param(Param("rotation", ParamType.FLOAT, 0.0, min=-180, max=180, group="Transform",
                             accepts_input=True))
        self.add_param(Param("skew_x", ParamType.FLOAT, 0.0, min=-1.0, max=1.0, step=0.01,
                             group="Transform"))
        self.add_param(Param("skew_y", ParamType.FLOAT, 0.0, min=-1.0, max=1.0, step=0.01,
                             group="Transform"))
        self.add_param(Param("anchor_x", ParamType.FLOAT, 0.5, min=0, max=1, step=0.01,
                             group="Transform"))
        self.add_param(Param("anchor_y", ParamType.FLOAT, 0.5, min=0, max=1, step=0.01,
                             group="Transform"))
        self.add_param(Param("resample", ParamType.ENUM, "bilinear",
                             choices=("bilinear", "bicubic", "lanczos"), group="Transform"))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        if src is None:
            return self._empty(ctx)
        f = ctx.acquire_fbo()
        ctx.compositor.sample(
            f, src,
            translate=(self.p("translate_x", ctx.t, inputs), self.p("translate_y", ctx.t, inputs)),
            scale=(self.params["scale_x"].value, self.params["scale_y"].value),
            rotation=math.radians(self.p("rotation", ctx.t, inputs)),
            anchor=(self.params["anchor_x"].value, self.params["anchor_y"].value),
            skew=(self.params["skew_x"].value, self.params["skew_y"].value),
            fit=0, opacity=1.0,
        )
        return {"image": f.color_attachments[0]}


@register
class ColorAdjust(_Modifier):
    type_name = "Color Adjust"
    title_default = "Color Adjust"
    color = (130, 110, 90)

    def _define(self) -> None:
        self._io()
        g = "Adjust"
        self.add_param(Param("exposure", ParamType.FLOAT, 0.0, min=-4, max=4, step=0.05, group=g))
        self.add_param(Param("contrast", ParamType.FLOAT, 1.0, min=0, max=3, step=0.01, group=g))
        self.add_param(Param("saturation", ParamType.FLOAT, 1.0, min=0, max=3, step=0.01, group=g))
        self.add_param(Param("temperature", ParamType.FLOAT, 0.0, min=-1, max=1, step=0.01, group=g))
        self.add_param(Param("tint", ParamType.FLOAT, 0.0, min=-1, max=1, step=0.01, group=g))
        self.add_param(Param("hue_shift", ParamType.FLOAT, 0.0, min=-180, max=180, group=g))
        self.add_param(Param("lift", ParamType.RECT, (0.0, 0.0, 0.0, 0.0), group="Wheels",
                             tooltip="RGB lift (4th value ignored)."))
        self.add_param(Param("gamma", ParamType.RECT, (1.0, 1.0, 1.0, 1.0), group="Wheels"))
        self.add_param(Param("gain", ParamType.RECT, (1.0, 1.0, 1.0, 1.0), group="Wheels"))
        self.add_param(Param("lut_file", ParamType.FILEPATH, "", group="LUT"))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        if src is None:
            return self._empty(ctx)
        f = ctx.acquire_fbo()
        ctx.compositor.color_adjust(
            f, src,
            exposure=self.params["exposure"].value,
            contrast=self.params["contrast"].value,
            saturation=self.params["saturation"].value,
            temperature=self.params["temperature"].value,
            tint=self.params["tint"].value,
            lift=tuple(self.params["lift"].value)[:3],
            gamma=tuple(self.params["gamma"].value)[:3],
            gain=tuple(self.params["gain"].value)[:3],
            hue_shift=math.radians(self.params["hue_shift"].value),
        )
        return {"image": f.color_attachments[0]}


@register
class Blur(_Modifier):
    type_name = "Blur"
    title_default = "Blur"
    color = (100, 110, 130)

    def _define(self) -> None:
        self._io()
        self.add_param(Param("radius", ParamType.FLOAT, 8.0, min=0, max=64, step=0.5, group="Blur",
                             accepts_input=True))
        self.add_param(Param("type", ParamType.ENUM, "gaussian", choices=tuple(_BLUR_TYPE),
                             group="Blur"))
        self.add_param(Param("angle", ParamType.FLOAT, 0.0, min=-180, max=180, group="Blur"))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        if src is None:
            return self._empty(ctx)
        r = float(self.p("radius", ctx.t, inputs))
        out = ctx.acquire_fbo()
        tmp = ctx.acquire_fbo()
        if r <= 0:
            ctx.compositor.sample(out, src, fit=0)
            return {"image": out.color_attachments[0]}
        ctx.compositor.gaussian_blur(src, r, ctx.cw, ctx.ch, out, tmp)
        return {"image": out.color_attachments[0]}


@register
class Key(_Modifier):
    type_name = "Key"
    title_default = "Key"
    color = (90, 140, 110)

    def _define(self) -> None:
        self._io()
        self.add_param(Param("mode", ParamType.ENUM, "chroma", choices=tuple(_KEY_MODE), group="Key"))
        self.add_param(Param("key_color", ParamType.COLOR, (0.0, 1.0, 0.0, 1.0), group="Key"))
        self.add_param(Param("tolerance", ParamType.FLOAT, 0.25, min=0, max=1, step=0.01, group="Key"))
        self.add_param(Param("softness", ParamType.FLOAT, 0.1, min=0, max=1, step=0.01, group="Key"))
        self.add_param(Param("spill_suppression", ParamType.FLOAT, 0.4, min=0, max=1, step=0.01, group="Key"))
        self.add_param(Param("despill_amount", ParamType.FLOAT, 0.3, min=0, max=1, step=0.01, group="Key"))
        self.add_param(Param("invert", ParamType.BOOL, False, group="Key"))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        if src is None:
            return self._empty(ctx)
        f = ctx.acquire_fbo()
        ctx.compositor.key(
            f, src, mode=_KEY_MODE.get(self.params["mode"].value, 2),
            key=tuple(self.params["key_color"].value)[:3],
            tolerance=self.params["tolerance"].value,
            softness=self.params["softness"].value,
            spill=self.params["spill_suppression"].value,
            despill=self.params["despill_amount"].value,
            invert=int(self.params["invert"].value),
        )
        return {"image": f.color_attachments[0]}


@register
class Opacity(_Modifier):
    type_name = "Opacity"
    title_default = "Opacity"
    color = (110, 110, 110)

    def _define(self) -> None:
        self._io()
        self.add_param(Param("amount", ParamType.FLOAT, 1.0, min=0, max=1, step=0.01,
                             group="Opacity", accepts_input=True))

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        if src is None:
            return self._empty(ctx)
        amt = float(self.p("amount", ctx.t, inputs))
        f = ctx.acquire_fbo()
        empty = ctx.acquire_fbo()
        empty.use()
        empty.clear(0, 0, 0, 0)
        ctx.compositor.compose(f, empty.color_attachments[0], src, opacity=amt)
        return {"image": f.color_attachments[0]}
