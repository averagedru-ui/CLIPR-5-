"""Runs the moderngl compositor on its own thread.

The GL context is thread-affine, so the :class:`Compositor` is created inside the
worker loop, never on the GUI thread. Requests are coalesced (latest wins).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QMutex, QObject, QThread, QWaitCondition, Signal

log = logging.getLogger("vcomp.renderworker")


class RenderWorker(QObject):
    frameComposited = Signal(int, object)   # index, RGBA numpy (canvas res)
    ready = Signal(str)                     # GL renderer string
    failed = Signal(str)

    def __init__(self, canvas_w: int = 1080, canvas_h: int = 1920) -> None:
        super().__init__()
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h

        self._thread = QThread()
        self._thread.setObjectName("RenderWorker")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._loop)

        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._running = True
        self._pending: tuple[int, object] | None = None
        self._comp = None

    def start(self) -> None:
        self._thread.start()

    def submit(self, index: int, source_rgb) -> None:
        self._mutex.lock()
        self._pending = (index, source_rgb)
        self._cond.wakeAll()
        self._mutex.unlock()

    def stop(self) -> None:
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
            index, src = self._pending
            self._pending = None
            self._mutex.unlock()

            try:
                out = self._comp.render_gameplay_on_solid(
                    src, self.canvas_w, self.canvas_h
                )
                self.frameComposited.emit(index, out)
            except Exception as exc:  # noqa: BLE001
                log.exception("composite failed")
                self.failed.emit(str(exc))

        self._comp.release()
