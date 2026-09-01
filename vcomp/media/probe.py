"""Media metadata.

Spec calls for ``ffprobe``; until a vendored ``ffprobe.exe`` is in place we read
the same facts through PyAV (which is already a hard dependency for decoding).
``probe_ffprobe`` is kept for when the binary lands and gives a second opinion on
VFR sources.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av

from vcomp.util import paths

_ROT_RE = re.compile(r"rotation of\s+(-?\d+(?:\.\d+)?)\s+degrees", re.I)
_ROTATE_TAG_RE = re.compile(r"\brotate\s*[:=]\s*(-?\d+)", re.I)


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
    rotation: int = 0          # container display rotation, degrees CW to view upright

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def display_width(self) -> int:
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation in (90, 270) else self.height


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
        meta_rotate = v.metadata.get("rotate", "")

    rotation = detect_rotation(path, meta_rotate)

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
        rotation=rotation,
    )


def detect_rotation(path: str, meta_rotate: str = "") -> int:
    """Container display rotation in degrees, normalised to {0, 90, 180, 270}
    clockwise (i.e. rotate the decoded frame this much to view it upright).

    Reads the display-matrix side data via the bundled ffmpeg; falls back to the
    legacy ``rotate`` metadata tag.
    """
    deg = None
    exe = paths.ffmpeg_exe()
    if exe.exists():
        try:
            out = subprocess.run([str(exe), "-hide_banner", "-i", str(path)],
                                 capture_output=True, text=True, timeout=15)
            m = _ROT_RE.search(out.stderr)
            if m:
                deg = float(m.group(1))
        except (OSError, subprocess.SubprocessError):
            deg = None
    if deg is None and meta_rotate:
        try:
            deg = float(meta_rotate)
        except ValueError:
            deg = None
    if deg is None:
        return 0
    # ffmpeg reports the CCW rotation baked into the stream; to display upright
    # the frame must be rotated clockwise by -deg.
    return int(round((-deg) % 360)) // 90 * 90 % 360


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
