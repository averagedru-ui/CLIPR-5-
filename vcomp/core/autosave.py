"""Autosave + crash recovery.

Every ``INTERVAL`` seconds the current project is written to
``%APPDATA%/VCOMP/autosave/`` with a timestamped name; the newest ``KEEP`` are
retained. On startup :func:`pending_recovery` reports the newest autosave so the
app can offer to restore it.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from vcomp.util import paths

log = logging.getLogger("vcomp.autosave")

INTERVAL = 60.0
KEEP = 5


def _dir() -> Path:
    return paths.autosave_dir()


def write_autosave(project) -> Path | None:
    try:
        name = f"autosave_{time.strftime('%Y%m%d_%H%M%S')}.vcproj"
        target = _dir() / name
        project.save(target)
        _prune()
        return target
    except Exception:  # noqa: BLE001
        log.exception("autosave failed")
        return None


def _prune() -> None:
    files = sorted(_dir().glob("autosave_*.vcproj"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for stale in files[KEEP:]:
        stale.unlink(missing_ok=True)


def pending_recovery(max_age_hours: float = 48.0) -> Path | None:
    files = sorted(_dir().glob("autosave_*.vcproj"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if not files:
        return None
    newest = files[0]
    if (time.time() - newest.stat().st_mtime) / 3600.0 > max_age_hours:
        return None
    return newest


def clear_recovery() -> None:
    for f in _dir().glob("autosave_*.vcproj"):
        f.unlink(missing_ok=True)
