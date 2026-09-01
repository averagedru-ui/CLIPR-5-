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
        self._selected_id: str | None = None

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
        self._add(f, "Export...", "Ctrl+E", self._export)
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

        self.source_view.createRegion.connect(self._on_create_region)
        self.source_view.editRect.connect(self._on_edit_rect)
        self.source_view.selectRegion.connect(self._on_region_selected)
        self.source_view.pickColor.connect(self._on_pick_color)
        self.output_view.moveDest.connect(self._on_move_dest)
        self.output_view.scaleDest.connect(self._on_scale_dest)
        self.output_view.rotateDest.connect(self._on_rotate_dest)

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
        sc("M", self.source_view.arm_create)
        sc("Alt+I", self.source_view.arm_eyedropper)
        sc("S", self._toggle_solo)
        sc("H", self._toggle_hide)

    # ----------------------------------------------------------------- nodes
    def _add_node(self, type_name: str) -> None:
        try:
            self.canvas.add_node_by_type(type_name)
            self.set_status(f"added {type_name}")
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"cannot add {type_name}: {exc}")

    def _on_node_selected(self, cid) -> None:
        self._selected_id = cid or None
        self.props.show_node(self._selected_id)
        self._refresh_overlays()

    def _on_region_selected(self, cid) -> None:
        self._selected_id = cid or None
        if cid:
            self.canvas.focus_core_node(cid)
        self.props.show_node(self._selected_id)
        self._refresh_overlays()

    def _on_graph_changed(self) -> None:
        self.props.refresh()
        self._refresh_overlays()
        self._rerender.start()

    # -------------------------------------------------------------- overlays
    def _src_dims(self) -> tuple[int, int]:
        if self._info:
            return self._info.width, self._info.height
        return 1920, 1080

    def _hud_nodes(self):
        return [n for n in self.graph.nodes.values() if n.type_name == "HUD Region"]

    def _refresh_overlays(self) -> None:
        regs = []
        for n in self._hud_nodes():
            regs.append({
                "id": n.id,
                "label": n.params["label"].value or n.title,
                "rect": tuple(n.params["source_rect"].value),
                "selected": n.id == self._selected_id,
            })
        self.source_view.set_regions(regs)

        sel = self.graph.nodes.get(self._selected_id) if self._selected_id else None
        sw, sh = self._src_dims()
        cw, ch, _ = self.graph.canvas_params()
        band = None
        fr = next((n for n in self.graph.nodes.values() if n.type_name == "Main Framing"), None)
        if fr is not None:
            band = fr.band_rect(cw, ch, sw, sh)
        if sel is not None and sel.type_name == "HUD Region":
            quad = sel.dest_rect_for(cw, ch, sw, sh)
            self.output_view.set_selection(
                sel.id, quad,
                (sel.params["dest_x"].value, sel.params["dest_y"].value),
                sel.params["dest_scale"].value, sel.params["rotation"].value, band)
        else:
            self.output_view.set_selection(None, None, None, None, None, band)

    # ---------------------------------------------------------- region edits
    def _on_create_region(self, x, y, w, h) -> None:
        from vcomp.core import coords

        clip = next(iter(self.graph.clip_source_nodes()), None)
        stack = next((n for n in self.graph.nodes.values() if n.type_name == "Stack"), None)
        from vcomp.ui.commands import AddNodeCmd

        rid = self.graph.new_id("HUD Region")
        self.undo_stack.beginMacro("Create HUD Region")
        self.undo_stack.push(AddNodeCmd(self.graph, "HUD Region", rid))
        self.graph.set_param(rid, "source_rect", coords.clamp_rect((x, y, w, h)))
        n_regions = len(self._hud_nodes())
        self.graph.set_param(rid, "dest_x", 0.5)
        self.graph.set_param(rid, "dest_y", 0.08 + 0.06 * (n_regions - 1))
        self.graph.set_param(rid, "label", f"Region {n_regions}")
        if clip:
            self._safe_connect(clip.id, "image", rid, "image")
        if stack:
            self._safe_connect(rid, "image", stack.id, "layers")
        self.undo_stack.endMacro()
        self._selected_id = rid
        self.canvas.sync_from_core()
        self.canvas.focus_core_node(rid)
        self.props.show_node(rid)
        self.set_status(f"created HUD Region '{rid}'")

    def _safe_connect(self, a, ap, b, bp) -> None:
        from vcomp.ui.commands import ConnectCmd
        from vcomp.core.graph import Connection

        try:
            self.graph.connect(a, ap, b, bp)
            self.graph.disconnect(Connection(a, ap, b, bp))
            self.undo_stack.push(ConnectCmd(self.graph, Connection(a, ap, b, bp)))
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"wire failed: {exc}")

    def _on_edit_rect(self, node_id, rect, final) -> None:
        from vcomp.ui.commands import SetParamCmd

        if node_id in self.graph.nodes:
            self.undo_stack.push(SetParamCmd(self.graph, node_id, "source_rect", tuple(rect)))

    def _on_pick_color(self, rgb) -> None:
        from vcomp.ui.commands import SetParamCmd

        if not self._selected_id:
            return
        node = self.graph.nodes[self._selected_id]
        target = "plate_color" if node.params.get("plate_enabled") and \
            node.params["plate_enabled"].value else "outline_color"
        if target not in node.params:
            target = next((k for k, p in node.params.items()
                           if p.type.name == "COLOR"), None)
        if target:
            r, g, b = rgb
            self.undo_stack.push(SetParamCmd(self.graph, self._selected_id, target,
                                             (r, g, b, 1.0)))
            self.set_status(f"picked colour -> {target}")

    def _on_move_dest(self, node_id, dx, dy, final) -> None:
        from vcomp.ui.commands import SetParamCmd

        self.undo_stack.push(SetParamCmd(self.graph, node_id, "dest_x", float(dx)))
        self.undo_stack.push(SetParamCmd(self.graph, node_id, "dest_y", float(dy)))

    def _on_scale_dest(self, node_id, scale, final) -> None:
        from vcomp.ui.commands import SetParamCmd

        self.undo_stack.push(SetParamCmd(self.graph, node_id, "dest_scale", float(scale)))

    def _on_rotate_dest(self, node_id, deg, final) -> None:
        from vcomp.ui.commands import SetParamCmd

        self.undo_stack.push(SetParamCmd(self.graph, node_id, "rotation", float(deg)))

    def _toggle_solo(self) -> None:
        from vcomp.ui.commands import SetParamCmd

        if self._selected_id and "solo" in self.graph.nodes[self._selected_id].params:
            cur = self.graph.nodes[self._selected_id].params["solo"].value
            self.undo_stack.push(SetParamCmd(self.graph, self._selected_id, "solo", not cur))

    def _toggle_hide(self) -> None:
        from vcomp.ui.commands import SetEnabledCmd

        if self._selected_id:
            cur = self.graph.nodes[self._selected_id].enabled
            self.undo_stack.push(SetEnabledCmd(self.graph, self._selected_id, not cur))

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
        self._refresh_overlays()
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

    def _export(self) -> None:
        if not self._info:
            self.set_status("open a clip first")
            return
        from vcomp.ui.export_dialog import ExportDialog

        clip = next(iter(self.graph.clip_source_nodes()), None)
        speed = float(clip.params["speed"].value) if clip else 1.0
        in_t = self.timeline.in_point / self._info.fps
        out_t = (self.timeline.out_point + 1) / self._info.fps
        dlg = ExportDialog(self, self.graph, self._info.path, in_t, out_t, speed)
        dlg.exec()

    def _todo(self) -> None:
        self.set_status("not implemented yet")

    def _about(self) -> None:
        QMessageBox.about(self, "About VCOMP",
                          "VCOMP - node-based vertical gameplay compositor.\nMilestone M3.")
