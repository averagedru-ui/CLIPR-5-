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

import numpy as np
from NodeGraphQt import BaseNode, NodeBaseWidget, NodeGraph
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import QLabel

from vcomp.core.graph import Connection, Graph
from vcomp.core.params import WireType
from vcomp.nodes.registry import all_types, get as get_vtype
from vcomp.ui import commands as cmd

log = logging.getLogger("vcomp.canvas")

_IDENT = "vcomp"
# NodeGraphQt ignores the app font; pick a real UI family (fallbacks for non-Win).
_NODE_FONT = "Segoe UI"
_PFX = "vc_"   # NodeGraphQt reserves names like 'color', 'border_color', 'width'

_WIRE_COLOR = {
    WireType.IMAGE: (80, 170, 255),
    WireType.NUMBER: (190, 190, 200),
    WireType.COLOR: (255, 210, 70),
    WireType.RECT: (255, 150, 55),
    WireType.AUDIO: (90, 230, 140),
}

# Vibrant per-category node body colours (kept saturated on purpose).
_CATEGORY_COLOR = {
    "Input": (0, 178, 214),        # cyan
    "Framing": (150, 82, 235),     # violet
    "Background": (58, 110, 245),  # blue
    "Modify": (214, 74, 178),      # magenta
    "Composite": (124, 66, 232),   # deep purple
    "Misc": (110, 96, 150),
}
_NODE_OVERRIDE = {
    "Output": (36, 196, 118),      # green
    "Clip Source": (0, 178, 214),
    "Key": (214, 74, 90),          # red
    "Guides": (214, 74, 90),
}


def _clsname(type_name: str) -> str:
    return re.sub(r"\W", "", type_name.title().replace(" ", ""))


_THUMB_W, _THUMB_H = 64, 114


class ThumbWidget(NodeBaseWidget):
    """A small live preview of a node's Image output, embedded in the node body."""

    def __init__(self, parent=None):
        # NodeBaseWidget.__init__(parent, name, label); `label` must stay a str -
        # do NOT shadow self._label with a QWidget (breaks set_custom_widget).
        super().__init__(parent, name="vc_thumb", label="")
        self._img = QLabel()
        self._img.setFixedSize(_THUMB_W, _THUMB_H)
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setStyleSheet("background:#0d0d10; border:1px solid #2a2a30;")
        self.set_custom_widget(self._img)

    def get_value(self):
        return ""

    def set_value(self, _v):
        pass

    def set_array(self, arr: np.ndarray) -> None:
        h, w = arr.shape[:2]
        img = QImage(np.ascontiguousarray(arr).data, w, h, 4 * w,
                     QImage.Format.Format_RGBA8888).copy()
        self._img.setPixmap(QPixmap.fromImage(img))

    def clear(self) -> None:
        self._img.clear()


def _build_ngqt_classes() -> dict[str, type]:
    out: dict[str, type] = {}
    for vtype in all_types():
        probe = vtype("_probe")
        ins = [(p.name, p.multi, _WIRE_COLOR.get(p.wire, (150, 150, 150))) for p in probe.inputs]
        outs = [(p.name, _WIRE_COLOR.get(p.wire, (150, 150, 150))) for p in probe.outputs]
        props = {n: _jsonable(pm.default) for n, pm in probe.params.items()}
        cname = _clsname(vtype.type_name)
        ncolor = _NODE_OVERRIDE.get(
            vtype.type_name, _CATEGORY_COLOR.get(vtype.category, (110, 96, 150)))
        has_img_out = any(p.wire == WireType.IMAGE for p in probe.outputs)

        def _init(self, _ins=ins, _outs=outs, _props=props, _col=ncolor,
                  _thumb=has_img_out):  # noqa: ANN001
            BaseNode.__init__(self)
            self.set_color(*_col)
            for name, multi, col in _ins:
                self.add_input(name, multi_input=multi, color=col)
            for name, col in _outs:
                self.add_output(name, multi_output=True, color=col)
            for name, val in _props.items():
                self.create_property(_PFX + name, val)
            if _thumb:
                try:
                    self.add_custom_widget(ThumbWidget(), tab="Node")
                except Exception:  # noqa: BLE001
                    log.exception("could not attach node preview widget")

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


class _CanvasPan(QObject):
    """Left-drag on empty canvas pans the view (works over RDP where MMB /
    scroll are unreliable). Drag that starts on a node/pipe is left alone."""

    def __init__(self, viewer) -> None:
        super().__init__(viewer)
        self._v = viewer
        self._on = False
        self._last = QPointF()

    def eventFilter(self, _obj, e) -> bool:  # noqa: N802
        v = self._v
        et = e.type()
        if et == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            if v.itemAt(e.position().toPoint()) is None:
                self._on = True
                self._last = e.position()
                v.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
        elif et == QEvent.Type.MouseMove and self._on:
            p0 = v.mapToScene(self._last.toPoint())
            p1 = v.mapToScene(e.position().toPoint())
            d = p0 - p1
            v._set_viewer_pan(d.x(), d.y())
            self._last = e.position()
            return True
        elif et == QEvent.Type.MouseButtonRelease and self._on:
            self._on = False
            v.unsetCursor()
            return True
        return False


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
        self._thumbs_visible = False

        self.ng = NodeGraph()
        try:
            self.ng.set_background_color(14, 16, 13)
            self.ng.set_grid_color(32, 38, 30)
            self.ng.set_grid_mode(1)          # dots
        except Exception:  # noqa: BLE001
            pass
        try:
            _viewer = self.ng.viewer()
            self._pan_filter = _CanvasPan(_viewer)
            _viewer.viewport().installEventFilter(self._pan_filter)
        except Exception:  # noqa: BLE001
            log.exception("could not install canvas pan filter")
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

    # ------------------------------------------------------------- thumbnails
    def _thumb_widget(self, ng_node):
        try:
            return ng_node.get_widget("vc_thumb")
        except Exception:  # noqa: BLE001
            return None

    def set_thumbs_visible(self, on: bool) -> None:
        self._thumbs_visible = bool(on)
        for ng in self._c2n.values():
            w = self._thumb_widget(ng)
            if w is None:
                continue
            w.setVisible(self._thumbs_visible)
            if not self._thumbs_visible:
                try:
                    w.clear()
                except Exception:  # noqa: BLE001
                    pass
            try:
                ng.view.draw_node()
            except Exception:  # noqa: BLE001
                pass

    def set_thumbs(self, thumbs: dict) -> None:
        if not self._thumbs_visible:
            return
        for cid, arr in thumbs.items():
            ng = self._c2n.get(cid)
            if ng is None:
                continue
            w = self._thumb_widget(ng)
            if w is not None:
                try:
                    w.set_array(arr)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------- core -> canvas
    def _layout_positions(self) -> dict[str, tuple[float, float]]:
        """Left-to-right layout: column = longest path to the Output node,
        rows stacked within a column, no overlaps."""
        nodes = self.core.nodes
        succ: dict[str, list[str]] = {n: [] for n in nodes}
        pred: dict[str, list[str]] = {n: [] for n in nodes}
        for c in self.core.connections:
            if c.from_node in nodes and c.to_node in nodes:
                succ[c.from_node].append(c.to_node)
                pred[c.to_node].append(c.from_node)

        # depth = longest chain from any source
        depth: dict[str, int] = {}

        def _depth(nid: str, seen: frozenset) -> int:
            if nid in depth:
                return depth[nid]
            if nid in seen or not pred[nid]:
                d = 0
            else:
                d = 1 + max(_depth(p, seen | {nid}) for p in pred[nid])
            depth[nid] = d
            return d

        for nid in nodes:
            _depth(nid, frozenset())

        # keep the Output node rightmost
        try:
            out_id = self.core.output_node().id
            others = [d for n, d in depth.items() if n != out_id]
            depth[out_id] = (max(others) + 1) if others else 0
        except Exception:  # noqa: BLE001
            pass

        cols: dict[int, list[str]] = {}
        for nid, d in sorted(depth.items(), key=lambda kv: (kv[1], nodes[kv[0]].category)):
            cols.setdefault(d, []).append(nid)

        dx, dy = 320, 170
        pos: dict[str, tuple[float, float]] = {}
        for d, ids in cols.items():
            for row, nid in enumerate(ids):
                pos[nid] = (80 + d * dx, 80 + row * dy)
        return pos

    def sync_from_core(self) -> None:
        self._syncing = True
        try:
            self.ng.clear_session()
            self._n2c.clear()
            self._c2n.clear()

            layout = self._layout_positions()
            for cid, node in self.core.nodes.items():
                ngtype = f"{_IDENT}.{_clsname(node.type_name)}"
                x, y = layout.get(cid, (100, 100))
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
        self._restyle_fonts()
        self.set_thumbs_visible(self._thumbs_visible)   # enforce hidden by default

    def _restyle_fonts(self) -> None:
        """Make node text legible. NodeGraphQt hardcodes a bare ``QFont()`` which
        resolves to the generic 'Sans Serif' alias (thin, ugly on Windows) at
        8pt with 40%-transparent white. Force a real UI family, bump size/weight,
        full-opacity cream."""
        title_f = QFont(_NODE_FONT, 12)
        title_f.setWeight(QFont.Weight.Bold)
        port_f = QFont(_NODE_FONT, 10)
        port_f.setWeight(QFont.Weight.DemiBold)
        for ng in self.ng.all_nodes():
            try:
                v = ng.view
                v.text_color = (245, 240, 230, 255)
                v._text_item.setFont(title_f)
                for _p, t in list(v._input_items.items()) + list(v._output_items.items()):
                    t.setFont(port_f)
                v.draw_node()
            except Exception:  # noqa: BLE001
                log.exception("restyle node fonts")

    @staticmethod
    def _port_index(ng_node, port_name: str, is_input: bool) -> int:
        ports = ng_node.input_ports() if is_input else ng_node.output_ports()
        for i, p in enumerate(ports):
            if p.name() == port_name:
                return i
        return 0

    # ------------------------------------------------------- canvas -> core
    def add_node_by_type(self, type_name: str, *, auto_wire: bool = True) -> str:
        nid = self.core.new_id(type_name)
        self.undo.beginMacro(f"Add {type_name}")
        self.undo.push(cmd.AddNodeCmd(self.core, type_name, nid))  # redo() adds it
        if auto_wire:
            self._auto_wire(nid, type_name)
        self.undo.endMacro()
        self.sync_from_core()
        return nid

    def _auto_wire(self, nid: str, type_name: str) -> None:
        """Best-effort connect a freshly added node into the existing graph."""
        vt = get_vtype(type_name)
        has_img_in = any(p.wire == WireType.IMAGE for p in vt("_p").inputs)
        has_img_out = any(p.wire == WireType.IMAGE for p in vt("_p").outputs)
        if not has_img_out:
            return

        clip = next((n for n in self.core.nodes.values()
                     if n.type_name == "Clip Source"), None)
        stack = next((n for n in self.core.nodes.values()
                      if n.type_name == "Stack"), None)
        multi = any(p.wire == WireType.IMAGE and p.multi for p in vt("_p").inputs)

        def _try(a, ap, b, bp):
            try:
                self.core.connect(a, ap, b, bp)
                self.core.disconnect(Connection(a, ap, b, bp))
                self.undo.push(cmd.ConnectCmd(self.core, Connection(a, ap, b, bp)))
                return True
            except Exception:  # noqa: BLE001
                return False

        in_port = next((p.name for p in vt("_p").inputs if p.wire == WireType.IMAGE), None)
        if has_img_in and in_port and clip:
            _try(clip.id, "image", nid, in_port if not multi else in_port)
        out_port = next(p.name for p in vt("_p").outputs if p.wire == WireType.IMAGE)
        if stack:
            _try(nid, out_port, stack.id, "layers")

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
