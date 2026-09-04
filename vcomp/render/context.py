"""moderngl offscreen rendering context: the one renderer shared by preview and
export (spec 2, 5.1).

Owns:
  * a standalone GL 3.3-core context (no window),
  * an FBO pool keyed by ``(w, h)`` with acquire / release,
  * a shader program cache with a minimal ``#include`` preprocessor,
  * texture upload helpers for numpy RGB / RGBA arrays.

Qt is never imported here.
"""
from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path

import moderngl
import numpy as np

from vcomp.util import paths

log = logging.getLogger("vcomp.render")

_SHADER_DIR = paths.resource_path("vcomp", "render", "shaders")
_INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$', re.MULTILINE)


class RenderContext:
    def __init__(self, standalone: bool = True) -> None:
        if standalone:
            self.ctx = moderngl.create_context(standalone=True, require=330)
        else:  # attach to an already-current context (Qt GL widget)
            self.ctx = moderngl.create_context(require=330)
        self.ctx.gc_mode = "auto"
        log.info("GL %s | %s | %s",
                 self.ctx.version_code, self.ctx.info.get("GL_RENDERER", "?"),
                 self.ctx.info.get("GL_VENDOR", "?"))

        self._free: dict[tuple[int, int], list[moderngl.Framebuffer]] = {}
        self._in_use: set[int] = set()
        # source-frame textures are re-uploaded every frame - pool + rewrite
        # instead of realloc, and never build mipmaps (nothing samples them)
        self._tex_free: dict[tuple[int, int, int], list[moderngl.Texture]] = {}
        self._tex_in_use: dict[int, moderngl.Texture] = {}
        self._programs: dict[tuple[str, str], moderngl.Program] = {}
        self._empty_vao = self.ctx.vertex_array(self._noop_prog(), [])

    @property
    def renderer_string(self) -> str:
        return str(self.ctx.info.get("GL_RENDERER", "unknown"))

    # ------------------------------------------------------------- shaders
    def _read_shader(self, name: str) -> str:
        text = (_SHADER_DIR / name).read_text(encoding="utf-8")

        def _sub(m: re.Match) -> str:
            return (_SHADER_DIR / m.group(1)).read_text(encoding="utf-8")

        return _INCLUDE_RE.sub(_sub, text)

    def program(self, vert: str, frag: str) -> moderngl.Program:
        key = (vert, frag)
        prog = self._programs.get(key)
        if prog is None:
            prog = self.ctx.program(
                vertex_shader=self._read_shader(vert),
                fragment_shader=self._read_shader(frag),
            )
            self._programs[key] = prog
        return prog

    def _noop_prog(self) -> moderngl.Program:
        return self.ctx.program(
            vertex_shader="#version 330\nvoid main(){ gl_Position=vec4(0); }",
            fragment_shader="#version 330\nout vec4 c;\nvoid main(){ c=vec4(0); }",
        )

    def draw_fullscreen(self, prog: moderngl.Program) -> None:
        """Render a fullscreen triangle with ``prog`` (uses fullscreen.vert)."""
        vao = self.ctx.vertex_array(prog, [])
        vao.render(mode=moderngl.TRIANGLES, vertices=3)
        vao.release()

    # ---------------------------------------------------------------- FBOs
    def acquire_fbo(self, w: int, h: int) -> moderngl.Framebuffer:
        pool = self._free.setdefault((w, h), [])
        if pool:
            fbo = pool.pop()
        else:
            tex = self.ctx.texture((w, h), 4, dtype="f1")
            tex.repeat_x = tex.repeat_y = False
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            fbo = self.ctx.framebuffer(color_attachments=[tex])
        self._in_use.add(id(fbo))
        return fbo

    def release_fbo(self, fbo: moderngl.Framebuffer) -> None:
        i = id(fbo)
        if i not in self._in_use:
            return
        self._in_use.discard(i)
        size = (fbo.width, fbo.height)
        self._free.setdefault(size, []).append(fbo)

    @contextmanager
    def fbo(self, w: int, h: int):
        f = self.acquire_fbo(w, h)
        try:
            yield f
        finally:
            self.release_fbo(f)

    # ------------------------------------------------------------ textures
    def texture_from_array(self, arr: np.ndarray) -> moderngl.Texture:
        """Upload an ``(H, W, 3|4)`` uint8 array as a GL texture (top row first).

        Pooled + rewritten in place; a 3-channel source stays 3-channel (GLSL
        reads ``.a`` as 1.0). No mipmaps - the sample/region shaders filter
        LINEAR only, and the earlier ``build_mipmaps`` call was ~15ms/frame of
        pure waste on a 1440p source frame.
        """
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        arr = np.ascontiguousarray(arr)
        h, w, c = arr.shape
        c = 4 if c >= 4 else 3

        key = (w, h, c)
        pool = self._tex_free.setdefault(key, [])
        tex = pool.pop() if pool else None
        if tex is None:
            tex = self.ctx.texture((w, h), c, dtype="f1")
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
        tex.write(arr)
        self._tex_in_use[id(tex)] = tex
        return tex

    def release_texture(self, tex: moderngl.Texture) -> None:
        if self._tex_in_use.pop(id(tex), None) is None:
            return
        key = (tex.width, tex.height, tex.components)
        self._tex_free.setdefault(key, []).append(tex)

    def release(self) -> None:
        for pool in self._free.values():
            for fbo in pool:
                for a in fbo.color_attachments:
                    a.release()
                fbo.release()
        self._free.clear()
        for pool in self._tex_free.values():
            for t in pool:
                t.release()
        self._tex_free.clear()
        for t in list(self._tex_in_use.values()):
            t.release()
        self._tex_in_use.clear()
        for prog in self._programs.values():
            prog.release()
        self._programs.clear()
        try:
            self.ctx.release()
        except Exception:  # noqa: BLE001
            pass
