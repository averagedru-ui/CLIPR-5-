"""PyAV video decoder with frame-accurate seeking and an LRU frame cache.

Design rules (spec sections 1, 5.1, 9.5):
  * Frames are always resolved by **PTS in seconds**, never by counting frames.
    This is what makes VFR sources (OBS / ShadowPlay) behave.
  * The decoder exposes a virtual **constant-frame-rate** timeline: output frame
    index ``n`` maps to ``t = n / fps``; ``frame_at`` returns the source frame
    whose presentation time is nearest ``t``.
  * Decoded frames are cached RGB24 ``numpy`` arrays, keyed by CFR index, with a
    simple LRU bound.

Qt-free on purpose: this module is used by the render pipeline and by headless
CLI export.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from vcomp.media.probe import MediaInfo, probe

log = logging.getLogger("vcomp.decoder")


class VideoDecoder:
    def __init__(self, path: str | Path, cache_size: int = 96) -> None:
        self.info: MediaInfo = probe(path)
        self._path = str(path)
        self._cache_size = max(4, cache_size)
        self._cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._lock = threading.RLock()

        self._container = av.open(self._path)
        self._stream = self._container.streams.video[0]
        # Decode threads help a lot for 1080p60 scrubbing.
        self._stream.thread_type = "AUTO"
        self._tb: Fraction = self._stream.time_base or Fraction(1, 1000)
        self._start_time: float = 0.0
        if self._stream.start_time is not None:
            self._start_time = float(self._stream.start_time * self._tb)

        self._last_decoded_pts: float | None = None

    # ---------------------------------------------------------------- geometry
    @property
    def fps(self) -> float:
        return self.info.fps

    @property
    def frame_count(self) -> int:
        return self.info.frame_count

    def index_to_time(self, n: int) -> float:
        return n / self.fps if self.fps else 0.0

    def time_to_index(self, t: float) -> int:
        return int(round(t * self.fps)) if self.fps else 0

    # ------------------------------------------------------------------- cache
    def _cache_get(self, n: int) -> np.ndarray | None:
        with self._lock:
            arr = self._cache.get(n)
            if arr is not None:
                self._cache.move_to_end(n)
            return arr

    def _cache_put(self, n: int, arr: np.ndarray) -> None:
        with self._lock:
            self._cache[n] = arr
            self._cache.move_to_end(n)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def cached_indices(self) -> set[int]:
        with self._lock:
            return set(self._cache)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    # -------------------------------------------------------------------- read
    def frame_at(self, t: float) -> np.ndarray:
        """Return RGB24 ``(H, W, 3)`` uint8 for the CFR frame nearest time ``t``."""
        n = self.time_to_index(t)
        n = max(0, min(n, max(0, self.frame_count - 1))) if self.frame_count else max(0, n)
        cached = self._cache_get(n)
        if cached is not None:
            return cached
        arr = self._decode_nearest(self.index_to_time(n))
        self._cache_put(n, arr)
        return arr

    def frame_by_index(self, n: int) -> np.ndarray:
        return self.frame_at(self.index_to_time(n))

    # --------------------------------------------------------------- internals
    def _decode_nearest(self, target: float) -> np.ndarray:
        """Seek to just before ``target`` seconds and decode forward to it."""
        with self._lock:
            want_pts = target + self._start_time
            need_seek = (
                self._last_decoded_pts is None
                or want_pts < self._last_decoded_pts
                or want_pts - self._last_decoded_pts > 1.0
            )
            if need_seek:
                seek_ts = int((max(0.0, target)) / self._tb) + (self._stream.start_time or 0)
                self._container.seek(seek_ts, stream=self._stream, backward=True, any_frame=False)
                self._last_decoded_pts = None

            best: np.ndarray | None = None
            best_dt = float("inf")
            try:
                for frame in self._container.decode(self._stream):
                    if frame.pts is None:
                        continue
                    ftime = float(frame.pts * self._tb)
                    self._last_decoded_pts = ftime
                    dt = abs(ftime - want_pts)
                    if dt < best_dt:
                        best_dt = dt
                        best = frame.to_ndarray(format="rgb24")
                    if ftime >= want_pts:
                        break
            except (av.error.EOFError, StopIteration):
                pass

            if best is None:
                # Past EOF or empty demux window: reopen and grab the last frame.
                best = self._decode_last_frame()
            if best is None:
                raise RuntimeError(f"Could not decode any frame near t={target:.3f}s")
            return np.ascontiguousarray(best)

    def _decode_last_frame(self) -> np.ndarray | None:
        try:
            self._container.close()
        except Exception:  # noqa: BLE001
            pass
        self._container = av.open(self._path)
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        self._last_decoded_pts = None
        dur = self._container.duration or 0
        try:
            self._container.seek(max(0, dur - int(0.5 / self._tb)),
                                 stream=self._stream, backward=True)
        except av.error.FFmpegError:
            pass
        last = None
        try:
            for frame in self._container.decode(self._stream):
                last = frame.to_ndarray(format="rgb24")
                self._last_decoded_pts = float((frame.pts or 0) * self._tb)
        except (av.error.EOFError, StopIteration):
            pass
        return last

    def close(self) -> None:
        with self._lock:
            try:
                self._container.close()
            except Exception:  # noqa: BLE001
                log.exception("Error closing container")
            self._cache.clear()

    def __enter__(self) -> "VideoDecoder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
