"""M4: draw-to-create HUD Region + viewport edits are wired and undoable."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1",
                                reason="GUI disabled")


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    QApplication.instance() or QApplication([])
    w = MainWindow(Settings())
    yield w
    w.fetcher.stop()
    w.renderer.stop()
    w.close()


def test_create_region_wires_and_undoes(win):
    n0 = len(win.graph.nodes)
    win.source_view.createRegion.emit(0.02, 0.02, 0.30, 0.18)

    hud = [n for n in win.graph.nodes.values() if n.type_name == "HUD Region"]
    assert len(hud) == 1
    reg = hud[0]
    assert any(c.to_node == reg.id and c.to_port == "image" for c in win.graph.connections)
    assert any(c.from_node == reg.id for c in win.graph.connections)
    assert reg.params["source_rect"].value[2] == pytest.approx(0.30)

    win.undo_stack.undo()   # the "Create HUD Region" macro
    assert len(win.graph.nodes) == n0
    win.undo_stack.redo()
    assert len(win.graph.nodes) == n0 + 1


def test_viewport_rect_edit_is_undoable(win):
    win.source_view.createRegion.emit(0.1, 0.1, 0.2, 0.2)
    reg = [n for n in win.graph.nodes.values() if n.type_name == "HUD Region"][0]

    win.source_view.editRect.emit(reg.id, (0.3, 0.3, 0.25, 0.25), True)
    assert reg.params["source_rect"].value == (0.3, 0.3, 0.25, 0.25)

    win._selected_id = reg.id
    win.output_view.moveDest.emit(reg.id, 0.4, 0.6, True)
    assert reg.params["dest_x"].value == pytest.approx(0.4)
    assert reg.params["dest_y"].value == pytest.approx(0.6)
