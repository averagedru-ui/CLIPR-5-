"""Main window: menus, docks, media playback, node graph, properties, undo."""
from __future__ import annotations

import base64
import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
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
_VIDEO_FILTER_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def _placeholder(text: str) -> QWidget:
    w = QLabel(text)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    w.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:13px;")
    return w


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("CLIPR")
        self.resize(1600, 950)
        self.setAcceptDrops(True)

        load_builtin_nodes()
        self.graph = Graph()
        build_default_graph(self.graph)
        self.undo_stack = QUndoStack(self)

        self._info: MediaInfo | None = None
        self._last_frame: np.ndarray | None = None
        self._last_output: np.ndarray | None = None
        self._selected_id: str | None = None
        self._project_path = None

        self._rerender = QTimer(self)
        self._rerender.setSingleShot(True)
        self._rerender.setInterval(16)
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
        self.renderer.thumbsReady.connect(self._on_thumbs)
        self.renderer.failed.connect(self._on_fail)

        self._build_menus()
        self._build_docks()
        self._build_view_menu_extras()
        self._build_statusbar()
        self._install_shortcuts()
        self._restore_layout()

        self.canvas.sync_from_core()
        self.fetcher.start()
        self.renderer.start()

        self._autosave = QTimer(self)
        self._autosave.setInterval(60_000)
        self._autosave.timeout.connect(self._do_autosave)
        self._autosave.start()
        QTimer.singleShot(400, self._offer_recovery)

    # ------------------------------------------------------------------ menus
    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._add(f, "New Project", "Ctrl+N", self._new_project)
        self._add(f, "Open Project...", "Ctrl+Shift+O", self._open_project)
        self._add(f, "Open Clip...", "Ctrl+O", self._open_clip)
        f.addSeparator()
        self._add(f, "Save Project", "Ctrl+S", self._save_project)
        self._add(f, "Save Project As...", "Ctrl+Shift+S", self._save_project_as)
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
        self._add(tpl, "Save as Template", "Ctrl+T", self._save_template)
        self._add(tpl, "Template Browser", "Ctrl+Shift+T", self._template_browser)
        tpl.addSeparator()
        wc = tpl.addMenu("Webcam Overlay")
        self.act_webcam = QAction("Enabled", self, checkable=True)
        self.act_webcam.toggled.connect(self._toggle_webcam)
        wc.addAction(self.act_webcam)
        place = wc.addMenu("Placement")
        for name in ("top-left", "top-right", "bottom-left", "bottom-right",
                     "top-center", "bottom-center"):
            act = QAction(name, self)
            act.triggered.connect(lambda _=False, p=name: self._set_webcam_placement(p))
            place.addAction(act)
        render_menu = mb.addMenu("&Render")
        self._add(render_menu, "Export...", "Ctrl+E", self._export)
        self._add(render_menu, "Batch Export...", None, self._batch_export)
        self._view_menu = mb.addMenu("&View")
        h = mb.addMenu("&Help")
        self._add(h, "About CLIPR", None, self._about)

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
        self.source_view.openClip.connect(self._open_clip)
        self.source_view.fileDropped.connect(self._load_clip)
        self.output_view.moveDest.connect(self._on_move_dest)
        self.output_view.scaleDest.connect(self._on_scale_dest)
        self.output_view.rotateDest.connect(self._on_rotate_dest)

        # LEFT: one viewport at a time (16:9 / 9:16 toggle) above the timeline
        self._vp_stack = QStackedWidget()
        self._vp_stack.addWidget(self.source_view)   # 0
        self._vp_stack.addWidget(self.output_view)   # 1

        self.btn_src = QPushButton("Source 16:9")
        self.btn_out = QPushButton("Output 9:16")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for i, b in enumerate((self.btn_src, self.btn_out)):
            b.setCheckable(True)
            grp.addButton(b, i)
            b.clicked.connect(lambda _=False, idx=i: self._show_viewport(idx))
        self.btn_out.setChecked(True)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(6, 4, 6, 0)
        toggle_row.addWidget(self.btn_src)
        toggle_row.addWidget(self.btn_out)
        toggle_row.addStretch(1)

        vp_panel = QWidget()
        vlay = QVBoxLayout(vp_panel)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(2)
        vlay.addLayout(toggle_row)
        vlay.addWidget(self._vp_stack, 1)
        vlay.addWidget(self.timeline, 0)

        self.dock_view = self._dock("Output 9:16", "view",
                                    Qt.DockWidgetArea.LeftDockWidgetArea, vp_panel)
        self.dock_nodes = self._dock("Node Canvas", "nodes",
                                     Qt.DockWidgetArea.RightDockWidgetArea, self.canvas.widget)
        self.dock_props = self._dock("Properties", "props",
                                     Qt.DockWidgetArea.RightDockWidgetArea, self.props)
        self.splitDockWidget(self.dock_view, self.dock_nodes, Qt.Orientation.Horizontal)
        self.splitDockWidget(self.dock_nodes, self.dock_props, Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_view, self.dock_nodes, self.dock_props],
                         [560, 760, 300], Qt.Orientation.Horizontal)
        self._show_viewport(1)

    def _show_viewport(self, idx: int) -> None:
        self._vp_stack.setCurrentIndex(idx)
        (self.btn_src if idx == 0 else self.btn_out).setChecked(True)
        if hasattr(self, "dock_view"):
            self.dock_view.setWindowTitle("Source 16:9" if idx == 0 else "Output 9:16")

    def _toggle_viewport(self) -> None:
        self._show_viewport(1 - self._vp_stack.currentIndex())

    def _build_view_menu_extras(self) -> None:
        self._view_menu.addSeparator()
        self.act_thumbs = QAction("Node Preview Thumbnails", self, checkable=True)
        self.act_thumbs.toggled.connect(self._toggle_thumbs)
        self._view_menu.addAction(self.act_thumbs)
        self.act_fullq = QAction("Full-Quality Preview", self, checkable=True)
        self.act_fullq.setToolTip("Always render the preview at 1x (no auto-downscale).")
        self.act_fullq.toggled.connect(self._toggle_full_quality)
        self._view_menu.addAction(self.act_fullq)

    def _toggle_full_quality(self, on: bool) -> None:
        self.renderer.lock_full_quality = bool(on)
        if on:
            self.renderer.preview_scale = 1.0
        self.lbl_preview.setText("Preview 1x" if on else "Preview auto")
        self._render_current()

    def _toggle_thumbs(self, on: bool) -> None:
        self.renderer.want_thumbs = bool(on)
        self.canvas.set_thumbs_visible(bool(on))
        if on:
            self._render_current()

    def _on_thumbs(self, thumbs: dict) -> None:
        self.canvas.set_thumbs(thumbs)

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
        sc("G", lambda: (self.output_view.toggle_guides(), self._render_current()))
        sc("F", self._frame_selection)
        sc("\\", self._toggle_viewport)
        sc("1", lambda: self._set_preview_scale(0.25))
        sc("2", lambda: self._set_preview_scale(0.5))
        sc("3", lambda: self._set_preview_scale(1.0))
        sc("Ctrl+D", self._duplicate_selected)
        sc("L", lambda: self.canvas.ng.auto_layout_nodes()
           if hasattr(self.canvas.ng, "auto_layout_nodes") else None)

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
        fc = self._facecam_node()
        self.act_webcam.blockSignals(True)
        self.act_webcam.setChecked(fc is not None and fc.enabled)
        self.act_webcam.blockSignals(False)
        self._rerender.start()

    # -------------------------------------------------------------- overlays
    def _src_dims(self) -> tuple[int, int]:
        if self._info:
            return self._info.display_width, self._info.display_height
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
            self._load_clip(path)

    def _load_clip(self, path: str) -> None:
        self.set_status(f"opening {path} ...")
        self.fetcher.open(path, self._orientation_override())

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls() and any(
                u.toLocalFile().lower().endswith(_VIDEO_FILTER_EXT)
                for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(_VIDEO_FILTER_EXT):
                self._load_clip(p)
                return

    def _orientation_override(self) -> int | None:
        clip = next(iter(self.graph.clip_source_nodes()), None)
        val = clip.params["orientation"].value if clip and "orientation" in clip.params else "auto"
        if val == "auto":
            return None
        if val == "none":
            return 0
        try:
            return int(val)
        except ValueError:
            return None

    def _on_opened(self, info: MediaInfo) -> None:
        self._info = info
        self.settings.add_recent_file(info.path)
        self.settings.save()
        self.timeline.set_media(info.frame_count, info.fps)
        dw, dh = info.display_width, info.display_height
        for node in self.graph.clip_source_nodes():
            node.params["file_path"].set(info.path)
            node.params["out_point"].set(info.duration)
            node.set_media_info(dw, dh, info.fps, info.duration)
        vfr = " VFR" if info.is_vfr else ""
        rot = f"  rot{info.rotation}" if info.rotation else ""
        self.lbl_source.setText(f"{dw}x{dh}{rot}  {info.fps:.3f}fps{vfr}  {info.duration:.1f}s")
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
        idx = self.timeline.frame
        fps = self._info.fps if self._info else 30.0
        frames = ({n.id: self._last_frame for n in self.graph.clip_source_nodes()}
                  if self._last_frame is not None else {})
        self.renderer.submit(idx, frames, idx / fps if fps else 0.0)

    def _on_composited(self, index: int, arr: np.ndarray) -> None:
        self._last_output = arr
        if index == self.timeline.frame:
            self.output_view.set_frame(arr)
        if self.renderer.lock_full_quality:
            return
        if self.renderer.last_render_ms > 130 and self.renderer.preview_scale > 0.25:
            self.renderer.preview_scale = max(0.25, self.renderer.preview_scale / 2)
        lbl = {1.0: "1x", 0.5: "½", 0.25: "¼"}.get(round(self.renderer.preview_scale, 2), "?")
        self.lbl_preview.setText(f"Preview {lbl}")

    def _on_gl_ready(self, renderer: str) -> None:
        self.lbl_gpu.setText(f"GPU: {renderer[:40]}")
        self.set_status("GL renderer ready")

    def _on_fail(self, msg: str) -> None:
        self.set_status(f"error: {msg}")
        QMessageBox.critical(self, "CLIPR", f"Error:\n{msg}")

    # ---------------------------------------------------------------- layout
    _LAYOUT_VERSION = 2

    def _restore_layout(self) -> None:
        if self.settings.get("layout_version") != self._LAYOUT_VERSION:
            return                       # dock set changed - start from defaults
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
        self.settings.set("layout_version", self._LAYOUT_VERSION)
        self.settings.set("window_geometry",
                          base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        self.settings.set("window_layout",
                          base64.b64encode(bytes(self.saveState())).decode("ascii"))
        self.settings.save()
        super().closeEvent(event)

    # ------------------------------------------------------------- templates
    def _save_template(self) -> None:
        from vcomp.ui.template_browser import SaveTemplateDialog

        dlg = SaveTemplateDialog(self, self.graph, self._src_dims(), self._last_output)
        if dlg.exec() and dlg.saved_path:
            self.set_status(f"saved template {dlg.saved_path.name}")

    def _template_browser(self) -> None:
        from vcomp.ui.template_browser import TemplateBrowser

        TemplateBrowser(self, self._apply_template).exec()

    def _apply_template(self, tpl) -> None:
        from vcomp.templates.io import apply_template
        from vcomp.ui.commands import ReplaceGraphCmd

        tmp = Graph()
        tmp.load_dict(self.graph.to_dict())
        warns = apply_template(tmp, tpl, self._src_dims())
        self.undo_stack.push(ReplaceGraphCmd(self.graph, tmp.to_dict(),
                                             text=f"Apply {tpl.meta.name}"))
        if self._info:
            for n in self.graph.clip_source_nodes():
                n.params["file_path"].set(self._info.path)
                if "orientation" in n.params:
                    n.params["orientation"].set("none")
                n.set_media_info(self._info.display_width, self._info.display_height,
                                 self._info.fps, self._info.duration)
        self.canvas.sync_from_core()
        self._refresh_overlays()
        # re-decode so the clip's orientation matches the (reset) Clip Source param
        if self._info:
            self.fetcher.open(self._info.path, self._orientation_override())
        else:
            self._render_current()
        if warns:
            self.set_status("  ".join(warns))
        else:
            self.set_status(f"applied template {tpl.meta.name}")

    # -------------------------------------------------------------- project
    def _new_project(self) -> None:
        self.graph.load_dict(build_default_graph(Graph()).to_dict())
        self.undo_stack.clear()
        self._project_path = None
        self.canvas.sync_from_core()
        self._render_current()
        self.set_status("new project")

    def _open_project(self) -> None:
        from vcomp.core.project import Project

        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "CLIPR project (*.vcproj)")
        if not path:
            return
        try:
            proj = Project.load(path)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Open", str(exc))
            return
        self.graph.load_dict(proj.graph.to_dict())
        self.undo_stack.clear()
        self._project_path = path
        self.canvas.sync_from_core()
        clip = next(iter(self.graph.clip_source_nodes()), None)
        if clip and clip.params["file_path"].value:
            self.fetcher.open(clip.params["file_path"].value, self._orientation_override())
        self.set_status(f"opened {path}")

    def _save_project(self) -> None:
        if self._project_path:
            self._write_project(self._project_path)
        else:
            self._save_project_as()

    def _save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "CLIPR project (*.vcproj)")
        if path:
            self._write_project(path)

    def _write_project(self, path) -> None:
        from vcomp.core.project import Project

        proj = Project(graph=self.graph, in_point=self.timeline.in_point,
                       out_point=self.timeline.out_point)
        proj.save(path)
        self._project_path = path
        self.set_status(f"saved {path}")

    # ---------------------------------------------------------------- polish
    def _do_autosave(self) -> None:
        if len(self.graph.nodes) <= 1:
            return
        from vcomp.core.autosave import write_autosave
        from vcomp.core.project import Project

        p = Project(graph=self.graph, in_point=self.timeline.in_point,
                    out_point=self.timeline.out_point)
        if write_autosave(p):
            self.lbl_action.setText("autosaved")

    def _offer_recovery(self) -> None:
        from vcomp.core.autosave import clear_recovery, pending_recovery
        from vcomp.core.project import Project

        rec = pending_recovery()
        if not rec:
            return
        if QMessageBox.question(
                self, "Recover", f"An autosave from {rec.stem} was found. Restore it?"
        ) == QMessageBox.StandardButton.Yes:
            try:
                proj = Project.load(rec)
                self.graph.load_dict(proj.graph.to_dict())
                self.undo_stack.clear()
                self.canvas.sync_from_core()
                clip = next(iter(self.graph.clip_source_nodes()), None)
                if clip and clip.params["file_path"].value:
                    self.fetcher.open(clip.params["file_path"].value, self._orientation_override())
                self.set_status("recovered autosave")
            except (ValueError, OSError) as exc:
                self.set_status(f"recovery failed: {exc}")
        clear_recovery()

    def _set_preview_scale(self, s: float) -> None:
        self.renderer.preview_scale = s
        label = {0.25: "¼", 0.5: "½", 1.0: "1x"}[s]
        self.lbl_preview.setText(f"Preview {label}")
        self._render_current()

    def _frame_selection(self) -> None:
        for v in (self.source_view, self.output_view):
            v._zoom = 1.0
            v._pan = v._pan.__class__(0, 0)
            v.update()

    def _duplicate_selected(self) -> None:
        if not self._selected_id or self._selected_id not in self.graph.nodes:
            return
        src = self.graph.nodes[self._selected_id]
        if not src.deletable:
            return
        from vcomp.ui.commands import AddNodeCmd

        nid = self.graph.new_id(src.type_name)
        self.undo_stack.beginMacro("Duplicate node")
        self.undo_stack.push(AddNodeCmd(self.graph, src.type_name, nid))
        for k, snap in src.to_dict()["params"].items():
            self.graph.nodes[nid].params[k].restore(snap)
        self.undo_stack.endMacro()
        self.canvas.sync_from_core()
        self.set_status(f"duplicated {src.type_name}")

    # ---------------------------------------------------------------- webcam
    def _facecam_node(self):
        return next((n for n in self.graph.nodes.values()
                     if n.type_name == "Facecam"), None)

    def _toggle_webcam(self, on: bool) -> None:
        from vcomp.ui.commands import AddNodeCmd, ConnectCmd, SetEnabledCmd
        from vcomp.core.graph import Connection

        fc = self._facecam_node()
        if fc is None:
            if not on:
                return
            clip = next(iter(self.graph.clip_source_nodes()), None)
            stack = next((n for n in self.graph.nodes.values()
                          if n.type_name == "Stack"), None)
            nid = self.graph.new_id("Facecam")
            self.undo_stack.beginMacro("Add Webcam Overlay")
            self.undo_stack.push(AddNodeCmd(self.graph, "Facecam", nid))
            for a, ap, b, bp in filter(None, [
                (clip.id, "image", nid, "image") if clip else None,
                (nid, "image", stack.id, "layers") if stack else None,
            ]):
                try:
                    self.graph.connect(a, ap, b, bp)
                    self.graph.disconnect(Connection(a, ap, b, bp))
                    self.undo_stack.push(ConnectCmd(self.graph, Connection(a, ap, b, bp)))
                except Exception:  # noqa: BLE001
                    pass
            self.undo_stack.endMacro()
            self.canvas.sync_from_core()
            self._selected_id = nid
            self.props.show_node(nid)
            self.set_status("webcam overlay added — set its source_rect to the "
                            "webcam box in the source view")
        else:
            self.undo_stack.push(SetEnabledCmd(self.graph, fc.id, on))

    def _set_webcam_placement(self, placement: str) -> None:
        from vcomp.ui.commands import SetParamCmd

        fc = self._facecam_node()
        if fc is None:
            self._toggle_webcam(True)
            fc = self._facecam_node()
        if fc is not None:
            self.undo_stack.push(SetParamCmd(self.graph, fc.id, "placement", placement))
            if not self.act_webcam.isChecked():
                self.act_webcam.setChecked(True)
            self.set_status(f"webcam -> {placement}")

    def _batch_export(self) -> None:
        from vcomp.ui.batch_dialog import BatchDialog

        BatchDialog(self, self.graph).exec()

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
        QMessageBox.about(self, "About CLIPR",
                          "CLIPR - node-based vertical gameplay compositor.")
