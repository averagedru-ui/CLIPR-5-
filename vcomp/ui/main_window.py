"""Main window: menus, docks, media playback, node graph, properties, undo."""
from __future__ import annotations

import base64
import logging
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
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


def _panel(title: str, widget: QWidget, extra: QWidget | None = None) -> QWidget:
    """Wrap a widget in a titled panel (small uppercase header + content)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    head = QLabel(title)
    head.setObjectName("panelTitle")
    head.setContentsMargins(10, 6, 10, 4)
    lay.addWidget(head)
    lay.addWidget(widget, 1)
    if extra is not None:
        lay.addWidget(extra, 0)
    return box


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
        self._pending_inout: tuple[int, int] | None = None
        self._req_prev = 0        # last requested frame index (detects loop wrap)
        self._shown_src = -1      # freshest source frame index shown while playing
        self._shown_out = -1      # freshest composited frame index shown while playing
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
        self._build_central()
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
        self._add(node_menu, "Draw Rectangle Mask", "M",
                  lambda: self._arm_mask(self.source_view.arm_create))
        self._add(node_menu, "Draw Polygon Mask", "P",
                  lambda: self._arm_mask(self.source_view.arm_polygon))
        node_menu.addSeparator()
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

    # ---------------------------------------------------------------- central
    def _build_central(self) -> None:
        self.source_view = SourceViewport()
        self.output_view = OutputViewport()
        self.timeline = Timeline()
        self.timeline.frameChanged.connect(self._request_frame)
        self.timeline.playingChanged.connect(self._on_play_state)

        self.canvas = NodeCanvas(self.graph, self.undo_stack)
        self.canvas.nodeSelected.connect(self._on_node_selected)
        self.canvas.status.connect(self.set_status)

        self.props = PropertiesPanel(self.graph, self.undo_stack)

        self.source_view.createRegion.connect(self._on_create_region)
        self.source_view.createPolygon.connect(self._on_create_polygon)
        self.source_view.editPolygon.connect(self._on_edit_polygon)
        self.source_view.editRect.connect(self._on_edit_rect)
        self.source_view.selectRegion.connect(self._on_region_selected)
        self.source_view.pickColor.connect(self._on_pick_color)
        self.source_view.openClip.connect(self._open_clip)
        self.source_view.fileDropped.connect(self._load_clip)
        self.output_view.moveDest.connect(self._on_move_dest)
        self.output_view.scaleDest.connect(self._on_scale_dest)
        self.output_view.rotateDest.connect(self._on_rotate_dest)

        # ---- top toolbar
        bar = QWidget()
        bar.setObjectName("toolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 7, 10, 7)
        bl.setSpacing(8)

        btn_open = QPushButton("  Open Clip  ")
        btn_open.setObjectName("primary")
        btn_open.clicked.connect(self._open_clip)
        btn_tpl = QPushButton("Templates")
        btn_tpl.clicked.connect(self._template_browser)
        btn_exp = QPushButton("Export")
        btn_exp.clicked.connect(self._export)
        bl.addWidget(btn_open)
        bl.addWidget(btn_tpl)
        bl.addWidget(btn_exp)

        sep = QLabel("|")
        sep.setStyleSheet(f"color:{theme.BORDER_HI};")
        bl.addSpacing(4)
        bl.addWidget(sep)
        bl.addSpacing(4)
        self.btn_rect_mask = QPushButton("▭  Rect Mask")
        self.btn_rect_mask.setToolTip("Drag a rectangular HUD mask on the 16:9 (M)")
        self.btn_rect_mask.clicked.connect(
            lambda: self._arm_mask(self.source_view.arm_create))
        self.btn_poly_mask = QPushButton("⬠  Polygon Mask")
        self.btn_poly_mask.setToolTip(
            "Click points to draw a polygon HUD mask on the 16:9; "
            "click the first point / Enter to close (P)")
        self.btn_poly_mask.clicked.connect(
            lambda: self._arm_mask(self.source_view.arm_polygon))
        bl.addWidget(self.btn_rect_mask)
        bl.addWidget(self.btn_poly_mask)
        bl.addStretch(1)

        self.btn_src = QPushButton("16:9")
        self.btn_src.setObjectName("segL")
        self.btn_out = QPushButton("9:16")
        self.btn_out.setObjectName("segR")
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for i, b in enumerate((self.btn_src, self.btn_out)):
            b.setCheckable(True)
            grp.addButton(b, i)
            b.clicked.connect(lambda _=False, idx=i: self._show_viewport(idx))
        bl.addWidget(self.btn_src)
        bl.addWidget(self.btn_out)
        bl.addStretch(1)

        self.tb_guides = QPushButton("Guides")
        self.tb_guides.setCheckable(True)
        self.tb_guides.toggled.connect(lambda v: (self.output_view.toggle_guides(v),
                                                  self._render_current()))
        self.tb_fullq = QPushButton("Full Quality")
        self.tb_fullq.setCheckable(True)
        self.tb_fullq.toggled.connect(self._toggle_full_quality)
        self.tb_thumbs = QPushButton("Node Previews")
        self.tb_thumbs.setCheckable(True)
        self.tb_thumbs.toggled.connect(self._toggle_thumbs)
        bl.addWidget(self.tb_thumbs)
        bl.addWidget(self.tb_guides)
        bl.addWidget(self.tb_fullq)

        # ---- left: viewport + timeline
        self._vp_stack = QStackedWidget()
        self._vp_stack.addWidget(self.source_view)
        self._vp_stack.addWidget(self.output_view)
        left = _panel("Viewport", self._vp_stack, extra=self.timeline)

        # ---- right: node canvas + properties
        right = self._right_split = QSplitter(Qt.Orientation.Horizontal)
        right.addWidget(_panel("Node Graph", self.canvas.widget))
        right.addWidget(_panel("Properties", self.props))
        right.setSizes([720, 320])
        right.setStretchFactor(0, 1)

        self._main_split = QSplitter(Qt.Orientation.Horizontal)
        self._main_split.addWidget(left)
        self._main_split.addWidget(right)
        self._main_split.setSizes([620, 1000])
        self._main_split.setStretchFactor(1, 1)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(bar)
        cl.addWidget(self._main_split, 1)
        self.setCentralWidget(central)
        self._show_viewport(0)

    def _show_viewport(self, idx: int) -> None:
        self._vp_stack.setCurrentIndex(idx)
        (self.btn_src if idx == 0 else self.btn_out).setChecked(True)

    def _toggle_viewport(self) -> None:
        self._show_viewport(1 - self._vp_stack.currentIndex())

    def _build_view_menu_extras(self) -> None:
        self._view_menu.addSeparator()
        self.act_thumbs = QAction("Node Preview Thumbnails", self, checkable=True)
        self.act_thumbs.toggled.connect(lambda v: self.tb_thumbs.setChecked(v))
        self._view_menu.addAction(self.act_thumbs)
        self.act_fullq = QAction("Full-Quality Preview", self, checkable=True)
        self.act_fullq.toggled.connect(lambda v: self.tb_fullq.setChecked(v))
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

    def _arm_mask(self, arm_fn) -> None:
        """Make sure the 16:9 source view is up, then arm a mask tool on it."""
        if self._info is None:
            self.set_status("load a clip first")
            return
        self._show_viewport(0)
        arm_fn()
        self.source_view.setFocus()
        poly = getattr(arm_fn, "__name__", "") == "arm_polygon"
        self.set_status("click points, then click the first point or press Enter to close"
                        if poly else "drag a rectangle over the HUD element")

    def _refresh_overlays(self) -> None:
        regs = []
        for n in self._hud_nodes():
            shape = n.params["shape"].value if "shape" in n.params else "rect"
            regs.append({
                "id": n.id,
                "label": n.params["label"].value or n.title,
                "rect": tuple(n.params["source_rect"].value),
                "shape": shape,
                "points": n.polygon_points_source() if shape == "polygon" else [],
                "selected": n.id == self._selected_id,
            })
        # the webcam overlay is also lifted from a source sub-rect - let it be
        # dragged on the 16:9 like any other mask
        fc = self._facecam_node()
        if fc is not None:
            regs.append({
                "id": fc.id,
                "label": "Webcam",
                "rect": tuple(fc.params["source_rect"].value),
                "shape": "rect",
                "points": [],
                "selected": fc.id == self._selected_id,
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
        self.graph.set_param(rid, "reference_height", int(self._src_dims()[1]))
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

    _POLY_MIN = 0.02   # smallest polygon bounding box (source fraction)

    def _poly_bbox_and_local(self, pts):
        """Source-space points -> (clamped bbox rect, quad-local points str)."""
        from vcomp.core import coords
        from vcomp.nodes.region import bbox_of, format_points

        bx, by, bw, bh = bbox_of(pts)
        bw = max(self._POLY_MIN, bw)
        bh = max(self._POLY_MIN, bh)
        rect = coords.clamp_rect((bx, by, bw, bh))
        bx, by, bw, bh = rect
        local = [((px - bx) / bw, (py - by) / bh) for px, py in pts]
        return rect, format_points(local)

    def _on_create_polygon(self, pts) -> None:
        from vcomp.ui.commands import AddNodeCmd, SetParamCmd

        if len(pts) < 3:
            return
        clip = next(iter(self.graph.clip_source_nodes()), None)
        stack = next((n for n in self.graph.nodes.values() if n.type_name == "Stack"), None)
        rect, local = self._poly_bbox_and_local(pts)

        rid = self.graph.new_id("HUD Region")
        n_regions = len(self._hud_nodes())
        self.undo_stack.beginMacro("Create polygon mask")
        self.undo_stack.push(AddNodeCmd(self.graph, "HUD Region", rid))
        for name, val in (("shape", "polygon"), ("source_rect", rect),
                          ("polygon_points", local),
                          ("reference_height", int(self._src_dims()[1])),
                          ("dest_x", 0.5), ("dest_y", 0.08 + 0.06 * n_regions),
                          ("label", f"Region {n_regions + 1}")):
            self.undo_stack.push(SetParamCmd(self.graph, rid, name, val))
        if clip:
            self._safe_connect(clip.id, "image", rid, "image")
        if stack:
            self._safe_connect(rid, "image", stack.id, "layers")
        self.undo_stack.endMacro()

        self._selected_id = rid
        self.canvas.sync_from_core()
        self.canvas.focus_core_node(rid)
        self.props.show_node(rid)
        self._refresh_overlays()
        self._render_current()
        self.set_status("created polygon mask")

    def _on_edit_polygon(self, node_id, pts, final) -> None:
        from vcomp.ui.commands import SetParamsCmd

        if node_id not in self.graph.nodes or len(pts) < 3:
            return
        rect, local = self._poly_bbox_and_local(pts)
        self.undo_stack.push(SetParamsCmd(
            self.graph, node_id,
            {"source_rect": rect, "polygon_points": local, "shape": "polygon"},
            text="Edit polygon mask"))
        self._refresh_overlays()

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
        if self._pending_inout is not None:
            a, b = self._pending_inout
            self._pending_inout = None
            hi = max(0, info.frame_count - 1)
            a = max(0, min(a, hi))
            b = max(a, min(b if b > 0 else hi, hi))
            self.timeline._set_in(a)
            self.timeline._set_out(b)
        self._refresh_overlays()
        self._show_viewport(1)   # show the composited 9:16 result
        self._request_frame(0)

    def _request_frame(self, index: int) -> None:
        self.lbl_playhead.setText(f"f{index}")
        if index < self._req_prev - 1:      # loop wrap / backward scrub
            self._shown_src = self._shown_out = -1
        self._req_prev = index
        self.fetcher.request(index)

    def _on_frame(self, index: int, arr: np.ndarray) -> None:
        playing = self.timeline.is_playing
        # Paused: only the exact playhead frame matters. Playing: the pipeline
        # lags the wall-clock playhead, so take the freshest frame we get rather
        # than discarding everything and freezing the view.
        if playing:
            if index <= self._shown_src:
                self.timeline.set_cache_state(self.fetcher.cached_indices())
                return
            self._shown_src = index
        elif index != self.timeline.frame:
            self.timeline.set_cache_state(self.fetcher.cached_indices())
            return

        self._last_frame = arr
        if not (playing and self._vp_stack.currentIndex() == 1):
            self.source_view.set_frame(arr)
        self._render_current(index)
        self.timeline.set_cache_state(self.fetcher.cached_indices())

    def _render_current(self, idx: int | None = None) -> None:
        if idx is None:
            idx = self.timeline.frame
        fps = self._info.fps if self._info else 30.0
        frames = ({n.id: self._last_frame for n in self.graph.clip_source_nodes()}
                  if self._last_frame is not None else {})
        self.renderer.submit(idx, frames, idx / fps if fps else 0.0)

    def _on_play_state(self, playing: bool) -> None:
        self.renderer.playing = bool(playing)
        fps = self._info.fps if self._info else 30.0
        self.renderer.target_ms = 1000.0 / fps if fps > 0 else 33.0
        self.fetcher.set_readahead(16 if playing else 0)
        self._shown_src = self._shown_out = -1
        if not playing:
            # settle back to a crisp frame the moment playback stops
            if not self.renderer.lock_full_quality:
                self.renderer.preview_scale = 1.0
            self._render_current()

    def _on_composited(self, index: int, arr: np.ndarray) -> None:
        self._last_output = arr
        if self.timeline.is_playing:
            if index > self._shown_out:
                self._shown_out = index
                self.output_view.set_frame(arr)
        elif index == self.timeline.frame:
            self.output_view.set_frame(arr)
        # scale adaptation lives in the render worker now (fps-aware)
        lbl = {1.0: "1x", 0.75: "¾", 0.5: "½", 0.25: "¼"}.get(
            round(self.renderer.preview_scale, 2), f"{self.renderer.preview_scale:.2f}")
        self.lbl_preview.setText("Preview 1x" if self.renderer.lock_full_quality
                                 else f"Preview {lbl}")

    def _on_gl_ready(self, renderer: str) -> None:
        self.lbl_gpu.setText(f"GPU: {renderer[:40]}")
        self.set_status("GL renderer ready")

    def _on_fail(self, msg: str) -> None:
        self.set_status(f"error: {msg}")
        QMessageBox.critical(self, "CLIPR", f"Error:\n{msg}")

    # ---------------------------------------------------------------- layout
    _LAYOUT_VERSION = 3

    def _restore_layout(self) -> None:
        if self.settings.get("layout_version") != self._LAYOUT_VERSION:
            return
        geo = self.settings.get("window_geometry")
        try:
            if geo:
                self.restoreGeometry(base64.b64decode(geo))
            for split, key in ((self._main_split, "split_main"),
                               (self._right_split, "split_right")):
                data = self.settings.get(key)
                if data:
                    split.restoreState(base64.b64decode(data))
        except (ValueError, TypeError):
            log.warning("Could not restore layout")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timeline.set_playing(False)
        self._autosave.stop()
        self.fetcher.stop()
        self.renderer.stop()
        # clean shutdown -> drop crash-recovery autosaves so the next launch
        # doesn't falsely claim CLIPR didn't close cleanly
        try:
            from vcomp.core.autosave import clear_recovery
            clear_recovery()
            self.settings.set("recovery_declined", "")
        except Exception:  # noqa: BLE001
            log.exception("clear recovery on close")
        self.settings.set("layout_version", self._LAYOUT_VERSION)
        self.settings.set("window_geometry",
                          base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        self.settings.set("split_main",
                          base64.b64encode(bytes(self._main_split.saveState())).decode("ascii"))
        self.settings.set("split_right",
                          base64.b64encode(bytes(self._right_split.saveState())).decode("ascii"))
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
        except (ValueError, OSError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Open", str(exc))
            return
        self._load_project_obj(proj, status=f"opened {path}", project_path=path)

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
    def _has_unsaved_work(self) -> bool:
        """Worth autosaving? A clip is loaded, or the user has edited the graph."""
        if self._info is not None:
            return True
        try:
            return not self.undo_stack.isClean()
        except Exception:  # noqa: BLE001
            return len(self.graph.nodes) > 1

    def _do_autosave(self) -> None:
        if not self._has_unsaved_work():
            return
        from vcomp.core.autosave import write_autosave
        from vcomp.core.project import Project

        p = Project(graph=self.graph, in_point=self.timeline.in_point,
                    out_point=self.timeline.out_point)
        if write_autosave(p):
            self.lbl_action.setText("autosaved")

    def _offer_recovery(self) -> None:
        from vcomp.core.autosave import clear_recovery, recoverable
        from vcomp.core.project import Project

        cands = recoverable()
        if not cands:
            return
        # skip if the user already declined this exact autosave last launch
        last_declined = self.settings.get("recovery_declined") or ""
        if last_declined == cands[0].name:
            return

        newest = cands[0]
        if QMessageBox.question(
                self, "Recover unsaved work",
                f"CLIPR didn't close cleanly.\n\nRestore the autosave from "
                f"{newest.stem.replace('autosave_', '').replace('_', ' ')}?",
        ) != QMessageBox.StandardButton.Yes:
            self.settings.set("recovery_declined", newest.name)
            self.settings.save()
            return

        for path in cands:
            try:
                proj = Project.load(path)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                log.warning("autosave %s unreadable: %s", path.name, exc)
                continue
            self._load_project_obj(proj, status=f"recovered autosave ({path.stem})")
            self.settings.set("recovery_declined", "")
            self.settings.save()
            clear_recovery()
            return

        self.set_status("recovery failed - all autosaves unreadable")

    def _load_project_obj(self, proj, *, status: str, project_path=None) -> None:
        """Shared post-load: swap the graph in, rebuild the canvas, reload media,
        restore the timeline range."""
        self.graph.load_dict(proj.graph.to_dict())
        self.undo_stack.clear()
        self._project_path = project_path
        self._info = None
        self._shown_src = self._shown_out = -1
        self.canvas.sync_from_core()

        clip = next(iter(self.graph.clip_source_nodes()), None)
        path = clip.params["file_path"].value if clip else ""
        if path and os.path.exists(path):
            self._pending_inout = (int(proj.in_point), int(proj.out_point))
            self.fetcher.open(path, self._orientation_override())
        else:
            if path:
                self.set_status(f"media not found: {path} - use Open Clip to relink")
            self._refresh_overlays()
            self._render_current()
        self.set_status(status)

    def _set_preview_scale(self, s: float) -> None:
        self.renderer.preview_scale = s
        label = {0.25: "¼", 0.5: "½", 1.0: "1x"}[s]
        self.lbl_preview.setText(f"Preview {label}")
        self._render_current()

    def _frame_selection(self) -> None:
        for v in (self.source_view, self.output_view):
            v.reset_view()

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
