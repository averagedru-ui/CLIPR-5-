"""Autosave + crash recovery.

Every ``INTERVAL`` seconds the current project is written to
``%APPDATA%/CLIPR/autosave/`` with a timestamped name; the newest ``KEEP`` are
retained. On startup :func:`pending_recovery` reports the newest autosave so the
app can offer to restore it.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from vcomp.util import paths

log = logging.getLogger("vcomp.autosave")

INTERVAL = 60.0
KEEP = 8


def _dir() -> Path:
    return paths.autosave_dir()


def write_autosave(project) -> Path | None:
    """Write the project to a fresh timestamped autosave. The write is atomic
    (temp file + os.replace) so a crash mid-write can never leave a truncated
    file that then breaks recovery."""
    try:
        d = _dir()
        name = f"autosave_{time.strftime('%Y%m%d_%H%M%S')}.vcproj"
        target = d / name
        tmp = d / (name + ".tmp")
        project.path = target
        payload = json.dumps(project.to_dict(), indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        _prune()
        return target
    except Exception:  # noqa: BLE001
        log.exception("autosave failed")
        return None


def _prune() -> None:
    d = _dir()
    for junk in d.glob("autosave_*.vcproj.tmp"):
        junk.unlink(missing_ok=True)
    files = sorted(d.glob("autosave_*.vcproj"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for stale in files[KEEP:]:
        stale.unlink(missing_ok=True)


def recoverable(max_age_hours: float = 72.0) -> list[Path]:
    """Autosaves newest-first, within the age window. The caller tries them in
    order so a single corrupt newest file doesn't sink recovery."""
    out = []
    for f in sorted(_dir().glob("autosave_*.vcproj"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        if (time.time() - f.stat().st_mtime) / 3600.0 <= max_age_hours:
            out.append(f)
    return out


def pending_recovery(max_age_hours: float = 72.0) -> Path | None:
    files = recoverable(max_age_hours)
    return files[0] if files else None


def clear_recovery() -> None:
    for f in _dir().glob("autosave_*.vcproj"):
        f.unlink(missing_ok=True)
    for f in _dir().glob("autosave_*.vcproj.tmp"):
        f.unlink(missing_ok=True)
