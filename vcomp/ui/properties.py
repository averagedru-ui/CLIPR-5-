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


class PropertiesPanel(QWidget):
    def __init__(self, graph, undo_stack) -> None:
        super().__init__()
        self._graph = graph
        self._undo = undo_stack
        self._node_id: str | None = None

        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._body)

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
        header = QLabel(f"{node.title}  ·  {node.type_name}")
        header.setStyleSheet(f"font-weight:bold; color:{theme.TEXT};")
        self._body_lay.addWidget(header)

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
            for name, param in items:
                w = self._widget_for(node_id, name, param)
                if w is not None:
                    form.addRow(_label(name), w)
            self._body_lay.addWidget(box)

    def refresh(self) -> None:
        self.show_node(self._node_id)

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
            w = QSpinBox()
            w.setRange(int(param.min if param.min is not None else -1_000_000),
                       int(param.max if param.max is not None else 1_000_000))
            w.setValue(int(v))
            w.valueChanged.connect(lambda val: self._push(name, val))
            return w

        if t is ParamType.FLOAT:
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setSingleStep(param.step or 0.01)
            w.setRange(param.min if param.min is not None else -1e6,
                       param.max if param.max is not None else 1e6)
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
