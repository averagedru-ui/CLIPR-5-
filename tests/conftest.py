"""Shared fixtures: synthetic media generated with the vendored ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vcomp.util import paths

_FF = paths.ffmpeg_exe()
_ffmpeg_missing = not _FF.exists()
requires_ffmpeg = pytest.mark.skipif(_ffmpeg_missing, reason="vendored ffmpeg missing")


@pytest.fixture(scope="session")
def gl_ctx():
    """One shared standalone GL context for the whole test session.

    Multiple ``moderngl`` standalone contexts in a single process fight over the
    current context, so every GL test must go through this.
    """
    try:
        from vcomp.render.context import RenderContext
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"moderngl unavailable: {exc}")
    try:
        return RenderContext()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable GL context: {exc}")


@pytest.fixture(scope="session")
def compositor(gl_ctx):
    from vcomp.render.compositor import Compositor

    return Compositor(gl_ctx)


def _run(args: list[str]) -> None:
    subprocess.run([str(_FF), "-y", "-hide_banner", "-loglevel", "error", *args],
                   check=True, capture_output=True)


@pytest.fixture(scope="session")
def cfr_clip(tmp_path_factory) -> Path:
    """3 s, 320x180, constant 30 fps, with a 1 kHz tone starting at t=1.0 s."""
    if _ffmpeg_missing:
        pytest.skip("vendored ffmpeg missing")
    out = tmp_path_factory.mktemp("media") / "cfr.mp4"
    _run([
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-filter_complex", "[1:a]adelay=1000|1000[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "3", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def cfr8_clip(tmp_path_factory) -> Path:
    """8 s CFR clip with audio, for the deadlock regression test."""
    if _ffmpeg_missing:
        pytest.skip("vendored ffmpeg missing")
    out = tmp_path_factory.mktemp("media") / "cfr8.mp4"
    _run([
        "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=30:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "8", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def vfr_clip(tmp_path_factory) -> Path:
    """Variable frame rate clip: two segments at 30 and 60 fps spliced with
    ``-c copy`` so frame durations change mid-stream (avg_rate != base_rate)."""
    if _ffmpeg_missing:
        pytest.skip("vendored ffmpeg missing")
    d = tmp_path_factory.mktemp("media")
    a, b, out = d / "a.mp4", d / "b.mp4", d / "vfr.mp4"
    _run(["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=1",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(a)])
    _run(["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=60:duration=1",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(b)])
    lst = d / "list.txt"
    lst.write_text(f"file '{a.as_posix()}'\nfile '{b.as_posix()}'\n")
    _run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
          "-fflags", "+genpts", str(out)])
    return out
