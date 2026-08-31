"""Main window: menus, dockable panels, status bar, and (M1) media playback.

Source viewport + transport are live. Output viewport, node canvas and
properties remain placeholders until M2/M3.
"""
from __future__ import annotations

import base64
import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from vcomp.media.probe import MediaInfo
from vcomp.ui import theme
from vcomp.ui.frame_fetcher import FrameFetcher
from vcomp.ui.timeline import Timeline
from vcomp.ui.viewport_source import SourceViewport
from vcomp.util.settings import Settings

log = logging.getLogger("vcomp.ui")

_VIDEO_FILTER = "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*)"


def _placeholder(text: str) -> QWidget:
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:13px;")
    w.setMinimumSize(200, 120)
    return w


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("VCOMP")
        self.resize(1600, 950)

        self._info: MediaInfo | None = None
        self._pending_seek: int | None = None
        self._awaiting = False

        self.fetcher = FrameFetcher()
        self.fetcher.opened.connect(self._on_opened)
        self.fetcher.frameReady.connect(self._on_frame)
        self.fetcher.failed.connect(self._on_fail)
        self.fetcher.start()

        self._build_menus()
        self._build_docks()
        self._build_statusbar()
        self._install_shortcuts()
        self._restore_layout()

    # ------------------------------------------------------------------ menus
    def _build_menus(self) -> None:
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        self._add(file_menu, "New", "Ctrl+N", self._todo)
        self._add(file_menu, "Open Clip...", "Ctrl+O", self._open_clip)
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
        self._view_menu = mb.addMenu("&View")
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

        self.source_view = SourceViewport()
        self.timeline = Timeline()
        self.timeline.frameChanged.connect(self._request_frame)

        self.dock_source = self._dock("Source Viewport (16:9)", "source",
                                      Qt.DockWidgetArea.LeftDockWidgetArea, self.source_view)
        self.dock_output = self._dock("Output Viewport (9:16)", "output",
                                      Qt.DockWidgetArea.RightDockWidgetArea,
                                      _placeholder("Output Viewport\n(M2)"))
        self.dock_timeline = self._dock("Timeline", "timeline",
                                        Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline)
        self.dock_nodes = self._dock("Node Canvas", "nodes",
                                     Qt.DockWidgetArea.BottomDockWidgetArea,
                                     _placeholder("Node Canvas\n(M3)"))
        self.dock_props = self._dock("Properties", "props",
                                     Qt.DockWidgetArea.RightDockWidgetArea,
                                     _placeholder("Properties\n(M3)"))
        self.splitDockWidget(self.dock_nodes, self.dock_props, Qt.Orientation.Horizontal)

    def _dock(self, title, obj, area, widget) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(f"dock_{obj}")
        d.setWidget(widget)
        self.addDockWidget(area, d)
        self._view_menu.addAction(d.toggleViewAction())
        return d

    # -------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_source = QLabel("no clip")
        self.lbl_playhead = QLabel("f0")
        self.lbl_preview = QLabel("Preview 1x")
        self.lbl_gpu = QLabel("GPU: - (M2)")
        self.lbl_action = QLabel("ready")
        for w in (self.lbl_source, self.lbl_playhead, self.lbl_preview, self.lbl_gpu):
            sb.addPermanentWidget(w)
        sb.addWidget(self.lbl_action)

    def set_status(self, text: str) -> None:
        self.lbl_action.setText(text)
        log.info("status: %s", text)

    # ------------------------------------------------------------- shortcuts
    def _install_shortcuts(self) -> None:
        def sc(seq, fn):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(fn)
            self.addAction(a)

        sc("Space", self.timeline.toggle_play)
        sc(",", lambda: self.timeline.seek(self.timeline.frame - 1))
        sc(".", lambda: self.timeline.seek(self.timeline.frame + 1))
        sc("Home", lambda: self.timeline.seek(self.timeline.in_point))
        sc("End", lambda: self.timeline.seek(self.timeline.out_point))
        sc("I", lambda: self.timeline.btn_in.click())
        sc("O", lambda: self.timeline.btn_out.click())

    # ----------------------------------------------------------------- media
    def _open_clip(self) -> None:
        start = ""
        recent = self.settings.get("recent_files", [])
        if recent:
            start = recent[0]
        path, _ = QFileDialog.getOpenFileName(self, "Open Clip", start, _VIDEO_FILTER)
        if not path:
            return
        self.set_status(f"opening {path} ...")
        self.fetcher.open(path)

    def _on_opened(self, info: MediaInfo) -> None:
        self._info = info
        self.settings.add_recent_file(info.path)
        self.settings.save()
        self.timeline.set_media(info.frame_count, info.fps)
        vfr = " VFR" if info.is_vfr else ""
        self.lbl_source.setText(
            f"{info.width}x{info.height}  {info.fps:.3f}fps{vfr}  {info.duration:.1f}s"
        )
        self.set_status(f"loaded {info.path}")
        self._request_frame(0)

    def _request_frame(self, index: int) -> None:
        self.lbl_playhead.setText(f"f{index}")
        self.fetcher.request(index)

    def _on_frame(self, index: int, arr: np.ndarray) -> None:
        if index == self.timeline.frame:
            self.source_view.set_frame(arr)
        self.timeline.set_cache_state(self.fetcher.cached_indices())

    def _on_fail(self, msg: str) -> None:
        self.set_status(f"error: {msg}")
        QMessageBox.critical(self, "VCOMP", f"Media error:\n{msg}")

    # ---------------------------------------------------------------- layout
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

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timeline.set_playing(False)
        self.fetcher.stop()
        self.settings.set("window_geometry",
                          base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        self.settings.set("window_layout",
                          base64.b64encode(bytes(self.saveState())).decode("ascii"))
        self.settings.save()
        super().closeEvent(event)

    # ------------------------------------------------------------------ slots
    def _todo(self) -> None:
        self.set_status("not implemented yet")

    def _about(self) -> None:
        QMessageBox.about(self, "About VCOMP",
                          "VCOMP - node-based vertical gameplay compositor.\nMilestone M1.")
