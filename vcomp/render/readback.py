"""FBO -> numpy readback.

``read_fbo`` is the simple synchronous path used by preview. ``PBOReadback``
double-buffers ``read_into`` calls so export can overlap GPU readback with the
next frame's compositing (one-frame latency); it is wired up in M6.

All results are returned **top row first** (the FBO is stored bottom-up).
"""
from __future__ import annotations

import moderngl
import numpy as np


def read_fbo(fbo: moderngl.Framebuffer, components: int = 4) -> np.ndarray:
    raw = fbo.read(components=components, dtype="f1")
    arr = np.frombuffer(raw, np.uint8).reshape(fbo.height, fbo.width, components)
    return np.flipud(arr).copy()


class PBOReadback:
    def __init__(self, ctx: moderngl.Context, w: int, h: int, components: int = 4):
        self.w, self.h, self.c = w, h, components
        self._bufs = [ctx.buffer(reserve=w * h * components) for _ in range(2)]
        self._i = 0
        self._primed = False

    def submit(self, fbo: moderngl.Framebuffer) -> np.ndarray | None:
        """Queue a readback of ``fbo``; return the PREVIOUS frame (or None on the
        first call)."""
        fbo.read_into(self._bufs[self._i], components=self.c, dtype="f1")
        prev = None
        if self._primed:
            j = 1 - self._i
            raw = self._bufs[j].read()
            prev = np.flipud(
                np.frombuffer(raw, np.uint8).reshape(self.h, self.w, self.c)
            ).copy()
        self._i = 1 - self._i
        self._primed = True
        return prev

    def flush(self) -> np.ndarray:
        """Return the last submitted frame (call once after the loop)."""
        j = 1 - self._i
        raw = self._bufs[j].read()
        return np.flipud(
            np.frombuffer(raw, np.uint8).reshape(self.h, self.w, self.c)
        ).copy()

    def release(self) -> None:
        for b in self._bufs:
            b.release()
