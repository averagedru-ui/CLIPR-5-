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
        self._open_rotation: int | None = None
        self._running = True
        self._decoder: VideoDecoder | None = None
        self._readahead = 0        # frames to decode past the playhead while playing
        self._last_index = -1      # latest frame the UI actually asked for (playhead)
        self._warm_to = -1         # highest index the readahead has decoded to

    # -------------------------------------------------------------- public API
    def start(self) -> None:
        self._thread.start()

    def open(self, path: str, rotation: int | None = None) -> None:
        self._mutex.lock()
        self._open_path = path
        self._open_rotation = rotation
        self._cond.wakeAll()
        self._mutex.unlock()

    def request(self, index: int) -> None:
        self._mutex.lock()
        self._pending = index
        self._cond.wakeAll()
        self._mutex.unlock()

    def set_readahead(self, n: int) -> None:
        """While playing, decode this many frames past the latest request into
        the decoder's cache so the next request returns without a decode stall."""
        self._mutex.lock()
        self._readahead = max(0, int(n))
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
            while (self._running and self._pending is None and self._open_path is None
                   and not self._can_readahead()):
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            path = self._open_path
            rotation = self._open_rotation
            self._open_path = None
            index = self._pending
            self._pending = None
            span = self._readahead
            self._mutex.unlock()

            if path is not None:
                self._do_open(path, rotation)
            if index is not None and self._decoder is not None:
                self._last_index = index
                if index > self._warm_to:
                    self._warm_to = index
                self._do_decode(index)
            elif span and self._decoder is not None and self._last_index >= 0:
                self._warm_next(span)

        if self._decoder is not None:
            self._decoder.close()

    def _can_readahead(self) -> bool:
        return bool(self._readahead and self._decoder is not None
                    and self._last_index >= 0
                    and self._warm_to < self._last_index + self._readahead)

    def _warm_next(self, span: int) -> None:
        """Decode the next not-yet-cached frame in (playhead, playhead+span]."""
        try:
            total = self._decoder.frame_count or (self._last_index + span + 1)
            hi = min(self._last_index + span, total - 1)
            cached = self._decoder.cached_indices()
            n = self._warm_to + 1
            while n <= hi:
                if n not in cached:
                    self._decoder.frame_at(self._decoder.index_to_time(n))
                    self._warm_to = n
                    return
                n += 1
            self._warm_to = hi
        except Exception:  # noqa: BLE001
            log.exception("readahead decode failed")

    def _do_open(self, path: str, rotation: int | None = None) -> None:
        try:
            if self._decoder is not None:
                self._decoder.close()
            self._decoder = VideoDecoder(path, rotation=rotation)
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
