"""Filesystem path resolution for VCOMP.

Works both in a normal dev checkout and inside a PyInstaller ``--onedir`` bundle
(where bundled data lives under ``sys._MEIPASS``). Nothing here touches the
network or relies on a tool being on ``PATH``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VCOMP"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_root() -> Path:
    """Directory that contains bundled read-only resources.

    In a frozen build this is ``sys._MEIPASS``; in dev it is the repo root
    (the parent of the ``vcomp`` package).
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource, e.g. ``resource_path("vcomp", "render", "shaders")``."""
    return resource_root().joinpath(*parts)


def ffmpeg_dir() -> Path:
    """Directory holding the vendored ``ffmpeg.exe`` / ``ffprobe.exe``."""
    return resource_path("vendor", "ffmpeg")


def ffmpeg_exe() -> Path:
    return ffmpeg_dir() / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")


def ffprobe_exe() -> Path:
    return ffmpeg_dir() / ("ffprobe.exe" if os.name == "nt" else "ffprobe")


def appdata_dir() -> Path:
    """Per-user writable directory: ``%APPDATA%/VCOMP`` (or XDG equivalent).

    Created on first access.
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str) -> Path:
    d = appdata_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    return _sub("logs")


def autosave_dir() -> Path:
    return _sub("autosave")


def templates_dir() -> Path:
    return _sub("templates")


def settings_file() -> Path:
    return appdata_dir() / "settings.json"
