"""Runs the moderngl compositor + graph evaluation on its own thread.

The GL context is thread-affine, so the :class:`Compositor` is created inside the
worker loop. Requests are coalesced (latest wins). The core graph is shared with
the GUI thread and guarded by its own lock.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from PySide6.QtCore import QMutex, QObject, QThread, QWaitCondition, Signal

log = logging.getLogger("vcomp.renderworker")

_CACHE_MAX_FRAMES = 1200      # hard cap on cached preview frames
_CACHE_MAX_BYTES = 3_500_000_000   # ~3.5 GB ceiling for the preview cache


class RenderWorker(QObject):
    frameComposited = Signal(int, object)   # index, RGBA numpy (canvas res)
    thumbsReady = Signal(object)            # {node_id: small RGBA}
    cacheState = Signal(set)                # frame indices currently in the preview cache
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._graph = None
        self._thread = QThread()
        self._thread.setObjectName("RenderWorker")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._loop)

        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._running = True
        self._pending: tuple | None = None
        self._comp = None
        self.preview_scale = 1.0
        self.last_render_ms = 0.0
        self.want_thumbs = False
        self.lock_full_quality = False
        self.playing = False
        self.target_ms = 33.0   # per-frame budget while playing (set from clip fps)
        self._fast_streak = 0
        self._slow_streak = 0

        # preview render cache: frame index -> full-res RGBA. Lets a looped
        # in/out range play back at real time after the first pass. Bumped
        # (and cleared) whenever the graph or render settings change.
        self._cache: "OrderedDict[int, object]" = OrderedDict()
        self._cache_bytes = 0
        self._cache_enabled = True
        self._cache_dirty_evt = False

    def set_graph(self, graph) -> None:
        self._graph = graph

    def invalidate_cache(self) -> None:
        """Drop every cached preview frame (graph / render settings changed)."""
        self._mutex.lock()
        self._cache.clear()
        self._cache_bytes = 0
        self._cache_dirty_evt = True
        self._mutex.unlock()

    def set_cache_enabled(self, on: bool) -> None:
        self._cache_enabled = bool(on)
        if not on:
            self.invalidate_cache()

    def start(self) -> None:
        self._thread.start()

    def submit(self, index: int, frames: dict, t: float) -> None:
        self._mutex.lock()
        self._pending = (index, frames, t)
        self._cond.wakeAll()
        self._mutex.unlock()

    def stop(self) -> None:
        if not self._thread.isRunning():
            return
        self._mutex.lock()
        self._running = False
        self._cond.wakeAll()
        self._mutex.unlock()
        self._thread.quit()
        self._thread.wait(3000)

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        try:
            from vcomp.render.compositor import Compositor

            self._comp = Compositor()
            self.ready.emit(self._comp.ctx.renderer_string)
        except Exception as exc:  # noqa: BLE001
            log.exception("compositor init failed")
            self.failed.emit(f"GL init failed: {exc}")
            return

        while True:
            self._mutex.lock()
            while self._running and self._pending is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            index, frames, t = self._pending
            self._pending = None
            dirty = self._cache_dirty_evt
            self._cache_dirty_evt = False
            cached = None
            if self._can_cache():
                cached = self._cache.get(index)
                if cached is not None:
                    self._cache.move_to_end(index)
            self._mutex.unlock()

            if dirty:
                self.cacheState.emit(set())
            if self._graph is None:
                continue
            if cached is not None:
                self.last_render_ms = 0.0
                self.frameComposited.emit(index, cached)
                continue
            try:
                self._render(index, frames, t)
            except Exception as exc:  # noqa: BLE001
                log.exception("composite failed")
                self.failed.emit(str(exc))

        self._comp.release()

    def _can_cache(self) -> bool:
        return (self._cache_enabled and self.playing and not self.want_thumbs
                and (self.lock_full_quality or self.preview_scale >= 1.0))

    def _store_cache(self, index: int, arr) -> None:
        self._mutex.lock()
        if index not in self._cache:
            self._cache[index] = arr
            self._cache_bytes += arr.nbytes
        else:
            self._cache.move_to_end(index)
        while (len(self._cache) > _CACHE_MAX_FRAMES
               or self._cache_bytes > _CACHE_MAX_BYTES) and len(self._cache) > 1:
            _, old = self._cache.popitem(last=False)
            self._cache_bytes -= old.nbytes
        keys = set(self._cache)
        self._mutex.unlock()
        self.cacheState.emit(keys)

    def _render(self, index: int, frames: dict, t: float) -> None:
        import time

        from vcomp.render.frame_pipeline import render_graph_frame

        # Skip node thumbnails while playing - they add a full extra readback per
        # node and are the main reason 9:16 playback stutters.
        thumbs: dict | None = {} if (self.want_thumbs and not self.playing) else None
        scale = 1.0 if self.lock_full_quality else self.preview_scale
        t0 = time.perf_counter()
        out = render_graph_frame(self._comp, self._graph, frames, t,
                                 render_scale=scale, thumbs=thumbs)
        self.last_render_ms = (time.perf_counter() - t0) * 1000.0
        self.frameComposited.emit(index, out)
        if thumbs:
            self.thumbsReady.emit(thumbs)
        if self._can_cache():
            self._store_cache(index, out)

        if self.lock_full_quality:
            return

        # NOTE: benchmarking showed rendering at render_scale < 1.0 is *slower*
        # than full res for this pipeline (full-size clip upload every frame +
        # FBO-pool thrash at odd sizes), so playback no longer drops resolution.
        # Only fall back if a frame is genuinely catastrophic.
        if self.last_render_ms > 80 and self.preview_scale > 0.5:
            self._slow_streak += 1
            if self._slow_streak >= 3:
                self.preview_scale = 0.5
                self._slow_streak = 0
        elif self.last_render_ms < 45 and self.preview_scale < 1.0:
            self._fast_streak += 1
            if self._fast_streak >= 4:
                self.preview_scale = 1.0
                self._fast_streak = 0
        else:
            self._fast_streak = self._slow_streak = 0
