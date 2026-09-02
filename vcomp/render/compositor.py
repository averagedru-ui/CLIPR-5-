"""M2 compositor: a fixed pipeline (solid background + one letterboxed gameplay
layer). M3 replaces ``render_frame`` with graph evaluation, but the primitives
here — solid fill, ``layer.frag`` pass, readback — stay.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import moderngl
import numpy as np

from vcomp.render.blend import BlendMode
from vcomp.render.context import RenderContext
from vcomp.render.readback import read_fbo


@dataclass
class LayerSpec:
    """A source image placed onto the canvas."""
    dest: tuple[float, float, float, float]     # x0,y0,x1,y1 canvas [0,1] top-left
    srcrect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    opacity: float = 1.0
    feather: float = 0.0
    blend: BlendMode = BlendMode.NORMAL
    flip_h: bool = False
    flip_v: bool = False


@dataclass
class FrameSpec:
    canvas_w: int
    canvas_h: int
    bg_color: tuple[float, float, float, float] = (0.06, 0.06, 0.08, 1.0)
    render_scale: float = 1.0
    layers: list[LayerSpec] = field(default_factory=list)


def letterbox_dest(canvas_w: int, canvas_h: int, src_aspect: float) -> tuple[float, float, float, float]:
    """Full-width gameplay band, vertically centred (the classic look)."""
    band_h_px = canvas_w / src_aspect
    y0 = (canvas_h - band_h_px) / 2.0 / canvas_h
    y1 = 1.0 - y0
    return (0.0, max(0.0, y0), 1.0, min(1.0, y1))


class Compositor:
    def __init__(self, ctx: RenderContext | None = None) -> None:
        self.ctx = ctx or RenderContext()
        self._solid = self.ctx.program("fullscreen.vert", "solid.frag")
        self._layer = self.ctx.program("fullscreen.vert", "layer.frag")
        self._blit = self.ctx.program("fullscreen.vert", "blit.frag")
        self._compose = self.ctx.program("fullscreen.vert", "compose.frag")
        self._region = self.ctx.program("fullscreen.vert", "region.frag")
        self._blur = self.ctx.program("fullscreen.vert", "blur.frag")
        self._plate = self.ctx.program("fullscreen.vert", "plate.frag")
        self._shadow = self.ctx.program("fullscreen.vert", "shadow.frag")
        self._gradient = self.ctx.program("fullscreen.vert", "gradient.frag")
        self._adjust = self.ctx.program("fullscreen.vert", "adjust.frag")
        self._key = self.ctx.program("fullscreen.vert", "key.frag")
        self._bgfx = self.ctx.program("fullscreen.vert", "bgfx.frag")
        self._sample = self.ctx.program("fullscreen.vert", "sample.frag")

    # ------------------------------------------------------- node-graph ops
    def fill_solid(self, fbo: moderngl.Framebuffer, color) -> None:
        fbo.use()
        self.ctx.ctx.disable(moderngl.BLEND)
        self._solid["u_color"].value = tuple(color)
        self.ctx.draw_fullscreen(self._solid)

    def blit(self, fbo: moderngl.Framebuffer, src_tex: moderngl.Texture, *,
             dest=(0.0, 0.0, 1.0, 1.0), srcrect=(0.0, 0.0, 1.0, 1.0),
             opacity=1.0, feather=0.0, radius=0.0, rotation=0.0, skew=(0.0, 0.0),
             flip_h=False, flip_v=False) -> None:
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.ctx.disable(moderngl.BLEND)
        src_tex.use(0)
        p = self._blit
        p["u_src"].value = 0
        p["u_dest"].value = tuple(dest)
        p["u_srcrect"].value = tuple(srcrect)
        p["u_opacity"].value = float(opacity)
        p["u_feather"].value = float(feather)
        p["u_radius"].value = float(radius)
        p["u_rotation"].value = float(rotation)
        p["u_skew"].value = tuple(skew)
        p["u_flip_h"].value = int(flip_h)
        p["u_flip_v"].value = int(flip_v)
        self.ctx.draw_fullscreen(p)

    def compose(self, dst: moderngl.Framebuffer, bg_tex: moderngl.Texture,
                top_tex: moderngl.Texture, *, opacity=1.0,
                blend: BlendMode = BlendMode.NORMAL) -> None:
        dst.use()
        dst.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.ctx.disable(moderngl.BLEND)
        bg_tex.use(0)
        top_tex.use(1)
        p = self._compose
        p["u_bg"].value = 0
        p["u_top"].value = 1
        p["u_opacity"].value = float(opacity)
        p["u_blend"].value = int(blend)
        self.ctx.draw_fullscreen(p)

    def to_numpy(self, fbo: moderngl.Framebuffer) -> np.ndarray:
        return read_fbo(fbo, components=4)

    # ------------------------------------------------------------- M4 ops
    def region(self, fbo: moderngl.Framebuffer, src_tex: moderngl.Texture, *,
               dest, srcrect, shape: int, radii=(0.0, 0.0, 0.0, 0.0),
               feather=0.0, expand=0.0, rotation=0.0, opacity=1.0,
               outline_w=0.0, outline_color=(1, 1, 1, 1),
               flip_h=False, flip_v=False, crop=(0.0, 0.0, 0.0, 0.0),
               polymask: moderngl.Texture | None = None) -> None:
        fbo.use()
        fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.ctx.disable(moderngl.BLEND)
        src_tex.use(0)
        p = self._region
        p["u_src"].value = 0
        if polymask is not None:
            polymask.use(1)
            p["u_polymask"].value = 1
            p["u_has_polymask"].value = 1
        else:
            p["u_has_polymask"].value = 0
        p["u_dest"].value = tuple(dest)
        p["u_srcrect"].value = tuple(srcrect)
        p["u_shape"].value = int(shape)
        p["u_radii"].value = tuple(radii)
        p["u_feather"].value = float(feather)
        p["u_expand"].value = float(expand)
        p["u_rotation"].value = float(rotation)
        p["u_flip_h"].value = int(flip_h)
        p["u_flip_v"].value = int(flip_v)
        p["u_outline_w"].value = float(outline_w)
        p["u_outline_color"].value = tuple(outline_color)
        p["u_opacity"].value = float(opacity)
        p["u_crop"].value = tuple(crop)
        self.ctx.draw_fullscreen(p)

    def gaussian_blur(self, tex: moderngl.Texture, radius_px: float,
                      w: int, h: int, out_fbo, tmp_fbo) -> None:
        """Two-pass separable blur; result left in ``out_fbo``."""
        r = int(max(0, min(12, round(radius_px))))
        p = self._blur
        p["u_tex"].value = 0
        p["u_radius"].value = r
        tmp_fbo.use()
        tmp_fbo.clear(0, 0, 0, 0)
        self.ctx.ctx.disable(moderngl.BLEND)
        tex.use(0)
        p["u_dir"].value = (1.0 / w, 0.0)
        self.ctx.draw_fullscreen(p)
        out_fbo.use()
        out_fbo.clear(0, 0, 0, 0)
        tmp_fbo.color_attachments[0].use(0)
        p["u_dir"].value = (0.0, 1.0 / h)
        self.ctx.draw_fullscreen(p)

    def plate(self, fbo, *, rect, radius=0.0, softness=0.002, color=(0, 0, 0, 0.5)) -> None:
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        self.ctx.ctx.disable(moderngl.BLEND)
        p = self._plate
        p["u_rect"].value = tuple(rect)
        p["u_radius"].value = float(radius)
        p["u_softness"].value = float(softness)
        p["u_color"].value = tuple(color)
        self.ctx.draw_fullscreen(p)

    def shadow(self, fbo, region_tex, *, offset=(0.0, 0.0), color=(0, 0, 0, 1),
               opacity=0.5) -> None:
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        self.ctx.ctx.disable(moderngl.BLEND)
        region_tex.use(0)
        p = self._shadow
        p["u_tex"].value = 0
        p["u_offset"].value = tuple(offset)
        p["u_color"].value = tuple(color)
        p["u_opacity"].value = float(opacity)
        self.ctx.draw_fullscreen(p)

    # --------------------------------------------------------- M5 ops
    def _run1(self, prog, fbo, tex, uniforms: dict, tex_uniform: str = "u_tex") -> None:
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        self.ctx.ctx.disable(moderngl.BLEND)
        if tex is not None:
            tex.use(0)
            if tex_uniform in prog:
                prog[tex_uniform].value = 0
        for k, v in uniforms.items():
            if k in prog:
                prog[k].value = v
        self.ctx.draw_fullscreen(prog)

    def gradient(self, fbo, *, gtype, angle, center, radius, stops, interp, dither) -> None:
        p = self._gradient
        n = min(8, len(stops))
        pos = [0.0] * 8
        cols = [(0.0, 0.0, 0.0, 1.0)] * 8
        for i in range(n):
            pos[i] = float(stops[i][0])
            cols[i] = tuple(stops[i][1])
        fbo.use()
        fbo.clear(0, 0, 0, 0)
        self.ctx.ctx.disable(moderngl.BLEND)
        p["u_type"].value = int(gtype)
        p["u_angle"].value = float(angle)
        p["u_center"].value = tuple(center)
        p["u_radius"].value = float(radius)
        p["u_count"].value = int(n)
        p["u_pos"].value = pos
        p["u_col"].write(_f32(cols))
        p["u_interp"].value = int(interp)
        p["u_dither"].value = int(dither)
        self.ctx.draw_fullscreen(p)

    def color_adjust(self, fbo, tex, **u) -> None:
        self._run1(self._adjust, fbo, tex, {
            "u_exposure": float(u.get("exposure", 0.0)),
            "u_contrast": float(u.get("contrast", 1.0)),
            "u_saturation": float(u.get("saturation", 1.0)),
            "u_temperature": float(u.get("temperature", 0.0)),
            "u_tint": float(u.get("tint", 0.0)),
            "u_lift": tuple(u.get("lift", (0, 0, 0))),
            "u_gamma": tuple(u.get("gamma", (1, 1, 1))),
            "u_gain": tuple(u.get("gain", (1, 1, 1))),
            "u_hue_shift": float(u.get("hue_shift", 0.0)),
        })

    def key(self, fbo, tex, **u) -> None:
        self._run1(self._key, fbo, tex, {
            "u_mode": int(u.get("mode", 0)),
            "u_key": tuple(u.get("key", (0, 1, 0))),
            "u_tolerance": float(u.get("tolerance", 0.1)),
            "u_softness": float(u.get("softness", 0.1)),
            "u_spill": float(u.get("spill", 0.0)),
            "u_despill": float(u.get("despill", 0.0)),
            "u_invert": int(u.get("invert", 0)),
        })

    def bgfx(self, fbo, tex, **u) -> None:
        self._run1(self._bgfx, fbo, tex, {
            "u_brightness": float(u.get("brightness", 1.0)),
            "u_saturation": float(u.get("saturation", 1.0)),
            "u_contrast": float(u.get("contrast", 1.0)),
            "u_tint": tuple(u.get("tint", (1, 1, 1))),
            "u_tint_amount": float(u.get("tint_amount", 0.0)),
            "u_overlay": tuple(u.get("overlay", (0, 0, 0, 0))),
            "u_vignette": float(u.get("vignette", 0.0)),
            "u_vignette_soft": float(u.get("vignette_soft", 0.25)),
        })

    def sample(self, fbo, tex, **u) -> None:
        self._run1(self._sample, fbo, tex, {
            "u_translate": tuple(u.get("translate", (0.0, 0.0))),
            "u_scale": tuple(u.get("scale", (1.0, 1.0))),
            "u_rotation": float(u.get("rotation", 0.0)),
            "u_anchor": tuple(u.get("anchor", (0.5, 0.5))),
            "u_fit": int(u.get("fit", 0)),
            "u_src_aspect": float(u.get("src_aspect", 1.0)),
            "u_canvas_aspect": float(u.get("canvas_aspect", 0.5625)),
            "u_skew": tuple(u.get("skew", (0.0, 0.0))),
            "u_opacity": float(u.get("opacity", 1.0)),
        }, tex_uniform="u_src")

    def blur_tex(self, tex, radius_px, w, h, out_fbo, tmp_fbo) -> None:
        self.gaussian_blur(tex, radius_px, w, h, out_fbo, tmp_fbo)

    def thumbnail(self, tex: moderngl.Texture, w: int = 64, h: int = 114) -> np.ndarray:
        """Small RGBA preview of an image texture (for node-canvas thumbnails)."""
        fbo = self.ctx.acquire_fbo(w, h)
        try:
            self.sample(fbo, tex, fit=3)   # stretch-copy into the thumb
            return read_fbo(fbo, components=4)
        finally:
            self.ctx.release_fbo(fbo)

    # ------------------------------------------------------------------ render
    def render_frame(self, spec: FrameSpec, source_rgb: np.ndarray | None) -> np.ndarray:
        rs = max(0.25, spec.render_scale)
        w = _even(int(round(spec.canvas_w * rs)))
        h = _even(int(round(spec.canvas_h * rs)))
        gl = self.ctx.ctx

        src_tex = self.ctx.texture_from_array(source_rgb) if source_rgb is not None else None

        bg = self.ctx.acquire_fbo(w, h)
        front = self.ctx.acquire_fbo(w, h)
        try:
            bg.use()
            gl.disable(moderngl.BLEND)
            self._solid["u_color"].value = spec.bg_color
            self.ctx.draw_fullscreen(self._solid)

            read_from, write_to = bg, front
            for layer in spec.layers:
                write_to.use()
                gl.viewport = (0, 0, w, h)
                p = self._layer
                read_from.color_attachments[0].use(0)
                p["u_bg"].value = 0
                if src_tex is not None:
                    src_tex.use(1)
                    p["u_src"].value = 1
                    p["u_has_src"].value = 1
                else:
                    p["u_has_src"].value = 0
                p["u_dest"].value = layer.dest
                p["u_srcrect"].value = layer.srcrect
                p["u_opacity"].value = float(layer.opacity)
                p["u_feather"].value = float(layer.feather)
                p["u_blend"].value = int(layer.blend)
                p["u_flip_h"].value = int(layer.flip_h)
                p["u_flip_v"].value = int(layer.flip_v)
                self.ctx.draw_fullscreen(p)
                read_from, write_to = write_to, read_from

            result = read_fbo(read_from, components=4)
            if rs != 1.0:
                result = _resize_nn(result, spec.canvas_w, spec.canvas_h)
            return result
        finally:
            if src_tex is not None:
                src_tex.release()
            self.ctx.release_fbo(bg)
            self.ctx.release_fbo(front)

    def render_gameplay_on_solid(
        self, source_rgb: np.ndarray, canvas_w: int = 1080, canvas_h: int = 1920,
        bg_color=(0.06, 0.06, 0.08, 1.0), render_scale: float = 1.0,
    ) -> np.ndarray:
        h, w = source_rgb.shape[:2]
        spec = FrameSpec(canvas_w, canvas_h, bg_color, render_scale,
                         [LayerSpec(dest=letterbox_dest(canvas_w, canvas_h, w / h))])
        return self.render_frame(spec, source_rgb)

    def release(self) -> None:
        self.ctx.release()


def _f32(rows) -> bytes:
    return np.asarray(rows, dtype="f4").tobytes()


def _even(n: int) -> int:
    return n if n % 2 == 0 else n + 1


def _resize_nn(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    yi = (np.arange(h) * (arr.shape[0] / h)).astype(np.int64)
    xi = (np.arange(w) * (arr.shape[1] / w)).astype(np.int64)
    return arr[yi][:, xi].copy()
