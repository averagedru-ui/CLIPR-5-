"""Main window: menu bar, dockable panels, status bar.

M0 populates the docks with placeholder widgets only. Later milestones swap the
placeholders for the real viewports, node canvas, properties inspector, and
timeline without changing the dock layout wiring here.
"""
from __future__ import annotations

import base64
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QWidget,
)

from vcomp.util.settings import Settings

log = logging.getLogger("vcomp.ui")

_PANEL_STYLE = "color:#8a8a92; font-size:13px;"


def _placeholder(text: str) -> QWidget:
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(_PANEL_STYLE)
    w.setMinimumSize(200, 120)
    return w


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("VCOMP")
        self.resize(1600, 950)

        self._build_menus()
        self._build_docks()
        self._build_statusbar()
        self._restore_layout()

    # ------------------------------------------------------------------ menus
    def _build_menus(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self._add(file_menu, "New", "Ctrl+N", self._todo)
        self._add(file_menu, "Open...", "Ctrl+O", self._todo)
        file_menu.addSeparator()
        self._add(file_menu, "Save", "Ctrl+S", self._todo)
        self._add(file_menu, "Save As...", "Ctrl+Shift+S", self._todo)
        file_menu.addSeparator()
        self._add(file_menu, "Export...", "Ctrl+E", self._todo)
        file_menu.addSeparator()
        self._add(file_menu, "Quit", "Ctrl+Q", self.close)

        edit_menu = mb.addMenu("&Edit")
        self._add(edit_menu, "Undo", "Ctrl+Z", self._todo)
        self._add(edit_menu, "Redo", "Ctrl+Shift+Z", self._todo)

        mb.addMenu("&Node")
        tpl = mb.addMenu("&Template")
        self._add(tpl, "Save as Template", "Ctrl+T", self._todo)
        self._add(tpl, "Template Browser", "Ctrl+Shift+T", self._todo)
        mb.addMenu("&Render")

        view_menu = mb.addMenu("&View")
        self._view_menu = view_menu  # dock toggles appended in _build_docks

        help_menu = mb.addMenu("&Help")
        self._add(help_menu, "About VCOMP", None, self._about)

    def _add(self, menu, text, shortcut, slot) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    # ------------------------------------------------------------------ docks
    def _build_docks(self) -> None:
        self.setDockNestingEnabled(True)

        self.dock_source = self._dock("Source Viewport (16:9)", "source", Qt.DockWidgetArea.LeftDockWidgetArea)
        self.dock_output = self._dock("Output Viewport (9:16)", "output", Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock_timeline = self._dock("Timeline", "timeline", Qt.DockWidgetArea.BottomDockWidgetArea)
        self.dock_nodes = self._dock("Node Canvas", "nodes", Qt.DockWidgetArea.BottomDockWidgetArea)
        self.dock_props = self._dock("Properties", "props", Qt.DockWidgetArea.RightDockWidgetArea)

        self.splitDockWidget(self.dock_nodes, self.dock_props, Qt.Orientation.Horizontal)

    def _dock(self, title: str, obj: str, area: Qt.DockWidgetArea) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(f"dock_{obj}")
        d.setWidget(_placeholder(f"{title}\n(coming in a later milestone)"))
        self.addDockWidget(area, d)
        self._view_menu.addAction(d.toggleViewAction())
        return d

    # -------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_source = QLabel("no clip")
        self.lbl_playhead = QLabel("00:00:00 / f0")
        self.lbl_preview = QLabel("Preview 1x")
        self.lbl_gpu = QLabel("GPU: -")
        self.lbl_action = QLabel("ready")
        for w in (self.lbl_source, self.lbl_playhead, self.lbl_preview, self.lbl_gpu):
            sb.addPermanentWidget(w)
        sb.addWidget(self.lbl_action)

    def set_status(self, text: str) -> None:
        self.lbl_action.setText(text)
        log.info("status: %s", text)

    # ----------------------------------------------------------------- layout
    def _restore_layout(self) -> None:
        geo = self.settings.get("window_geometry")
        st = self.settings.get("window_layout")
        try:
            if geo:
                self.restoreGeometry(base64.b64decode(geo))
            if st:
                self.restoreState(base64.b64decode(st))
        except (ValueError, TypeError):
            log.warning("Could not restore window layout")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.settings.set("window_geometry", base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        self.settings.set("window_layout", base64.b64encode(bytes(self.saveState())).decode("ascii"))
        self.settings.save()
        super().closeEvent(event)

    # ------------------------------------------------------------------ slots
    def _todo(self) -> None:
        self.set_status("not implemented yet")

    def _about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.about(
            self,
            "About VCOMP",
            "VCOMP - node-based vertical gameplay compositor.\nMilestone M0 scaffold.",
        )
