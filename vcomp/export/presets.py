"""Export presets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExportPreset:
    name: str
    width: int
    height: int
    fps: int
    crf: int            # libx264 quality (lower = better)
    audio_bitrate: str = "192k"


PRESETS: dict[str, ExportPreset] = {
    "TikTok": ExportPreset("TikTok", 1080, 1920, 30, 20),
    "Reels": ExportPreset("Reels", 1080, 1920, 30, 20),
    "Shorts": ExportPreset("Shorts", 1080, 1920, 60, 20),
}


def default_preset() -> ExportPreset:
    return PRESETS["TikTok"]
