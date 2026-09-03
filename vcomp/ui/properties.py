"""Generic node inspector.

Builds widgets from :class:`Param` definitions of the selected core node. Edits
go through :class:`SetParamCmd` so everything is undoable. Grouped, collapsible
sections match the param ``group``.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vcomp.core.params import ParamType
from vcomp.ui import theme
from vcomp.ui.commands import SetEnabledCmd, SetParamCmd
from vcomp.ui.widgets import ScrubSlider


class PropertiesPanel(QWidget):
    def __init__(self, graph, undo_stack) -> None:
        super().__init__()
        self._graph = graph
        self._undo = undo_stack
        self._node_id: str | None = None

        self._widgets: dict[str, QWidget] = {}
        self._built_key = None

        self.setMinimumWidth(280)

        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._body_lay.setContentsMargins(10, 8, 12, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
        self.show_node(None)

    # ------------------------------------------------------------------ API
    def show_node(self, node_id: str | None) -> None:
        self._node_id = node_id
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if node_id is None or node_id not in self._graph.nodes:
            self._body_lay.addWidget(_dim("No node selected"))
            return

        node = self._graph.nodes[node_id]
        self._widgets = {}
        self._built_key = (node_id, tuple(node.params), node.type_name)
        header = QLabel(f"{node.title}  ·  {node.type_name}")
        header.setStyleSheet(f"font-weight:bold; color:{theme.TEXT};")
        self._body_lay.addWidget(header)

        if node.type_name == "Stack":
            self._build_stack_panel(node_id)
            return

        en = QCheckBox("enabled")
        en.setChecked(node.enabled)
        en.toggled.connect(lambda v: self._undo.push(SetEnabledCmd(self._graph, node_id, v)))
        self._body_lay.addWidget(en)

        groups: dict[str, list] = {}
        for name, param in node.params.items():
            groups.setdefault(param.group, []).append((name, param))

        for gname, items in groups.items():
            box = QGroupBox(gname)
            form = QFormLayout(box)
            form.setContentsMargins(2, 4, 2, 4)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for name, param in items:
                w = self._widget_for(node_id, name, param)
                if w is not None:
                    self._widgets[name] = w
                    form.addRow(_label(name), w)
            self._body_lay.addWidget(box)

    def refresh(self) -> None:
        """Rebuild only on a structural change; otherwise sync values in place so
        a slider being dragged doesn't get torn down mid-drag."""
        nid = self._node_id
        if nid is None or nid not in self._graph.nodes:
            self.show_node(nid)
            return
        node = self._graph.nodes[nid]
        key = (nid, tuple(node.params), node.type_name)
        if key != self._built_key:
            self.show_node(nid)
        else:
            self.sync_values()

    def sync_values(self) -> None:
        nid = self._node_id
        if nid is None or nid not in self._graph.nodes:
            return
        node = self._graph.nodes[nid]
        for name, w in self._widgets.items():
            if name not in node.params:
                continue
            v = node.params[name].value
            blk = w.blockSignals(True)
            try:
                if isinstance(w, ScrubSlider):
                    w.set_value(float(v))
                elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                    w.setValue(float(v))
                elif isinstance(w, QComboBox):
                    w.setCurrentText(str(v))
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(v))
                elif isinstance(w, QLineEdit):
                    if not w.hasFocus():
                        w.setText(str(v))
            finally:
                w.blockSignals(blk)

    # ------------------------------------------------------------ stack panel
    def _build_stack_panel(self, node_id: str) -> None:
        from vcomp.render.blend import BlendMode

        node = self._graph.nodes[node_id]
        conns = self._graph.incoming_ordered(node_id, "layers")
        ops = [x for x in str(node.params["opacities"].value).split(",") if x != ""]
        bls = [x for x in str(node.params["blends"].value).split(",") if x != ""]

        info = QLabel("Layers (bottom → top)")
        info.setStyleSheet(f"color:{theme.TEXT_DIM};")
        self._body_lay.addWidget(info)

        n = len(conns)
        op_spins, bl_combos = [], []
        for i, c in enumerate(conns):
            up = self._graph.nodes.get(c.from_node)
            box = QGroupBox(up.title if up else c.from_node)
            row = QFormLayout(box)

            eye = QCheckBox("visible")
            eye.setChecked(up.enabled if up else True)
            eye.toggled.connect(lambda v, nid=c.from_node: self._undo.push(
                SetEnabledCmd(self._graph, nid, v)))
            row.addRow(eye)

            osp = QDoubleSpinBox()
            osp.setRange(0.0, 1.0)
            osp.setSingleStep(0.05)
            osp.setValue(float(ops[i]) if i < len(ops) else 1.0)
            op_spins.append(osp)
            row.addRow("opacity", osp)

            bc = QComboBox()
            bc.addItems([b.name.lower() for b in BlendMode])
            bc.setCurrentText(bls[i] if i < len(bls) else "normal")
            bl_combos.append(bc)
            row.addRow("blend", bc)

            up_btn = QPushButton("move up")
            up_btn.setEnabled(i < n - 1)
            up_btn.clicked.connect(lambda _=False, idx=i: self._reorder_stack(node_id, idx, idx + 1))
            dn_btn = QPushButton("move down")
            dn_btn.setEnabled(i > 0)
            dn_btn.clicked.connect(lambda _=False, idx=i: self._reorder_stack(node_id, idx, idx - 1))
            hb = QHBoxLayout()
            hb.addWidget(dn_btn)
            hb.addWidget(up_btn)
            row.addRow(hb)
            self._body_lay.addWidget(box)

        def commit_rows():
            self._undo.push(SetParamCmd(self._graph, node_id, "opacities",
                                        ",".join(f"{s.value():.3f}" for s in op_spins)))
            self._undo.push(SetParamCmd(self._graph, node_id, "blends",
                                        ",".join(c.currentText() for c in bl_combos)))

        for s in op_spins:
            s.valueChanged.connect(lambda *_: commit_rows())
        for c in bl_combos:
            c.currentTextChanged.connect(lambda *_: commit_rows())

    def _reorder_stack(self, node_id: str, i: int, j: int) -> None:
        conns = self._graph.incoming_ordered(node_id, "layers")
        order = [c.from_node for c in conns]
        if 0 <= i < len(order) and 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self._graph.reorder_multi_input(node_id, "layers", order)
            self.refresh()

    # ------------------------------------------------------------- widgets
    def _push(self, name: str, value: Any) -> None:
        self._undo.push(SetParamCmd(self._graph, self._node_id, name, value))

    def _widget_for(self, node_id: str, name: str, param):
        t = param.type
        v = param.value

        if t is ParamType.BOOL:
            w = QCheckBox()
            w.setChecked(bool(v))
            w.toggled.connect(lambda val: self._push(name, val))
            return w

        if t is ParamType.INT:
            if param.min is not None and param.max is not None:
                w = ScrubSlider(param.min, param.max, int(v), param.step or 1,
                                integer=True)
                w.valueChanged.connect(lambda val: self._push(name, int(val)))
                return w
            w = QSpinBox()
            w.setRange(int(param.min if param.min is not None else -1_000_000),
                       int(param.max if param.max is not None else 1_000_000))
            w.setValue(int(v))
            w.valueChanged.connect(lambda val: self._push(name, val))
            return w

        if t is ParamType.FLOAT:
            if param.min is not None and param.max is not None:
                w = ScrubSlider(param.min, param.max, float(v), param.step or 0.0)
                w.valueChanged.connect(lambda val: self._push(name, val))
                return w
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setSingleStep(param.step or 0.01)
            w.setRange(-1e6, 1e6)
            w.setValue(float(v))
            w.valueChanged.connect(lambda val: self._push(name, val))
            return w

        if t is ParamType.ENUM:
            w = QComboBox()
            w.addItems(list(param.choices))
            if str(v) in param.choices:
                w.setCurrentText(str(v))
            w.currentTextChanged.connect(lambda val: self._push(name, val))
            return w

        if t is ParamType.COLOR:
            return self._color_widget(name, v)

        if t in (ParamType.RECT, ParamType.VEC2):
            return self._tuple_widget(name, v)

        # STR / FILEPATH
        w = QLineEdit(str(v))
        w.editingFinished.connect(lambda: self._push(name, w.text()))
        return w

    def _color_widget(self, name: str, v):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        swatch = QPushButton()
        r, g, b, a = (list(v) + [1, 1, 1, 1])[:4]
        swatch.setStyleSheet(
            f"background: rgba({int(r*255)},{int(g*255)},{int(b*255)},{a}); min-width:60px;")

        def pick():
            c = QColorDialog.getColor(
                QColor.fromRgbF(r, g, b, a), self, "Colour",
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if c.isValid():
                self._push(name, (c.redF(), c.greenF(), c.blueF(), c.alphaF()))

        swatch.clicked.connect(pick)
        lay.addWidget(swatch)
        return row

    def _tuple_widget(self, name: str, v):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        spins = []
        for comp in v:
            s = QDoubleSpinBox()
            s.setDecimals(3)
            s.setRange(-1e6, 1e6)
            s.setSingleStep(0.01)
            s.setMaximumWidth(96)
            s.setValue(float(comp))
            spins.append(s)
            lay.addWidget(s)

        def emit():
            self._push(name, tuple(s.value() for s in spins))

        for s in spins:
            s.valueChanged.connect(lambda *_: emit())
        return row


def _label(name: str) -> QLabel:
    return QLabel(name.replace("_", " "))


def _dim(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{theme.TEXT_DIM};")
    return lbl
