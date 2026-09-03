"""QUndoCommand wrappers around core :class:`Graph` mutations.

Core stays Qt-free; undo/redo lives here (spec 3 lists commands.py under core/,
but the working agreement forbids Qt in core/ — this is the agreed resolution).
"""
from __future__ import annotations

from typing import Any

from PySide6.QtGui import QUndoCommand

from vcomp.core.graph import Connection, Graph


class SetParamCmd(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, name: str, new: Any, *, text: str = ""):
        super().__init__(text or f"Set {name}")
        self._g = graph
        self._nid = node_id
        self._name = name
        self._new = new
        self._old = graph.nodes[node_id].params[name].value
        self._merge_id = hash((node_id, name)) & 0x7FFFFFFF

    def id(self) -> int:            # enables coalescing of drag streams
        return self._merge_id

    def mergeWith(self, other: "QUndoCommand") -> bool:
        if isinstance(other, SetParamCmd) and other._merge_id == self._merge_id:
            self._new = other._new
            return True
        return False

    def redo(self) -> None:
        self._g.set_param(self._nid, self._name, self._new)

    def undo(self) -> None:
        self._g.set_param(self._nid, self._name, self._old)


class SetParamsCmd(QUndoCommand):
    """Set several params on one node as a single, coalescing undo entry.

    Used where one gesture changes multiple params together (e.g. dragging a
    polygon vertex updates both ``polygon_points`` and the ``source_rect``
    bounding box)."""

    def __init__(self, graph: Graph, node_id: str, values: dict[str, Any], *, text: str = ""):
        super().__init__(text or "Edit")
        self._g = graph
        self._nid = node_id
        self._new = dict(values)
        self._old = {k: graph.nodes[node_id].params[k].value for k in values}
        self._merge_id = hash((node_id, tuple(sorted(values)))) & 0x7FFFFFFF

    def id(self) -> int:
        return self._merge_id

    def mergeWith(self, other: "QUndoCommand") -> bool:
        if isinstance(other, SetParamsCmd) and other._merge_id == self._merge_id:
            self._new = other._new
            return True
        return False

    def redo(self) -> None:
        for k, v in self._new.items():
            self._g.set_param(self._nid, k, v)

    def undo(self) -> None:
        for k, v in self._old.items():
            self._g.set_param(self._nid, k, v)


class SetEnabledCmd(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str, on: bool):
        super().__init__("Enable node" if on else "Disable node")
        self._g, self._nid, self._on = graph, node_id, on
        self._old = graph.nodes[node_id].enabled

    def redo(self) -> None:
        self._g.set_enabled(self._nid, self._on)

    def undo(self) -> None:
        self._g.set_enabled(self._nid, self._old)


class AddNodeCmd(QUndoCommand):
    def __init__(self, graph: Graph, type_name: str, node_id: str):
        super().__init__(f"Add {type_name}")
        self._g, self._type, self._nid = graph, type_name, node_id

    def redo(self) -> None:
        if self._nid not in self._g.nodes:
            self._g.add_node(self._type, node_id=self._nid)

    def undo(self) -> None:
        self._g.remove_node(self._nid)


class RemoveNodeCmd(QUndoCommand):
    def __init__(self, graph: Graph, node_id: str):
        super().__init__("Remove node")
        self._g = graph
        self._nid = node_id
        self._snapshot = graph.nodes[node_id].to_dict()
        self._conns = [c for c in graph.connections
                       if node_id in (c.from_node, c.to_node)]

    def redo(self) -> None:
        self._g.remove_node(self._nid)

    def undo(self) -> None:
        node = self._g.add_node(self._snapshot["type"], node_id=self._nid)
        node.load_dict(self._snapshot)
        for c in self._conns:
            try:
                self._g.connect(c.from_node, c.from_port, c.to_node, c.to_port)
            except Exception:  # noqa: BLE001
                pass


class ReplaceGraphCmd(QUndoCommand):
    """Whole-graph swap as one undo entry (template apply, new project)."""

    def __init__(self, graph: Graph, new_dict: dict, *, text: str = "Apply template"):
        super().__init__(text)
        self._g = graph
        self._before = graph.to_dict()
        self._after = new_dict

    def redo(self) -> None:
        self._g.load_dict(self._after)

    def undo(self) -> None:
        self._g.load_dict(self._before)


class ConnectCmd(QUndoCommand):
    def __init__(self, graph: Graph, conn: Connection):
        super().__init__("Connect")
        self._g, self._c = graph, conn

    def redo(self) -> None:
        self._g.connect(self._c.from_node, self._c.from_port,
                        self._c.to_node, self._c.to_port)

    def undo(self) -> None:
        self._g.disconnect(self._c)


class DisconnectCmd(QUndoCommand):
    def __init__(self, graph: Graph, conn: Connection):
        super().__init__("Disconnect")
        self._g, self._c = graph, conn

    def redo(self) -> None:
        self._g.disconnect(self._c)

    def undo(self) -> None:
        self._g.connect(self._c.from_node, self._c.from_port,
                        self._c.to_node, self._c.to_port)
