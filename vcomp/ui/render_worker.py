"""Runs the moderngl compositor + graph evaluation on its own thread.

The GL context is thread-affine, so the :class:`Compositor` is created inside the
worker loop. Requests are coalesced (latest wins). The core graph is shared with
the GUI thread and guarded by its own lock.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QMutex, QObject, QThread, QWaitCondition, Signal

log = logging.getLogger("vcomp.renderworker")


class RenderWorker(QObject):
    frameComposited = Signal(int, object)   # index, RGBA numpy (canvas res)
    thumbsReady = Signal(object)            # {node_id: small RGBA}
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

    def set_graph(self, graph) -> None:
        self._graph = graph

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
            self._mutex.unlock()

            if self._graph is None:
                continue
            try:
                self._render(index, frames, t)
            except Exception as exc:  # noqa: BLE001
                log.exception("composite failed")
                self.failed.emit(str(exc))

        self._comp.release()

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

        if self.lock_full_quality:
            return

        if self.playing:
            # Hold real-time: drop resolution fast when we blow the frame budget,
            # recover slowly once we have comfortable headroom.
            budget = max(16.0, self.target_ms)
            if self.last_render_ms > budget and self.preview_scale > 0.25:
                self._slow_streak += 1
                self._fast_streak = 0
                if self._slow_streak >= 2:
                    self.preview_scale = max(0.25, round(self.preview_scale - 0.25, 2))
                    self._slow_streak = 0
            elif self.last_render_ms < budget * 0.45 and self.preview_scale < 1.0:
                self._fast_streak += 1
                self._slow_streak = 0
                if self._fast_streak >= 12:
                    self.preview_scale = min(1.0, round(self.preview_scale + 0.25, 2))
                    self._fast_streak = 0
            else:
                self._fast_streak = self._slow_streak = 0
            return

        # paused / scrubbing: creep back toward full res when frames are cheap
        if self.last_render_ms < 22 and self.preview_scale < 1.0:
            self._fast_streak += 1
            if self._fast_streak >= 6:
                self.preview_scale = min(1.0, self.preview_scale * 2)
                self._fast_streak = 0
        else:
            self._fast_streak = 0
