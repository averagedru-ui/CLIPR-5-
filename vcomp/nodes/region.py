"""HUD Region - the node the user creates dozens of.

Lifts a masked sub-rect of the source frame onto the vertical canvas with an
analytic shape (or a baked polygon mask), feathered edge, optional plate,
outline and drop shadow.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from vcomp.core.params import Param, ParamType, WireType
from vcomp.core import coords
from vcomp.render.blend import BlendMode
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register

_SHAPES = ("rect", "rounded_rect", "ellipse", "polygon")
_SHAPE_ID = {name: i for i, name in enumerate(_SHAPES)}


def parse_point_string(raw: str) -> list[tuple[float, float]]:
    """``"x,y;x,y;..."`` -> ``[(x, y), ...]`` (silently drops malformed pairs)."""
    pts: list[tuple[float, float]] = []
    for pair in str(raw).replace(" ", "").split(";"):
        if "," in pair:
            a, b = pair.split(",")[:2]
            try:
                pts.append((float(a), float(b)))
            except ValueError:
                pass
    return pts


def format_points(pts: list[tuple[float, float]]) -> str:
    return ";".join(f"{x:.5f},{y:.5f}" for x, y in pts)


def bbox_of(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Axis-aligned bounds ``(x, y, w, h)`` of a point list."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = min(xs), min(ys)
    return (x0, y0, max(xs) - x0, max(ys) - y0)


def _bake_polygon_mask(points: list[tuple[float, float]], res: int = 256) -> np.ndarray:
    """Rasterize a polygon (points in 0..1 quad space) to an RGB mask, 2x SSAA."""
    if len(points) < 3:
        return np.full((res, res, 3), 255, np.uint8)
    ss = res * 2
    ys, xs = np.mgrid[0:ss, 0:ss].astype(np.float32)
    px = (xs + 0.5) / ss
    py = (ys + 0.5) / ss
    inside = np.zeros((ss, ss), bool)
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        cond = ((yi > py) != (yj > py)) & (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        )
        inside ^= cond
        j = i
    m = inside.astype(np.float32).reshape(res, 2, res, 2).mean(axis=(1, 3))
    m8 = (np.clip(m, 0, 1) * 255).astype(np.uint8)
    return np.dstack([m8, m8, m8])


@register
class HUDRegion(VNode):
    type_name = "HUD Region"
    category = "Framing"
    title_default = "HUD Region"
    color = (150, 110, 90)

    def _define(self) -> None:
        # Source
        self.add_param(Param("label", ParamType.STR, "Region", group="Meta",
                             tooltip="Shown as the node title (e.g. 'Minimap')."))
        self.add_param(Param("shape", ParamType.ENUM, "rect", choices=_SHAPES, group="Source"))
        self.add_param(Param("source_rect", ParamType.RECT, (0.0, 0.0, 0.2, 0.2),
                             group="Source", tooltip="Sub-rect of the source frame."))
        self.add_param(Param("corner_radii", ParamType.RECT, (0.1, 0.1, 0.1, 0.1),
                             group="Source", tooltip="Per-corner radius (rounded_rect)."))
        self.add_param(Param("polygon_points", ParamType.STR, "",
                             group="Source", tooltip="x,y;x,y;... in 0..1 quad space."))
        self.add_param(Param("anchor", ParamType.ENUM, "top-left",
                             choices=tuple(coords.ANCHORS), group="Source"))
        self.add_param(Param("size_mode", ParamType.ENUM, "relative",
                             choices=coords.SIZE_MODES, group="Source"))
        self.add_param(Param("reference_height", ParamType.INT, 1080, min=1, group="Source"))
        self.add_param(Param("ultrawide_policy", ParamType.ENUM, "pin_to_edge",
                             choices=coords.ULTRAWIDE_POLICIES, group="Source"))

        # Placement
        self.add_param(Param("dest_x", ParamType.FLOAT, 0.5, min=-0.5, max=1.5, step=0.005,
                             group="Placement", accepts_input=True))
        self.add_param(Param("dest_y", ParamType.FLOAT, 0.15, min=-0.5, max=1.5, step=0.005,
                             group="Placement", accepts_input=True))
        self.add_param(Param("dest_scale", ParamType.FLOAT, 1.0, min=0.02, max=8.0, step=0.01,
                             group="Placement", accepts_input=True))
        self.add_param(Param("dest_scale_x", ParamType.FLOAT, 1.0, min=0.02, max=8.0, group="Placement"))
        self.add_param(Param("dest_scale_y", ParamType.FLOAT, 1.0, min=0.02, max=8.0, group="Placement"))
        self.add_param(Param("link_scale", ParamType.BOOL, True, group="Placement"))
        self.add_param(Param("rotation", ParamType.FLOAT, 0.0, min=-180, max=180, group="Placement"))
        self.add_param(Param("dest_anchor", ParamType.ENUM, "center",
                             choices=tuple(coords.ANCHORS), group="Placement"))
        self.add_param(Param("flip_h", ParamType.BOOL, False, group="Placement"))
        self.add_param(Param("flip_v", ParamType.BOOL, False, group="Placement"))

        # Edge
        self.add_param(Param("feather", ParamType.FLOAT, 1.5, min=0.0, max=128.0, step=0.5,
                             group="Edge", tooltip="Edge softness in canvas px."))
        self.add_param(Param("mask_expand", ParamType.FLOAT, 0.0, min=-64.0, max=64.0, step=0.5,
                             group="Edge", tooltip="Dilate (+) / erode (-) the mask, px."))
        self.add_param(Param("crop_left", ParamType.FLOAT, 0.0, min=0.0, max=0.49, step=0.005,
                             group="Edge", tooltip="Trim the mask's left edge (fraction)."))
        self.add_param(Param("crop_right", ParamType.FLOAT, 0.0, min=0.0, max=0.49, step=0.005,
                             group="Edge", tooltip="Trim the mask's right edge."))
        self.add_param(Param("crop_top", ParamType.FLOAT, 0.0, min=0.0, max=0.49, step=0.005,
                             group="Edge", tooltip="Trim the mask's top edge."))
        self.add_param(Param("crop_bottom", ParamType.FLOAT, 0.0, min=0.0, max=0.49, step=0.005,
                             group="Edge", tooltip="Trim the mask's bottom edge."))

        # Style
        self.add_param(Param("opacity", ParamType.FLOAT, 1.0, min=0.0, max=1.0, step=0.01,
                             group="Style", accepts_input=True))
        self.add_param(Param("blend_mode", ParamType.ENUM, "normal",
                             choices=tuple(b.name.lower() for b in BlendMode), group="Style"))
        self.add_param(Param("plate_enabled", ParamType.BOOL, False, group="Style"))
        self.add_param(Param("plate_color", ParamType.COLOR, (0, 0, 0, 0.55), group="Style"))
        self.add_param(Param("plate_padding", ParamType.FLOAT, 8.0, min=0.0, max=128.0, group="Style"))
        self.add_param(Param("plate_radius", ParamType.FLOAT, 0.15, min=0.0, max=0.5, step=0.01,
                             group="Style"))
        self.add_param(Param("plate_blur", ParamType.FLOAT, 0.0, min=0.0, max=12.0, group="Style"))
        self.add_param(Param("outline_width", ParamType.FLOAT, 0.0, min=0.0, max=32.0, group="Style"))
        self.add_param(Param("outline_color", ParamType.COLOR, (1, 1, 1, 1), group="Style"))
        self.add_param(Param("shadow_enabled", ParamType.BOOL, False, group="Style"))
        self.add_param(Param("shadow_blur", ParamType.FLOAT, 6.0, min=0.0, max=12.0, group="Style"))
        self.add_param(Param("shadow_offset_y", ParamType.FLOAT, 8.0, min=-64.0, max=64.0, group="Style"))
        self.add_param(Param("shadow_opacity", ParamType.FLOAT, 0.5, min=0.0, max=1.0, step=0.01,
                             group="Style"))
        self.add_param(Param("solo", ParamType.BOOL, False, group="Meta"))

        self.add_input("image", WireType.IMAGE)
        self.add_input("matte", WireType.IMAGE)
        self.add_output("image", WireType.IMAGE)

        self._poly_cache_key = None
        self._poly_tex = None

    # ------------------------------------------------------------------ geom
    def source_uvrect(self) -> tuple[float, float, float, float]:
        x, y, w, h = self.params["source_rect"].value
        return (x, y, x + w, y + h)

    def dest_rect_for(self, canvas_w: int, canvas_h: int, src_w: int, src_h: int,
                      dx: float | None = None, dy: float | None = None,
                      scale: float | None = None) -> tuple[float, float, float, float]:
        """Destination quad (x0,y0,x1,y1 canvas [0,1]). Pure - no GL context."""
        _, _, sw, sh = self.params["source_rect"].value
        src_w = src_w or canvas_w
        src_h = src_h or canvas_h
        # On-canvas size is anchored to a fixed reference height and the source
        # ASPECT only - never the clip's pixel count. So a placement reproduces
        # exactly for any clip of the same aspect, and `reference_height` is a
        # stable authoring constant (set once at create, never auto-changed).
        ref_h = float(self.params["reference_height"].value) if "reference_height" in self.params else 1080.0
        src_aspect = (float(src_w) / max(1.0, float(src_h)))
        reg_px_w = max(1.0, sw * ref_h * src_aspect)
        reg_px_h = max(1.0, sh * ref_h)

        scale = float(self.params["dest_scale"].value if scale is None else scale)
        linked = self.params["link_scale"].value
        scx = scale * (1.0 if linked else self.params["dest_scale_x"].value)
        scy = scale * (1.0 if linked else self.params["dest_scale_y"].value)
        dw = reg_px_w / canvas_w * scx
        dh = reg_px_h / canvas_h * scy

        dx = float(self.params["dest_x"].value if dx is None else dx)
        dy = float(self.params["dest_y"].value if dy is None else dy)
        ax, ay = coords.anchor_uv(self.params["dest_anchor"].value)
        x0, y0 = dx - ax * dw, dy - ay * dh
        return (x0, y0, x0 + dw, y0 + dh)

    def dest_rect(self, ctx) -> tuple[float, float, float, float]:
        return self.dest_rect_for(
            ctx.canvas_w, ctx.canvas_h,
            getattr(self, "_src_w", 0), getattr(self, "_src_h", 0),
            dx=float(self.p("dest_x", ctx.t, {})),
            dy=float(self.p("dest_y", ctx.t, {})),
            scale=float(self.p("dest_scale", ctx.t, {})),
        )

    # ---------------------------------------------------------------- render
    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        src = inputs.get("image")
        out_fbo = ctx.acquire_fbo()
        if src is None:
            out_fbo.use()
            out_fbo.clear(0, 0, 0, 0)
            return {"image": out_fbo.color_attachments[0]}

        self._src_w, self._src_h = src.width, src.height
        comp = ctx.compositor
        cw = ctx.canvas_w

        dest = self.dest_rect(ctx)
        srcrect = self.source_uvrect()
        shape = _SHAPE_ID.get(self.params["shape"].value, 0)
        radii = tuple(self.params["corner_radii"].value)
        feather = float(self.params["feather"].value) / cw
        expand = float(self.params["mask_expand"].value) / cw
        rot = math.radians(float(self.params["rotation"].value))
        opacity = float(self.p("opacity", ctx.t, inputs))
        outline_w = float(self.params["outline_width"].value) / cw

        polymask = None
        if shape == 3:
            polymask = self._polygon_texture(ctx)

        crop = (float(self.params["crop_left"].value), float(self.params["crop_top"].value),
                float(self.params["crop_right"].value), float(self.params["crop_bottom"].value))
        region_fbo = ctx.acquire_fbo()
        comp.region(
            region_fbo, src, dest=dest, srcrect=srcrect, shape=shape, radii=radii,
            feather=feather, expand=expand, rotation=rot, opacity=1.0,
            outline_w=outline_w, outline_color=tuple(self.params["outline_color"].value),
            flip_h=self.params["flip_h"].value, flip_v=self.params["flip_v"].value,
            crop=crop, polymask=polymask,
        )
        acc = region_fbo

        if self.params["plate_enabled"].value:
            pad = float(self.params["plate_padding"].value) / cw
            prect = (dest[0] - pad, dest[1] - pad, dest[2] + pad, dest[3] + pad)
            plate_fbo = ctx.acquire_fbo()
            comp.plate(plate_fbo, rect=prect, radius=float(self.params["plate_radius"].value),
                       softness=max(feather, 0.001), color=tuple(self.params["plate_color"].value))
            pb = float(self.params["plate_blur"].value)
            if pb > 0:
                tmp = ctx.acquire_fbo()
                blr = ctx.acquire_fbo()
                comp.gaussian_blur(plate_fbo.color_attachments[0], pb, ctx.cw, ctx.ch, blr, tmp)
                plate_fbo = blr
            merged = ctx.acquire_fbo()
            comp.compose(merged, plate_fbo.color_attachments[0], acc.color_attachments[0])
            acc = merged

        if self.params["shadow_enabled"].value:
            sh_fbo = ctx.acquire_fbo()
            comp.shadow(sh_fbo, region_fbo.color_attachments[0],
                        offset=(0.0, float(self.params["shadow_offset_y"].value) / cw),
                        color=(0, 0, 0, 1),
                        opacity=float(self.params["shadow_opacity"].value))
            sb = float(self.params["shadow_blur"].value)
            if sb > 0:
                tmp = ctx.acquire_fbo()
                blr = ctx.acquire_fbo()
                comp.gaussian_blur(sh_fbo.color_attachments[0], sb, ctx.cw, ctx.ch, blr, tmp)
                sh_fbo = blr
            merged = ctx.acquire_fbo()
            comp.compose(merged, sh_fbo.color_attachments[0], acc.color_attachments[0])
            acc = merged

        # apply node opacity as a final multiply via compose over empty
        if opacity < 1.0:
            faded = ctx.acquire_fbo()
            empty = ctx.acquire_fbo()
            empty.use()
            empty.clear(0, 0, 0, 0)
            comp.compose(faded, empty.color_attachments[0], acc.color_attachments[0],
                         opacity=opacity)
            acc = faded

        return {"image": acc.color_attachments[0],
                "blend_mode": self.params["blend_mode"].value}

    # --------------------------------------------------------------- polygon
    def _parse_points(self) -> list[tuple[float, float]]:
        return parse_point_string(self.params["polygon_points"].value)

    def polygon_points_source(self) -> list[tuple[float, float]]:
        """Polygon vertices in source-frame [0,1] space (quad-local points mapped
        through ``source_rect``). Empty if not a usable polygon."""
        pts = self._parse_points()
        if len(pts) < 3:
            return []
        x, y, w, h = self.params["source_rect"].value
        return [(x + px * w, y + py * h) for px, py in pts]

    def _polygon_texture(self, ctx):
        pts = self._parse_points()
        key = tuple(pts)
        if key != self._poly_cache_key:
            self._poly_cache_key = key
            self._poly_mask = _bake_polygon_mask(pts)
        return ctx.upload(self._poly_mask)

    def is_time_dependent(self) -> bool:
        # depends on the source frame, which changes with time
        return True
