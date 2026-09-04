"""RenderWorker preview cache: gating, LRU trim, invalidation."""
from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI")


@pytest.fixture()
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _frame():
    return np.zeros((64, 36, 4), np.uint8)


def test_can_cache_gating(app):
    from vcomp.ui.render_worker import RenderWorker

    w = RenderWorker()
    assert not w._can_cache()          # not playing
    w.playing = True
    assert w._can_cache()
    w.preview_scale = 0.5
    assert not w._can_cache()          # reduced res -> don't cache
    w.preview_scale = 1.0
    w.want_thumbs = True
    assert not w._can_cache()          # thumbnails pass -> don't cache
    w.want_thumbs = False
    w.lock_full_quality = True
    w.preview_scale = 0.5
    assert w._can_cache()              # locked full quality overrides scale


def test_store_and_invalidate(app):
    from vcomp.ui.render_worker import RenderWorker

    w = RenderWorker()
    w.playing = True
    for i in range(5):
        w._store_cache(i, _frame())
    assert set(w._cache) == {0, 1, 2, 3, 4}
    assert w._cache_bytes == 5 * _frame().nbytes

    w.invalidate_cache()
    assert not w._cache and w._cache_bytes == 0


def test_lru_trim_by_frame_count(app, monkeypatch):
    from vcomp.ui import render_worker as rw

    monkeypatch.setattr(rw, "_CACHE_MAX_FRAMES", 3)
    w = rw.RenderWorker()
    w.playing = True
    for i in range(6):
        w._store_cache(i, _frame())
    assert set(w._cache) == {3, 4, 5}          # oldest evicted


def test_lru_trim_by_bytes(app, monkeypatch):
    from vcomp.ui import render_worker as rw

    monkeypatch.setattr(rw, "_CACHE_MAX_BYTES", _frame().nbytes * 2)
    w = rw.RenderWorker()
    w.playing = True
    for i in range(6):
        w._store_cache(i, _frame())
    assert len(w._cache) <= 2
