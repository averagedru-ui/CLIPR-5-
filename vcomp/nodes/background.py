"""Background generator nodes. All output a full-canvas Image."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_GTYPE = {"linear": 0, "radial": 1, "conic": 2}
_INTERP = {"sRGB": 0, "oklab": 1}
_FIT = {"none": 0, "cover": 1, "contain": 2, "stretch": 3, "tile": 4, "mirror_edges": 5}


def _decode_image(path: str) -> np.ndarray | None:
    try:
        import av

        with av.open(path) as c:
            for frame in c.decode(video=0):
                return np.ascontiguousarray(frame.to_ndarray(format="rgba"))
    except Exception:  # noqa: BLE001
        return None
    return None


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


@register
class GradientBackground(VNode):
    type_name = "Gradient Background"
    category = "Background"
    title_default = "Gradient Background"
    color = (60, 90, 130)

    def _define(self) -> None:
        self.add_param(Param("type", ParamType.ENUM, "linear", choices=tuple(_GTYPE), group="Gradient"))
        self.add_param(Param("angle", ParamType.FLOAT, 90.0, min=-360, max=360, group="Gradient"))
        self.add_param(Param("center_x", ParamType.FLOAT, 0.5, min=0, max=1, group="Gradient"))
        self.add_param(Param("center_y", ParamType.FLOAT, 0.5, min=0, max=1, group="Gradient"))
        self.add_param(Param("radius", ParamType.FLOAT, 0.7, min=0.01, max=2.0, group="Gradient"))
        self.add_param(Param("stops", ParamType.STR, "0:0.05,0.05,0.08,1 ; 1:0.15,0.16,0.22,1",
                             group="Gradient",
                             tooltip="pos:r,g,b,a ; pos:r,g,b,a ; ..."))
        self.add_param(Param("dither", ParamType.BOOL, True, group="Gradient"))
        self.add_param(Param("interpolation", ParamType.ENUM, "oklab", choices=tuple(_INTERP),
                             group="Gradient"))
        self.add_output("image", WireType.IMAGE)

    def _parse_stops(self):
        out = []
        for seg in str(self.params["stops"].value).split(";"):
            seg = seg.strip()
            if ":" not in seg:
                continue
            pos, rest = seg.split(":", 1)
            try:
                p = float(pos)
                parts = [float(x) for x in rest.split(",")]
                while len(parts) < 4:
                    parts.append(1.0)
                out.append((p, tuple(parts[:4])))
            except ValueError:
                pass
        return out or [(0.0, (0, 0, 0, 1)), (1.0, (1, 1, 1, 1))]

    def render(self, ctx, inputs) -> dict[str, Any]:
        fbo = ctx.acquire_fbo()
        ctx.compositor.gradient(
            fbo, gtype=_GTYPE.get(self.params["type"].value, 0),
            angle=math.radians(self.params["angle"].value),
            center=(self.params["center_x"].value, self.params["center_y"].value),
            radius=self.params["radius"].value,
            stops=self._parse_stops(),
            interp=_INTERP.get(self.params["interpolation"].value, 1),
            dither=int(self.params["dither"].value),
        )
        return {"image": fbo.color_attachments[0]}


@register
class ImageBackground(VNode):
    type_name = "Image Background"
    category = "Background"
    title_default = "Image Background"
    color = (60, 90, 130)

    def _define(self) -> None:
        self.add_param(Param("file_path", ParamType.FILEPATH, "", group="Image"))
        self.add_param(Param("fit", ParamType.ENUM, "cover",
                             choices=("cover", "contain", "tile", "stretch"), group="Image"))
        self.add_param(Param("offset_x", ParamType.FLOAT, 0.0, min=-1, max=1, group="Image"))
        self.add_param(Param("offset_y", ParamType.FLOAT, 0.0, min=-1, max=1, group="Image"))
        self.add_param(Param("scale", ParamType.FLOAT, 1.0, min=0.05, max=8.0, group="Image"))
        self.add_param(Param("opacity", ParamType.FLOAT, 1.0, min=0, max=1, group="Image"))
        self.add_param(Param("tint", ParamType.COLOR, (1, 1, 1, 0), group="Image"))
        self.add_output("image", WireType.IMAGE)
        self._path = None
        self._img = None

    def render(self, ctx, inputs) -> dict[str, Any]:
        path = self.params["file_path"].value
        if path != self._path:
            self._path = path
            self._img = _decode_image(path) if path else None

        fbo = ctx.acquire_fbo()
        if self._img is None:
            fbo.use()
            fbo.clear(0, 0, 0, 0)
            return {"image": fbo.color_attachments[0]}

        tex = ctx.upload(self._img)
        h, w = self._img.shape[:2]
        ctx.compositor.sample(
            fbo, tex, translate=(self.params["offset_x"].value, self.params["offset_y"].value),
            scale=(self.params["scale"].value, self.params["scale"].value),
            anchor=(0.5, 0.5), fit=_FIT.get(self.params["fit"].value, 1),
            src_aspect=w / h, canvas_aspect=ctx.canvas_w / ctx.canvas_h,
            opacity=self.params["opacity"].value,
        )
        return {"image": fbo.color_attachments[0]}


@register
class BlurBackground(VNode):
    type_name = "Blur Background"
    category = "Background"
    title_default = "Blur Background"
    color = (60, 110, 140)

    def _define(self) -> None:
        self.add_input("image", WireType.IMAGE)
        self.add_param(Param("fit", ParamType.ENUM, "cover",
                             choices=("cover", "contain", "stretch", "mirror_edges"), group="Fit"))
        self.add_param(Param("zoom", ParamType.FLOAT, 1.1, min=1.0, max=3.0, step=0.01, group="Fit"))
        self.add_param(Param("blur_radius", ParamType.FLOAT, 80.0, min=0, max=600, step=1,
                             group="Blur", tooltip="Higher = heavier blur (iterated Gaussian)."))
        self.add_param(Param("blur_quality", ParamType.ENUM, "high", choices=("fast", "high"),
                             group="Blur"))
        self.add_param(Param("downsample_factor", ParamType.INT, 4, min=1, max=8, group="Blur"))
        self.add_param(Param("brightness", ParamType.FLOAT, 0.9, min=0, max=2, step=0.01, group="Look"))
        self.add_param(Param("saturation", ParamType.FLOAT, 1.0, min=0, max=2, step=0.01, group="Look"))
        self.add_param(Param("contrast", ParamType.FLOAT, 1.0, min=0, max=2, step=0.01, group="Look"))
        self.add_param(Param("tint_color", ParamType.COLOR, (0.2, 0.3, 0.5, 1), group="Look"))
        self.add_param(Param("tint_amount", ParamType.FLOAT, 0.0, min=0, max=1, step=0.01, group="Look"))
        self.add_param(Param("overlay_color", ParamType.COLOR, (0, 0, 0, 1), group="Look"))
        self.add_param(Param("overlay_opacity", ParamType.FLOAT, 0.25, min=0, max=1, step=0.01,
                             group="Look"))
        self.add_param(Param("vignette_amount", ParamType.FLOAT, 0.25, min=0, max=1, step=0.01,
                             group="Look"))
        self.add_param(Param("vignette_softness", ParamType.FLOAT, 0.3, min=0, max=1, step=0.01,
                             group="Look"))
        self.add_output("image", WireType.IMAGE)

    def is_time_dependent(self) -> bool:
        return True

    def render(self, ctx, inputs) -> dict[str, Any]:
        src = inputs.get("image")
        out = ctx.acquire_fbo()
        if src is None:
            ctx.compositor.fill_solid(out, (0.05, 0.05, 0.07, 1))
            return {"image": out.color_attachments[0]}

        comp = ctx.compositor
        cw, ch = ctx.cw, ctx.ch

        # 1. cover-fit + zoom into a full-canvas FBO
        covered = ctx.acquire_fbo()
        z = float(self.params["zoom"].value)
        fit_map = {"cover": 1, "contain": 2, "stretch": 3, "mirror_edges": 5}
        comp.sample(covered, src, scale=(z, z), anchor=(0.5, 0.5),
                    fit=fit_map.get(self.params["fit"].value, 1),
                    src_aspect=src.width / src.height,
                    canvas_aspect=ctx.canvas_w / ctx.canvas_h)

        # 2. blur - iterated separable Gaussian on a downsampled buffer.
        #    N iterations of an 8-tap Gaussian approximate a much wider kernel;
        #    the working buffer shrinks as the radius grows so huge blurs stay cheap.
        rad_px = float(self.params["blur_radius"].value)
        ds = min(16, max(1, int(self.params["downsample_factor"].value) + int(rad_px // 50)))
        bw, bh = max(4, cw // ds), max(4, ch // ds)
        small = ctx.acquire_fbo(bw, bh)
        comp.sample(small, covered.color_attachments[0], fit=3)   # stretch-copy down
        tmp = ctx.acquire_fbo(bw, bh)
        blr = ctx.acquire_fbo(bw, bh)

        per_iter = 8.0
        target = rad_px / ds
        iters = int(max(1, min(48, round((target / per_iter) ** 2 + target / per_iter))))
        if self.params["blur_quality"].value == "high":
            iters = min(72, iters * 2)
        srct = small.color_attachments[0]
        for _ in range(iters):
            comp.gaussian_blur(srct, per_iter, bw, bh, blr, tmp)
            srct = blr.color_attachments[0]
        up = ctx.acquire_fbo()
        comp.sample(up, srct, fit=3)

        # 3. look pass
        comp.bgfx(
            out, up.color_attachments[0],
            brightness=self.params["brightness"].value,
            saturation=self.params["saturation"].value,
            contrast=self.params["contrast"].value,
            tint=tuple(self.params["tint_color"].value)[:3],
            tint_amount=self.params["tint_amount"].value,
            overlay=(*tuple(self.params["overlay_color"].value)[:3],
                     self.params["overlay_opacity"].value),
            vignette=self.params["vignette_amount"].value,
            vignette_soft=self.params["vignette_softness"].value,
        )
        return {"image": out.color_attachments[0]}
