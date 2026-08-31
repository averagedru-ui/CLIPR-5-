"""M1: main window loads a clip and delivers frames through the fetcher."""
from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI tests disabled"
)


def _pump(app, predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_open_and_scrub(cfr_clip, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    app = QApplication.instance() or QApplication([])
    win = MainWindow(Settings())

    got: dict[int, tuple] = {}
    win.fetcher.frameReady.connect(lambda i, a: got.__setitem__(i, a.shape))

    win.fetcher.open(str(cfr_clip))
    assert _pump(app, lambda: win._info is not None), "clip never opened"
    assert win._info.frame_count > 0
    assert win.timeline.out_point == win._info.frame_count - 1

    for idx in (0, 40, 12):
        win.timeline.seek(idx)
        assert _pump(app, lambda i=idx: i in got), f"frame {idx} not delivered"
        assert got[idx] == (180, 320, 3)

    win.close()
    win.fetcher.stop()
