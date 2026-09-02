"""M0 smoke tests: imports, path helpers, settings round-trip, headless window."""
from __future__ import annotations

import os

import pytest


def test_version_flag(capsys):
    import main

    assert main.main(["--version"]) == 0
    assert "CLIPR" in capsys.readouterr().out


def test_paths_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from vcomp.util import paths

    assert paths.appdata_dir().is_dir()
    assert paths.logs_dir().is_dir()
    assert paths.ffmpeg_exe().name.startswith("ffmpeg")


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from vcomp.util.settings import Settings

    s = Settings()
    s.set("preview_scale", 0.25)
    s.add_recent_file("C:/clip.mp4")
    s.save()

    s2 = Settings()
    assert s2.get("preview_scale") == 0.25
    assert s2.get("recent_files") == ["C:/clip.mp4"]
    assert s2.get("theme") == "dark"  # default preserved


@pytest.mark.skipif(
    os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI tests disabled"
)
def test_main_window_constructs(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    app = QApplication.instance() or QApplication([])
    win = MainWindow(Settings())
    assert win.windowTitle() == "CLIPR"
    assert win.dock_source is not None and win.dock_output is not None
    win.close()
