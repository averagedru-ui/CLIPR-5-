"""Background frame decoding for the source viewport.

A ``FrameFetcher`` owns the :class:`VideoDecoder` on a worker thread. The UI
posts frame-index requests; only the most recent pending request is honoured
(coalescing), so scrubbing and playback stay responsive even when decode can't
keep up with real time.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, QWaitCondition, Signal

from vcomp.media.decoder import VideoDecoder
from vcomp.media.probe import MediaInfo

log = logging.getLogger("vcomp.fetcher")


class FrameFetcher(QObject):
    frameReady = Signal(int, object)   # index, RGB24 numpy array
    opened = Signal(object)                # MediaInfo
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread = QThread()
        self._thread.setObjectName("FrameFetcher")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._loop)

        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending: int | None = None
        self._open_path: str | None = None
        self._running = True
        self._decoder: VideoDecoder | None = None

    # -------------------------------------------------------------- public API
    def start(self) -> None:
        self._thread.start()

    def open(self, path: str) -> None:
        self._mutex.lock()
        self._open_path = path
        self._cond.wakeAll()
        self._mutex.unlock()

    def request(self, index: int) -> None:
        self._mutex.lock()
        self._pending = index
        self._cond.wakeAll()
        self._mutex.unlock()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._cond.wakeAll()
        self._mutex.unlock()
        self._thread.quit()
        self._thread.wait(2000)

    @property
    def info(self) -> MediaInfo | None:
        return self._decoder.info if self._decoder else None

    def cached_indices(self) -> set[int]:
        return self._decoder.cached_indices() if self._decoder else set()

    # ------------------------------------------------------------------- loop
    def _loop(self) -> None:
        while True:
            self._mutex.lock()
            while self._running and self._pending is None and self._open_path is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            path = self._open_path
            self._open_path = None
            index = self._pending
            self._pending = None
            self._mutex.unlock()

            if path is not None:
                self._do_open(path)
            if index is not None and self._decoder is not None:
                self._do_decode(index)

        if self._decoder is not None:
            self._decoder.close()

    def _do_open(self, path: str) -> None:
        try:
            if self._decoder is not None:
                self._decoder.close()
            self._decoder = VideoDecoder(path)
            log.info("opened %s (%dx%d @ %.3ffps, vfr=%s)", path,
                     self._decoder.info.width, self._decoder.info.height,
                     self._decoder.info.fps, self._decoder.info.is_vfr)
            self.opened.emit(self._decoder.info)
        except Exception as exc:  # noqa: BLE001 - surfaced in UI
            log.exception("open failed")
            self.failed.emit(str(exc))

    def _do_decode(self, index: int) -> None:
        try:
            arr = self._decoder.frame_at(self._decoder.index_to_time(index))
            self.frameReady.emit(index, arr)
        except Exception as exc:  # noqa: BLE001
            log.exception("decode failed")
            self.failed.emit(str(exc))
