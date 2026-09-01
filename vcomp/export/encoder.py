"""ffmpeg subprocess manager for export.

Frames are written as raw RGBA to ffmpeg stdin; audio is taken directly from the
source file (never re-decoded in Python). **stderr is drained on a separate
thread** or the pipe deadlocks on long exports (spec 9.2 - the single most common
bug in this design).
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from vcomp.util import paths

log = logging.getLogger("vcomp.encoder")


@dataclass
class EncoderOption:
    key: str
    label: str
    codec: str
    extra: list[str] = field(default_factory=list)


_ENCODER_TABLE = [
    EncoderOption("x264", "Quality (CPU, libx264)", "libx264",
                  ["-preset", "slow", "-crf", "18"]),
    EncoderOption("nvenc", "Fast (NVIDIA NVENC)", "h264_nvenc",
                  ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "20", "-b:v", "0"]),
    EncoderOption("amf", "Fast (AMD AMF)", "h264_amf",
                  ["-quality", "quality", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]),
    EncoderOption("qsv", "Fast (Intel QSV)", "h264_qsv", ["-global_quality", "20"]),
]


def detect_encoders(force: bool = False) -> list[EncoderOption]:
    cache = paths.appdata_dir() / "encoders.json"
    names: list[str] | None = None
    if cache.exists() and not force:
        try:
            names = json.loads(cache.read_text())
        except (json.JSONDecodeError, OSError):
            names = None
    if names is None:
        names = _query_encoders()
        try:
            cache.write_text(json.dumps(names))
        except OSError:
            pass
    present = [e for e in _ENCODER_TABLE if e.codec in names]
    return present or [_ENCODER_TABLE[0]]


def _query_encoders() -> list[str]:
    exe = paths.ffmpeg_exe()
    if not exe.exists():
        return ["libx264"]
    try:
        out = subprocess.run([str(exe), "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20)
        found = []
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith(("V", "A")) and len(parts[0]) == 6:
                found.append(parts[1])
        return found or ["libx264"]
    except (OSError, subprocess.SubprocessError):
        return ["libx264"]


@dataclass
class EncodeSpec:
    out_path: str
    width: int
    height: int
    fps: int
    encoder: EncoderOption
    crf: int = 18
    audio_bitrate: str = "192k"
    source_path: str | None = None      # for the audio stream
    in_point: float = 0.0
    out_point: float | None = None
    speed: float = 1.0


class FFmpegProcess:
    def __init__(self, spec: EncodeSpec) -> None:
        self.spec = spec
        self._proc: subprocess.Popen | None = None
        self._stderr_tail: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    def build_args(self) -> list[str]:
        s = self.spec
        exe = str(paths.ffmpeg_exe())
        args = [
            exe, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "rgba",
            "-video_size", f"{s.width}x{s.height}", "-framerate", str(s.fps),
            "-i", "pipe:0",
        ]
        have_audio = bool(s.source_path)
        if have_audio:
            args += ["-ss", f"{s.in_point}"]
            if s.out_point is not None:
                args += ["-to", f"{s.out_point}"]
            args += ["-i", s.source_path]

        args += ["-map", "0:v:0"]
        if have_audio:
            args += ["-map", "1:a:0?"]

        args += ["-c:v", s.encoder.codec, *s.encoder.extra]
        if s.encoder.codec == "libx264":
            args += ["-crf", str(s.crf)]
        args += [
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-profile:v", "high", "-level", "4.2",
        ]
        if have_audio:
            if abs(s.speed - 1.0) > 1e-3:
                args += ["-filter:a", _atempo_chain(s.speed)]
            args += ["-c:a", "aac", "-b:a", s.audio_bitrate, "-ar", "48000"]
        args += ["-movflags", "+faststart", "-shortest", s.out_path]
        return args

    def start(self) -> None:
        args = self.build_args()
        log.info("ffmpeg: %s", " ".join(args))
        self._proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, bufsize=0,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for raw in self._proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._stderr_tail.append(line)
                del self._stderr_tail[:-40]

    def write_frame(self, rgba_bytes: bytes) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(rgba_bytes)

    def finish(self, timeout: float = 60.0) -> int:
        if not self._proc:
            return -1
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        if self._stderr_thread:
            self._stderr_thread.join(timeout=2.0)
        return self._proc.returncode or 0

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except OSError:
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        Path(self.spec.out_path).unlink(missing_ok=True)

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._stderr_tail[-10:])


def _atempo_chain(speed: float) -> str:
    factors = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={f:.4f}" for f in factors)
