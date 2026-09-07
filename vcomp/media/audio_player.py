"""Timeline audio playback.

Decodes the currently-active audio tracks (OBS multi-track: un-muted / solo'd),
resamples + mixes them to one 48 kHz stereo int16 buffer, and streams it through
a ``QAudioSink`` - so it plays out the default output device and shows up in the
Windows volume mixer as CLIPR. Playback is wall-clock, matching the video loop.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QIODevice, QObject, QThread, QTimer, Signal

log = logging.getLogger("vcomp.audio")

_SR = 48000
_CH = 2


class _DecodeWorker(QObject):
    done = Signal(object)     # np.int16 (N, 2) or None

    def __init__(self, path: str, tracks: list[int]) -> None:
        super().__init__()
        self._path = path
        self._tracks = tracks

    def run(self) -> None:
        try:
            self.done.emit(self._decode())
        except Exception:  # noqa: BLE001
            log.exception("audio decode failed")
            self.done.emit(None)

    def _decode(self):
        import av

        mixes = []
        with av.open(self._path) as c:
            streams = c.streams.audio
            want = [streams[i] for i in self._tracks if i < len(streams)]
            if not want:
                return None
            for st in want:
                st.thread_type = "AUTO"
            resamplers = {
                st.index: av.AudioResampler(format="s16", layout="stereo", rate=_SR)
                for st in want
            }
            per = {st.index: [] for st in want}
            for packet in c.demux(*want):
                si = packet.stream.index
                if si not in per or packet.dts is None:
                    continue
                for frame in packet.decode():
                    for out in resamplers[si].resample(frame):
                        per[si].append(out.to_ndarray().reshape(-1, _CH))
        for idx, chunks in per.items():
            if chunks:
                mixes.append(np.concatenate(chunks, axis=0).astype(np.int32))
        if not mixes:
            return None
        n = max(m.shape[0] for m in mixes)
        acc = np.zeros((n, _CH), np.int32)
        for m in mixes:
            acc[: m.shape[0]] += m
        np.clip(acc, -32768, 32767, out=acc)
        return acc.astype(np.int16)


class AudioPlayer(QObject):
    loaded = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: str | None = None
        self._active: list[int] = [0]
        self._mix: np.ndarray | None = None      # (N, 2) int16 @ 48k
        self._sink = None
        self._io: QIODevice | None = None
        self._cursor = 0                          # sample offset into _mix
        self._muted = False
        self._enabled = True

        self._feed = QTimer(self)
        self._feed.setInterval(15)
        self._feed.timeout.connect(self._pump)

        self._thr: QThread | None = None
        self._worker: _DecodeWorker | None = None

    # ------------------------------------------------------------------ api
    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        if not on:
            self.stop()

    def load(self, path: str, active: list[int]) -> None:
        self._path = path
        self._active = list(active) or [0]
        self._mix = None
        self._decode()

    def set_active_tracks(self, active: list[int]) -> None:
        active = list(active) or [0]
        if set(active) == set(self._active):
            return
        self._active = active
        playing = self._feed.isActive()
        at = self._cursor / _SR
        self._mix = None
        self._decode(resume=(at if playing else None))

    def play(self, start_sec: float) -> None:
        if not self._enabled or self._mix is None:
            return
        self._start_stream(int(max(0.0, start_sec) * _SR))

    def stop(self) -> None:
        self._feed.stop()
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:  # noqa: BLE001
                pass
        self._sink = None
        self._io = None

    def release(self) -> None:
        self.stop()
        if self._thr is not None:
            self._thr.quit()
            self._thr.wait(1500)

    # -------------------------------------------------------------- internal
    def _decode(self, resume: float | None = None) -> None:
        if not self._path:
            return
        if self._thr is not None:
            self._thr.quit()
            self._thr.wait(1500)
        self._thr = QThread(self)
        self._worker = _DecodeWorker(self._path, list(self._active))
        self._worker.moveToThread(self._thr)
        self._thr.started.connect(self._worker.run)

        def _got(mix) -> None:
            self._mix = mix
            self._thr.quit()
            self.loaded.emit()
            if resume is not None and mix is not None:
                self.play(resume)

        self._worker.done.connect(_got)
        self._thr.start()

    def _start_stream(self, sample_offset: int) -> None:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self.stop()
        self._cursor = max(0, min(sample_offset, len(self._mix)))
        fmt = QAudioFormat()
        fmt.setSampleRate(_SR)
        fmt.setChannelCount(_CH)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dev = QMediaDevices.defaultAudioOutput()
        if dev is None or not dev.isFormatSupported(fmt):
            log.warning("no audio output / unsupported format")
            return
        self._sink = QAudioSink(dev, fmt, self)
        self._sink.setBufferSize(_SR * _CH * 2 // 5)   # ~0.2 s
        self._io = self._sink.start()
        self._feed.start()
        self._pump()

    def _pump(self) -> None:
        if self._io is None or self._sink is None or self._mix is None:
            return
        free = self._sink.bytesFree()
        if free <= 0:
            return
        want_samples = free // (_CH * 2)
        end = min(self._cursor + want_samples, len(self._mix))
        if end <= self._cursor:
            self._feed.stop()                 # ran out - playback loop will restart us
            return
        chunk = self._mix[self._cursor:end]
        if self._muted:
            chunk = np.zeros_like(chunk)
        self._io.write(chunk.tobytes())
        self._cursor = end
