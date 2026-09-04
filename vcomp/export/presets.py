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
    "TikTok / Reels (1080x1920)": ExportPreset("TikTok / Reels (1080x1920)", 1080, 1920, 30, 20),
    "Shorts 60fps (1080x1920)": ExportPreset("Shorts 60fps (1080x1920)", 1080, 1920, 60, 20),
    "High detail (1440x2560)": ExportPreset("High detail (1440x2560)", 1440, 2560, 30, 19),
    "High detail 60fps (1440x2560)": ExportPreset("High detail 60fps (1440x2560)", 1440, 2560, 60, 19),
}

# display order for the dropdown (excludes the legacy aliases below)
PRESET_ORDER = list(PRESETS)

# legacy keys kept so old projects / settings still resolve
PRESETS["TikTok"] = PRESETS["TikTok / Reels (1080x1920)"]
PRESETS["Reels"] = PRESETS["TikTok / Reels (1080x1920)"]
PRESETS["Shorts"] = PRESETS["Shorts 60fps (1080x1920)"]


def default_preset() -> ExportPreset:
    return PRESETS["TikTok"]
