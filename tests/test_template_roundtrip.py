"""Pixel-level guarantee that saving a template and reapplying it reproduces the
exact same picture - the thing "my mask isn't where I placed it" would break.

Param-level equality is already checked elsewhere; this renders through the real
compositor so a change anywhere between the saved JSON and the final pixels
(remap, defaults, load_dict, dest-rect math) is caught, not just a param diff.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from vcomp.core.graph import EvalContext, Graph, build_default_graph
from vcomp.nodes.registry import load_builtin_nodes
from vcomp.templates.io import (
    TemplateMeta,
    apply_template,
    load_template,
    template_from_graph,
)

load_builtin_nodes()


def _gradient_source(w: int, h: int) -> np.ndarray:
    """Coordinate-encoded frame: R = x, G = y. Any misplaced mask shows up as a
    shifted colour, and it stays smooth across resolutions (no resample noise)."""
    xs = np.linspace(0, 255, w, dtype=np.float32)[None, :].repeat(h, 0)
    ys = np.linspace(0, 255, h, dtype=np.float32)[:, None].repeat(w, 1)
    b = np.full((h, w), 90, np.float32)
    return np.dstack([xs, ys, b]).astype(np.uint8)


def _build_graph(src_w: int, src_h: int) -> Graph:
    g = build_default_graph(Graph())
    clip = g.clip_source_nodes()[0]
    clip.set_media_info(src_w, src_h, 30.0, 5.0)
    stack = next(n for n in g.nodes.values() if n.type_name == "Stack")

    def add_region(shape, rect, dest, scale=1.0, rot=0.0, pts=""):
        n = g.add_node("HUD Region")
        g.set_param(n.id, "shape", shape)
        g.set_param(n.id, "source_rect", rect)
        g.set_param(n.id, "reference_height", src_h)
        g.set_param(n.id, "dest_x", dest[0])
        g.set_param(n.id, "dest_y", dest[1])
        g.set_param(n.id, "dest_scale", scale)
        g.set_param(n.id, "rotation", rot)
        if pts:
            g.set_param(n.id, "polygon_points", pts)
        g.connect(clip.id, "image", n.id, "image")
        g.connect(n.id, "image", stack.id, "layers")
        return n

    add_region("rect", (0.02, 0.03, 0.22, 0.20), (0.30, 0.10))
    add_region("ellipse", (0.70, 0.60, 0.25, 0.30), (0.72, 0.85), scale=1.4)
    # triangle drawn on the source, stored the way the polygon tool stores it:
    # tight bbox as source_rect, points in 0..1 quad space
    add_region("polygon", (0.30, 0.35, 0.40, 0.45), (0.50, 0.45), rot=12.0,
               pts="0,0;1,0.05;0.55,1")
    return g


def _render(compositor, g: Graph, src: np.ndarray) -> np.ndarray:
    clip = g.clip_source_nodes()[0]
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    out = g.evaluate(ctx)
    ctx.release_all()
    return np.asarray(out).copy()


def _save_reload(g: Graph, ref_res, tmp_path):
    tpl = template_from_graph(g, TemplateMeta(name="rt"), ref_res)
    path = tmp_path / "rt.vctpl"
    # written raw: save_template() also mirrors into web/public/templates
    path.write_text(json.dumps(tpl.to_dict(), indent=2), encoding="utf-8")
    return load_template(path)


def _reapply(tpl, clip_res) -> Graph:
    """Mirrors MainWindow._apply_template: apply onto a working graph, then
    restore the clip's media info."""
    tmp = build_default_graph(Graph())
    apply_template(tmp, tpl, clip_res)
    for n in tmp.clip_source_nodes():
        n.set_media_info(clip_res[0], clip_res[1], 30.0, 5.0)
    return tmp


def test_reapply_same_clip_is_pixel_identical(compositor, tmp_path):
    src = _gradient_source(1920, 1080)
    g1 = _build_graph(1920, 1080)
    before = _render(compositor, g1, src)

    tpl = _save_reload(g1, (1920, 1080), tmp_path)
    g2 = _reapply(tpl, (1920, 1080))
    after = _render(compositor, g2, src)

    assert before.shape == after.shape
    diff = np.abs(before.astype(int) - after.astype(int))
    assert diff.max() == 0, f"max pixel diff {diff.max()} at {np.argwhere(diff > 0)[:3].tolist()}"


def _mask_of(frame: np.ndarray) -> np.ndarray:
    """Binary 'where did a region land' mask from a solid-magenta source on a
    black canvas (crisp edges, no resample noise to hide a shift behind)."""
    return (frame[..., 0] > 128) & (frame[..., 2] > 128)


@pytest.mark.parametrize("res", [(2560, 1440), (3840, 2160), (1280, 720)])
def test_reapply_other_16x9_resolution_lands_in_same_place(compositor, tmp_path, res):
    """Author at 1080p, reapply to a different 16:9 clip: every mask must land
    in the same place on the vertical canvas.

    A smooth-gradient photometric compare is far too forgiving for this (an ~8px
    shift only moves a 1920-wide gradient by ~2/255), so this uses a solid
    colour source and compares the resulting binary masks geometrically."""
    def solid(w, h):
        s = np.zeros((h, w, 3), np.uint8)
        s[:] = (255, 0, 255)
        return s

    g1 = _build_graph(1920, 1080)
    for n in g1.nodes.values():
        if n.type_name == "Main Framing":       # keep only the region layers
            g1.set_enabled(n.id, False)
        if n.type_name == "Blur Background":
            g1.set_enabled(n.id, False)
    before = _mask_of(_render(compositor, g1, solid(1920, 1080)))

    tpl = _save_reload(g1, (1920, 1080), tmp_path)
    g2 = _reapply(tpl, res)
    after = _mask_of(_render(compositor, g2, solid(*res)))

    assert before.any(), "test setup produced no visible masks"
    inter = np.logical_and(before, after).sum()
    union = np.logical_or(before, after).sum()
    iou = inter / union
    by, bx = np.argwhere(before).mean(0)
    ay, ax = np.argwhere(after).mean(0)
    assert iou > 0.995, f"mask overlap IoU {iou:.4f}"
    assert abs(by - ay) < 0.5 and abs(bx - ax) < 0.5, f"centroid moved ({ax - bx:.2f}, {ay - by:.2f}) px"


def test_test_would_notice_a_mask_drifting(compositor, tmp_path):
    """Guard against the check above going blind: an ~8px nudge on a 1080p clip
    has to fail it."""
    s = np.zeros((1080, 1920, 3), np.uint8)
    s[:] = (255, 0, 255)
    g1 = _build_graph(1920, 1080)
    for n in g1.nodes.values():
        if n.type_name in ("Main Framing", "Blur Background"):
            g1.set_enabled(n.id, False)
    before = _mask_of(_render(compositor, g1, s))

    tpl = _save_reload(g1, (1920, 1080), tmp_path)
    g2 = _reapply(tpl, (1920, 1080))
    poly = next(n for n in g2.nodes.values()
                if n.type_name == "HUD Region" and n.params["shape"].value == "polygon")
    # where a mask lands on the canvas is dest_x/dest_y (source_rect only picks
    # *what* is sampled, invisible on a solid source): 0.008 * 1080 ~= 8.6px
    poly.params["dest_x"].set(poly.params["dest_x"].value + 0.008)
    after = _mask_of(_render(compositor, g2, s))

    inter = np.logical_and(before, after).sum()
    union = np.logical_or(before, after).sum()
    assert inter / union < 0.995


def test_reapply_twice_is_stable(compositor, tmp_path):
    """Applying, re-saving and applying again must not walk the placement."""
    src = _gradient_source(1920, 1080)
    g1 = _build_graph(1920, 1080)
    first = _render(compositor, g1, src)

    tpl = _save_reload(g1, (1920, 1080), tmp_path)
    g2 = _reapply(tpl, (1920, 1080))
    tpl2 = _save_reload(g2, (1920, 1080), tmp_path)
    g3 = _reapply(tpl2, (1920, 1080))
    third = _render(compositor, g3, src)

    assert np.abs(first.astype(int) - third.astype(int)).max() == 0


# ------------------------------------------------------------------ GUI path
def _gui_window():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    app = QApplication.instance() or QApplication([])
    win = MainWindow(Settings())
    win._info = type("I", (), {"display_width": 1920, "display_height": 1080,
                               "fps": 60.0, "duration": 10.0, "path": "x.mp4"})()
    return app, win


def _overlay_snapshot(win):
    """What the user actually sees drawn on the 16:9 source view."""
    win._refresh_overlays()
    out = []
    for r in win.source_view._regions:
        out.append((
            r["label"], r["shape"],
            tuple(round(v, 6) for v in r["rect"]),
            [tuple(round(c, 6) for c in p) for p in r["points"]],
        ))
    return sorted(out)


def test_gui_mask_overlay_identical_after_save_and_apply(tmp_path):
    """The exact user flow: draw masks in the UI, save a template, reapply it -
    the outlines the user sees on the source view must not move."""
    _app, win = _gui_window()
    win._on_create_polygon([(0.30, 0.40), (0.70, 0.35), (0.55, 0.80)])
    win._on_create_region(0.05, 0.06, 0.18, 0.12)
    before = _overlay_snapshot(win)
    assert len(before) >= 2

    tpl = _save_reload(win.graph, win._src_dims(), tmp_path)
    win._new_project()                       # start from a clean default graph
    assert _overlay_snapshot(win) != before  # sanity: really cleared
    win._apply_template(tpl)
    after = _overlay_snapshot(win)

    assert after == before
