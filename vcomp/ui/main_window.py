"""Main window: menus, docks, media playback, node graph, properties, undo."""
from __future__ import annotations

import base64
import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from vcomp.core.graph import Graph, build_default_graph
from vcomp.media.probe import MediaInfo
from vcomp.nodes.registry import by_category, load_builtin_nodes
from vcomp.ui import theme
from vcomp.ui.frame_fetcher import FrameFetcher
from vcomp.ui.node_canvas import NodeCanvas
from vcomp.ui.properties import PropertiesPanel
from vcomp.ui.render_worker import RenderWorker
from vcomp.ui.timeline import Timeline
from vcomp.ui.viewport_output import OutputViewport
from vcomp.ui.viewport_source import SourceViewport
from vcomp.util.settings import Settings

log = logging.getLogger("vcomp.ui")

_VIDEO_FILTER = "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*)"


def _placeholder(text: str) -> QWidget:
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:13px;")
    return w


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("VCOMP")
        self.resize(1600, 950)

        load_builtin_nodes()
        self.graph = Graph()
        build_default_graph(self.graph)
        self.undo_stack = QUndoStack(self)

        self._info: MediaInfo | None = None
        self._last_frame: np.ndarray | None = None

        self._rerender = QTimer(self)
        self._rerender.setSingleShot(True)
        self._rerender.setInterval(30)
        self._rerender.timeout.connect(self._render_current)
        self.graph.on_changed.append(self._on_graph_changed)

        self.fetcher = FrameFetcher()
        self.fetcher.opened.connect(self._on_opened)
        self.fetcher.frameReady.connect(self._on_frame)
        self.fetcher.failed.connect(self._on_fail)

        self.renderer = RenderWorker()
        self.renderer.set_graph(self.graph)
        self.renderer.ready.connect(self._on_gl_ready)
        self.renderer.frameComposited.connect(self._on_composited)
        self.renderer.failed.connect(self._on_fail)

        self._build_menus()
        self._build_docks()
        self._build_statusbar()
        self._install_shortcuts()
        self._restore_layout()

        self.canvas.sync_from_core()
        self.fetcher.start()
        self.renderer.start()

    # ------------------------------------------------------------------ menus
    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._add(f, "New", "Ctrl+N", self._todo)
        self._add(f, "Open Clip...", "Ctrl+O", self._open_clip)
        f.addSeparator()
        self._add(f, "Save", "Ctrl+S", self._todo)
        self._add(f, "Export...", "Ctrl+E", self._todo)
        f.addSeparator()
        self._add(f, "Quit", "Ctrl+Q", self.close)

        e = mb.addMenu("&Edit")
        undo = self.undo_stack.createUndoAction(self, "Undo")
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        redo = self.undo_stack.createRedoAction(self, "Redo")
        redo.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        e.addAction(undo)
        e.addAction(redo)

        node_menu = mb.addMenu("&Node")
        for cat, types in by_category().items():
            sub = node_menu.addMenu(cat)
            for vt in types:
                act = QAction(vt.title_default, self)
                act.triggered.connect(lambda _=False, tn=vt.type_name: self._add_node(tn))
                sub.addAction(act)

        tpl = mb.addMenu("&Template")
        self._add(tpl, "Save as Template", "Ctrl+T", self._todo)
        self._add(tpl, "Template Browser", "Ctrl+Shift+T", self._todo)
        mb.addMenu("&Render")
        self._view_menu = mb.addMenu("&View")
        h = mb.addMenu("&Help")
        self._add(h, "About VCOMP", None, self._about)

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
        self.output_view = OutputViewport()
        self.timeline = Timeline()
        self.timeline.frameChanged.connect(self._request_frame)

        self.canvas = NodeCanvas(self.graph, self.undo_stack)
        self.canvas.nodeSelected.connect(self._on_node_selected)
        self.canvas.status.connect(self.set_status)

        self.props = PropertiesPanel(self.graph, self.undo_stack)

        self.dock_source = self._dock("Source Viewport (16:9)", "source",
                                      Qt.DockWidgetArea.LeftDockWidgetArea, self.source_view)
        self.dock_output = self._dock("Output Viewport (9:16)", "output",
                                      Qt.DockWidgetArea.RightDockWidgetArea, self.output_view)
        self.dock_timeline = self._dock("Timeline", "timeline",
                                        Qt.DockWidgetArea.BottomDockWidgetArea, self.timeline)
        self.dock_nodes = self._dock("Node Canvas", "nodes",
                                     Qt.DockWidgetArea.BottomDockWidgetArea, self.canvas.widget)
        self.dock_props = self._dock("Properties", "props",
                                     Qt.DockWidgetArea.RightDockWidgetArea, self.props)
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
        self.lbl_gpu = QLabel("GPU: -")
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

    # ----------------------------------------------------------------- nodes
    def _add_node(self, type_name: str) -> None:
        try:
            self.canvas.add_node_by_type(type_name)
            self.set_status(f"added {type_name}")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"cannot add {type_name}: {exc}")

    def _on_node_selected(self, cid) -> None:
        self.props.show_node(cid)

    def _on_graph_changed(self) -> None:
        self.props.refresh()
        self._rerender.start()

    # ----------------------------------------------------------------- media
    def _open_clip(self) -> None:
        recent = self.settings.get("recent_files", [])
        start = recent[0] if recent else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open Clip", start, _VIDEO_FILTER)
        if path:
            self.set_status(f"opening {path} ...")
            self.fetcher.open(path)

    def _on_opened(self, info: MediaInfo) -> None:
        self._info = info
        self.settings.add_recent_file(info.path)
        self.settings.save()
        self.timeline.set_media(info.frame_count, info.fps)
        for node in self.graph.clip_source_nodes():
            node.params["file_path"].set(info.path)
            node.params["out_point"].set(info.duration)
            node.set_media_info(info.width, info.height, info.fps, info.duration)
        vfr = " VFR" if info.is_vfr else ""
        self.lbl_source.setText(f"{info.width}x{info.height}  {info.fps:.3f}fps{vfr}  {info.duration:.1f}s")
        self.set_status(f"loaded {info.path}")
        self._request_frame(0)

    def _request_frame(self, index: int) -> None:
        self.lbl_playhead.setText(f"f{index}")
        self.fetcher.request(index)

    def _on_frame(self, index: int, arr: np.ndarray) -> None:
        if index != self.timeline.frame:
            self.timeline.set_cache_state(self.fetcher.cached_indices())
            return
        self._last_frame = arr
        self.source_view.set_frame(arr)
        self._render_current()
        self.timeline.set_cache_state(self.fetcher.cached_indices())

    def _render_current(self) -> None:
        if self._last_frame is None:
            return
        idx = self.timeline.frame
        fps = self._info.fps if self._info else 30.0
        frames = {n.id: self._last_frame for n in self.graph.clip_source_nodes()}
        self.renderer.submit(idx, frames, idx / fps if fps else 0.0)

    def _on_composited(self, index: int, arr: np.ndarray) -> None:
        if index == self.timeline.frame:
            self.output_view.set_frame(arr)

    def _on_gl_ready(self, renderer: str) -> None:
        self.lbl_gpu.setText(f"GPU: {renderer[:40]}")
        self.set_status("GL renderer ready")

    def _on_fail(self, msg: str) -> None:
        self.set_status(f"error: {msg}")
        QMessageBox.critical(self, "VCOMP", f"Error:\n{msg}")

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
        self.renderer.stop()
        self.settings.set("window_geometry",
                          base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        self.settings.set("window_layout",
                          base64.b64encode(bytes(self.saveState())).decode("ascii"))
        self.settings.save()
        super().closeEvent(event)

    def _todo(self) -> None:
        self.set_status("not implemented yet")

    def _about(self) -> None:
        QMessageBox.about(self, "About VCOMP",
                          "VCOMP - node-based vertical gameplay compositor.\nMilestone M3.")
