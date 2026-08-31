"""M3: NodeGraphQt <-> core graph bridge + undo."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1",
                                reason="GUI disabled")


@pytest.fixture()
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_bridge_add_connect_undo(app):
    from PySide6.QtGui import QUndoStack

    from vcomp.core.graph import Graph, build_default_graph
    from vcomp.nodes.registry import load_builtin_nodes
    from vcomp.ui.node_canvas import NodeCanvas

    load_builtin_nodes()
    g = Graph()
    build_default_graph(g)
    undo = QUndoStack()
    canvas = NodeCanvas(g, undo)
    canvas.sync_from_core()

    n0 = len(g.nodes)
    cid = canvas.add_node_by_type("Value")
    assert cid in g.nodes and len(g.nodes) == n0 + 1

    undo.undo()
    assert cid not in g.nodes
    undo.redo()
    assert cid in g.nodes


def test_param_change_is_undoable(app):
    from PySide6.QtGui import QUndoStack

    from vcomp.core.graph import Graph, build_default_graph
    from vcomp.nodes.registry import load_builtin_nodes
    from vcomp.ui.commands import SetParamCmd

    load_builtin_nodes()
    g = Graph()
    build_default_graph(g)
    undo = QUndoStack()
    out = g.output_node().id

    undo.push(SetParamCmd(g, out, "canvas_width", 720))
    assert g.nodes[out].params["canvas_width"].value == 720
    undo.undo()
    assert g.nodes[out].params["canvas_width"].value == 1080
