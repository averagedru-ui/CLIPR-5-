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
        from vcomp.render.frame_pipeline import render_graph_frame

        # preview always renders at 1x; export uses the Output render_scale
        out = render_graph_frame(self._comp, self._graph, frames, t, render_scale=1.0)
        self.frameComposited.emit(index, out)
