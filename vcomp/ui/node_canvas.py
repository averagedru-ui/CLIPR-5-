"""NodeGraphQt canvas bridged to the core :class:`Graph`.

Core graph is the source of truth. NodeGraphQt is the view/controller: user
gestures on the canvas are translated into undo commands that mutate the core
graph; :meth:`sync_from_core` rebuilds the canvas after load / template apply.
A ``_syncing`` guard blocks the feedback loop.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from NodeGraphQt import BaseNode, NodeGraph
from PySide6.QtCore import QObject, Signal

from vcomp.core.graph import Connection, Graph
from vcomp.nodes.registry import all_types, get as get_vtype
from vcomp.ui import commands as cmd

log = logging.getLogger("vcomp.canvas")

_IDENT = "vcomp"
_PFX = "vc_"   # NodeGraphQt reserves names like 'color', 'border_color', 'width'


def _clsname(type_name: str) -> str:
    return re.sub(r"\W", "", type_name.title().replace(" ", ""))


def _build_ngqt_classes() -> dict[str, type]:
    out: dict[str, type] = {}
    for vtype in all_types():
        probe = vtype("_probe")
        ins = [(p.name, p.multi) for p in probe.inputs]
        outs = [p.name for p in probe.outputs]
        props = {n: _jsonable(pm.default) for n, pm in probe.params.items()}
        cname = _clsname(vtype.type_name)

        def _init(self, _ins=ins, _outs=outs, _props=props):  # noqa: ANN001
            BaseNode.__init__(self)
            for name, multi in _ins:
                self.add_input(name, multi_input=multi)
            for name in _outs:
                self.add_output(name, multi_output=True)
            for name, val in _props.items():
                self.create_property(_PFX + name, val)

        cls = type(cname, (BaseNode,), {
            "__identifier__": _IDENT,
            "NODE_NAME": vtype.title_default,
            "__init__": _init,
        })
        out[f"{_IDENT}.{cname}"] = cls
    return out


def _jsonable(v):
    if isinstance(v, (tuple, list)):
        return ",".join(str(x) for x in v)
    return v


class NodeCanvas(QObject):
    nodeSelected = Signal(object)   # core node id or None
    status = Signal(str)

    def __init__(self, graph: Graph, undo_stack) -> None:
        super().__init__()
        self.core = graph
        self.undo = undo_stack
        self._syncing = False
        self._n2c: dict[str, str] = {}   # ngqt node id -> core id
        self._c2n: dict[str, object] = {}

        self.ng = NodeGraph()
        self._classes = _build_ngqt_classes()
        for cls in self._classes.values():
            self.ng.register_node(cls)
        self._vtype_by_ngtype = {
            ngt: vt for ngt, vt in zip(self._classes, all_types())
        }

        self.ng.port_connected.connect(self._on_port_connected)
        self.ng.port_disconnected.connect(self._on_port_disconnected)
        self.ng.nodes_deleted.connect(self._on_nodes_deleted)
        self.ng.property_changed.connect(self._on_property_changed)
        self.ng.node_selection_changed.connect(self._on_selection)

    @property
    def widget(self):
        return self.ng.widget

    # ------------------------------------------------------- core -> canvas
    def sync_from_core(self) -> None:
        self._syncing = True
        try:
            self.ng.clear_session()
            self._n2c.clear()
            self._c2n.clear()

            col = {}
            for i, (cid, node) in enumerate(self.core.nodes.items()):
                ngtype = f"{_IDENT}.{_clsname(node.type_name)}"
                x = 100 + 260 * col.get(node.category, 0)
                y = 80 + 150 * list(_CATS).index(node.category if node.category in _CATS else "Misc")
                col[node.category] = col.get(node.category, 0) + 1
                ng_node = self.ng.create_node(ngtype, name=node.title, pos=(x, y))
                for name, pm in node.params.items():
                    ng_node.set_property(_PFX + name, _jsonable(pm.value), push_undo=False)
                self._n2c[ng_node.id] = cid
                self._c2n[cid] = ng_node

            for c in self.core.connections:
                a = self._c2n.get(c.from_node)
                b = self._c2n.get(c.to_node)
                if a and b:
                    a.set_output(self._port_index(a, c.from_port, False),
                                 b.input(self._port_index(b, c.to_port, True)))
        finally:
            self._syncing = False

    @staticmethod
    def _port_index(ng_node, port_name: str, is_input: bool) -> int:
        ports = ng_node.input_ports() if is_input else ng_node.output_ports()
        for i, p in enumerate(ports):
            if p.name() == port_name:
                return i
        return 0

    # ------------------------------------------------------- canvas -> core
    def add_node_by_type(self, type_name: str) -> str:
        nid = self.core.new_id(type_name)
        self.undo.push(cmd.AddNodeCmd(self.core, type_name, nid))  # redo() adds it
        self.sync_from_core()
        return nid

    def _on_port_connected(self, in_port, out_port):
        if self._syncing:
            return
        try:
            src = self._n2c[out_port.node().id]
            dst = self._n2c[in_port.node().id]
            conn = Connection(src, out_port.name(), dst, in_port.name())
            self.core.connect(conn.from_node, conn.from_port, conn.to_node, conn.to_port)
            self.core.disconnect(conn)             # will be re-done by the command
            self.undo.push(cmd.ConnectCmd(self.core, conn))
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"connection rejected: {exc}")
            self._syncing = True
            try:
                in_port.disconnect_from(out_port)
            finally:
                self._syncing = False

    def _on_port_disconnected(self, in_port, out_port):
        if self._syncing:
            return
        try:
            src = self._n2c[out_port.node().id]
            dst = self._n2c[in_port.node().id]
            conn = Connection(src, out_port.name(), dst, in_port.name())
            self.undo.push(cmd.DisconnectCmd(self.core, conn))
        except Exception:  # noqa: BLE001
            log.exception("disconnect bridge failed")

    def _on_nodes_deleted(self, ngids):
        if self._syncing:
            return
        for ngid in ngids:
            cid = self._n2c.get(ngid)
            if cid is None or cid not in self.core.nodes:
                continue
            if not self.core.nodes[cid].deletable:
                self.status.emit("Output node cannot be deleted")
                self.sync_from_core()
                return
            self.undo.push(cmd.RemoveNodeCmd(self.core, cid))

    def _on_property_changed(self, ng_node, name, value):
        if self._syncing or not name.startswith(_PFX):
            return
        pname = name[len(_PFX):]
        cid = self._n2c.get(ng_node.id)
        if cid is None or pname not in self.core.nodes[cid].params:
            return
        param = self.core.nodes[cid].params[pname]
        parsed = _parse_like(param.value, value)
        if parsed == param.value:
            return
        self.undo.push(cmd.SetParamCmd(self.core, cid, pname, parsed))

    def _on_selection(self, *_):
        sel = self.ng.selected_nodes()
        cid = self._n2c.get(sel[0].id) if sel else None
        self.nodeSelected.emit(cid)

    def focus_core_node(self, cid: str) -> None:
        ng = self._c2n.get(cid)
        if ng:
            self.ng.clear_selection()
            ng.set_selected(True)
            try:
                self.ng.center_on([ng])
            except Exception:  # noqa: BLE001
                pass


_CATS = ("Input", "Framing", "Background", "Modify", "Composite", "Misc")


def _parse_like(reference, raw):
    if isinstance(reference, bool):
        return bool(raw) if not isinstance(raw, str) else raw.lower() in ("1", "true", "yes")
    if isinstance(reference, (tuple, list)):
        try:
            parts = [float(x) for x in str(raw).split(",")]
            return tuple(parts)
        except ValueError:
            return reference
    if isinstance(reference, int) and not isinstance(reference, bool):
        try:
            return int(round(float(raw)))
        except (TypeError, ValueError):
            return reference
    if isinstance(reference, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return reference
    return raw
