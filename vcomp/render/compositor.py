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

    # ------------------------------------------------------- node-graph ops
    def fill_solid(self, fbo: moderngl.Framebuffer, color) -> None:
        fbo.use()
        self.ctx.ctx.disable(moderngl.BLEND)
        self._solid["u_color"].value = tuple(color)
        self.ctx.draw_fullscreen(self._solid)

    def blit(self, fbo: moderngl.Framebuffer, src_tex: moderngl.Texture, *,
             dest=(0.0, 0.0, 1.0, 1.0), srcrect=(0.0, 0.0, 1.0, 1.0),
             opacity=1.0, feather=0.0, radius=0.0, flip_h=False, flip_v=False) -> None:
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


def _even(n: int) -> int:
    return n if n % 2 == 0 else n + 1


def _resize_nn(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    yi = (np.arange(h) * (arr.shape[0] / h)).astype(np.int64)
    xi = (np.arange(w) * (arr.shape[1] / w)).astype(np.int64)
    return arr[yi][:, xi].copy()
