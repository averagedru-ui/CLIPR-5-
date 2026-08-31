"""Media metadata.

Spec calls for ``ffprobe``; until a vendored ``ffprobe.exe`` is in place we read
the same facts through PyAV (which is already a hard dependency for decoding).
``probe_ffprobe`` is kept for when the binary lands and gives a second opinion on
VFR sources.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av

from vcomp.util import paths


@dataclass(frozen=True)
class MediaInfo:
    path: str
    width: int
    height: int
    fps: float                 # nominal constant frame rate (best guess)
    duration: float            # seconds
    frame_count: int           # estimated (duration * fps) when container is silent
    has_audio: bool
    pix_fmt: str
    is_vfr: bool
    time_base: Fraction        # video stream time base

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0


def probe(path: str | Path) -> MediaInfo:
    path = str(path)
    with av.open(path) as c:
        if not c.streams.video:
            raise ValueError(f"No video stream in {path!r}")
        v = c.streams.video[0]

        avg = v.average_rate or v.guessed_rate or Fraction(30, 1)
        base = v.base_rate or avg
        fps = float(avg)
        is_vfr = bool(base and avg and abs(float(base) - float(avg)) > 0.01)

        duration = 0.0
        if v.duration is not None and v.time_base is not None:
            duration = float(v.duration * v.time_base)
        elif c.duration is not None:
            duration = float(c.duration) / av.time_base

        frame_count = v.frames or (int(round(duration * fps)) if duration else 0)

        has_audio = bool(c.streams.audio)
        pix_fmt = getattr(v.format, "name", "") or ""
        tb = v.time_base or Fraction(1, 1000)

    return MediaInfo(
        path=path,
        width=int(v.codec_context.width),
        height=int(v.codec_context.height),
        fps=fps,
        duration=duration,
        frame_count=int(frame_count),
        has_audio=has_audio,
        pix_fmt=pix_fmt,
        is_vfr=is_vfr,
        time_base=tb,
    )


def probe_ffprobe(path: str | Path) -> dict:
    """Raw ``ffprobe -show_streams -show_format`` JSON. Requires vendored ffprobe."""
    exe = paths.ffprobe_exe()
    if not exe.exists():
        raise FileNotFoundError(f"ffprobe not found at {exe}")
    out = subprocess.run(
        [str(exe), "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)
