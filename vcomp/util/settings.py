"""Application settings persisted as JSON in ``%APPDATA%/CLIPR/settings.json``.

Small, flat, forgiving: unknown keys are preserved, missing keys fall back to
``DEFAULTS``, and a corrupt file is backed up rather than crashing startup.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from vcomp.util import paths

log = logging.getLogger("vcomp.settings")

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "default_export_preset": "TikTok",
    "preview_scale": 0.5,
    "render_scale": 2.0,
    "recent_files": [],
    "window_layout": None,   # base64 QMainWindow.saveState()
    "window_geometry": None,
}


class Settings:
    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        f = paths.settings_file()
        if not f.exists():
            return
        try:
            loaded = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._data = {**DEFAULTS, **loaded}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Bad settings file (%s); backing up and using defaults", exc)
            try:
                f.rename(f.with_suffix(".json.bak"))
            except OSError:
                pass

    def save(self) -> None:
        try:
            paths.settings_file().write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            log.exception("Could not write settings file")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def add_recent_file(self, path: str, limit: int = 10) -> None:
        recent = [p for p in self._data.get("recent_files", []) if p != path]
        recent.insert(0, path)
        self._data["recent_files"] = recent[:limit]
