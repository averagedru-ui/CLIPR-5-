"""Per-audio-track waveform images, rendered by the bundled ffmpeg.

``showwavespic`` reads a whole audio stream and writes one transparent PNG - far
cheaper than decoding the audio in Python. Results are cached in the temp dir
keyed by (path, mtime, track, size) so re-opening a clip is instant.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from vcomp.util import paths

log = logging.getLogger("vcomp.waveform")

_W, _H = 1600, 60
_COLOR = "0x7fd9a0"


def _cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "clipr_waveforms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(path: str, track: int) -> Path:
    try:
        mtime = int(os.path.getmtime(path))
    except OSError:
        mtime = 0
    h = hashlib.sha1(f"{path}|{mtime}|{track}|{_W}x{_H}".encode()).hexdigest()[:16]
    return _cache_dir() / f"{h}.png"


def render_waveform(path: str, track: int) -> Path | None:
    """Blocking: return a PNG path for audio-stream ``track`` (0-based), or None."""
    out = _key(path, track)
    if out.exists() and out.stat().st_size > 0:
        return out
    exe = paths.ffmpeg_exe()
    if not exe.exists():
        return None
    args = [
        str(exe), "-y", "-hide_banner", "-loglevel", "error", "-i", path,
        "-filter_complex",
        f"[0:a:{track}]aformat=channel_layouts=mono,"
        f"showwavespic=s={_W}x{_H}:colors={_COLOR}",
        "-frames:v", "1", str(out),
    ]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
        log.warning("showwavespic track %d failed: %s", track, r.stderr[:300])
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("showwavespic track %d error: %s", track, exc)
    return None


class WaveformWorker(QObject):
    """Renders a list of tracks on a background thread, newest request wins."""

    ready = Signal(int, str)     # track index, png path

    def __init__(self) -> None:
        super().__init__()
        self._thread = QThread()
        self._thread.setObjectName("Waveform")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._path: str | None = None
        self._tracks: list[int] = []
        self._running = True

    def start(self) -> None:
        self._thread.start()

    def request(self, path: str, tracks: list[int]) -> None:
        self._path = path
        self._tracks = list(tracks)
        if not self._thread.isRunning():
            self.start()

    def stop(self) -> None:
        self._running = False
        self._thread.quit()
        self._thread.wait(2000)

    def _run(self) -> None:
        import time

        while self._running:
            path, tracks = self._path, list(self._tracks)
            if not path or not tracks:
                time.sleep(0.15)
                continue
            for t in tracks:
                if not self._running or self._path != path:
                    break
                png = render_waveform(path, t)
                if png is not None:
                    self.ready.emit(t, str(png))
            if self._path == path:
                self._tracks = []
