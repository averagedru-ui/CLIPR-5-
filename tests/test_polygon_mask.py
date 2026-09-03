"""Polygon HUD-mask: draw-tool plumbing + render coverage."""
from __future__ import annotations

import os

import numpy as np
import pytest

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.region import (
    _bake_polygon_mask,
    bbox_of,
    format_points,
    parse_point_string,
)
from vcomp.nodes.registry import get, load_builtin_nodes

load_builtin_nodes()

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI")


@pytest.fixture()
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_point_string_roundtrip():
    pts = [(0.1, 0.2), (0.9, 0.15), (0.5, 0.95)]
    got = parse_point_string(format_points(pts))
    assert len(got) == 3
    for (gx, gy), (x, y) in zip(got, pts):
        assert gx == pytest.approx(x) and gy == pytest.approx(y)
    assert parse_point_string("garbage; 0.5,0.5 ;x,y;1,2,3") == [(0.5, 0.5), (1.0, 2.0)]


def test_bbox_of():
    assert bbox_of([(0.2, 0.3), (0.7, 0.1), (0.5, 0.9)]) == pytest.approx((0.2, 0.1, 0.5, 0.8))


def test_polygon_points_source_maps_through_source_rect():
    r = get("HUD Region")("r")
    r.params["shape"].set("polygon")
    r.params["source_rect"].set((0.2, 0.1, 0.4, 0.5))
    r.params["polygon_points"].set("0,0;1,0;1,1;0,1")
    src = r.polygon_points_source()
    assert src[0] == pytest.approx((0.2, 0.1))
    assert src[2] == pytest.approx((0.6, 0.6))


def test_create_polygon_builds_tight_bbox(app):
    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    win = MainWindow(Settings())
    win._info = type("I", (), {"display_width": 1920, "display_height": 1080,
                               "fps": 60.0, "duration": 10.0, "path": "x.mp4"})()

    # a triangle in source space
    tri = [(0.30, 0.40), (0.70, 0.35), (0.55, 0.80)]
    win._on_create_polygon(tri)

    regs = [n for n in win.graph.nodes.values() if n.type_name == "HUD Region"]
    assert len(regs) == 1
    reg = regs[0]
    assert reg.params["shape"].value == "polygon"
    x, y, w, h = reg.params["source_rect"].value
    assert (x, y) == pytest.approx((0.30, 0.35))
    assert (w, h) == pytest.approx((0.40, 0.45))
    # local points span the full 0..1 quad (bbox is tight)
    local = parse_point_string(reg.params["polygon_points"].value)
    xs = [p[0] for p in local]
    ys = [p[1] for p in local]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(1.0)
    # round-trips back to the same source-space triangle
    for (gx, gy), (x, y) in zip(reg.polygon_points_source(), tri):
        assert gx == pytest.approx(x, abs=1e-4) and gy == pytest.approx(y, abs=1e-4)
    win.close()


def test_edit_polygon_is_single_undo_entry(app):
    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    win = MainWindow(Settings())
    win._info = type("I", (), {"display_width": 1920, "display_height": 1080,
                               "fps": 60.0, "duration": 10.0, "path": "x.mp4"})()
    win._on_create_polygon([(0.3, 0.4), (0.7, 0.35), (0.55, 0.8)])
    reg = next(n for n in win.graph.nodes.values() if n.type_name == "HUD Region")

    before = win.undo_stack.index()
    for _ in range(5):   # a drag stream
        win._on_edit_polygon(reg.id, [(0.31, 0.4), (0.7, 0.35), (0.55, 0.8)], False)
    win._on_edit_polygon(reg.id, [(0.32, 0.4), (0.7, 0.35), (0.55, 0.8)], True)
    assert win.undo_stack.index() == before + 1   # coalesced
    win.close()


def test_polygon_mask_coverage(compositor):
    """A triangle polygon must cover roughly half its bounding box on canvas."""
    g = Graph()
    clip = g.add_node("Clip Source")
    reg = g.add_node("HUD Region")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", reg.id, "image")
    g.connect(reg.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    clip.set_media_info(640, 360, 30.0, 2.0)

    for k, v in dict(shape="polygon", source_rect=(0.0, 0.0, 1.0, 1.0),
                     polygon_points="0.5,0.0;1.0,1.0;0.0,1.0",
                     dest_x=0.5, dest_y=0.5, dest_anchor="center",
                     dest_scale=1.0, feather=0.0, reference_height=360).items():
        g.set_param(reg.id, k, v)

    src = np.full((360, 640, 3), (0, 200, 0), np.uint8)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    r = g.evaluate(ctx)
    ctx.release_all()

    green = int((r[..., 1] > 100).sum())
    # the region quad keeps the source's pixel size: ~ (sw*src_w) x (sh*src_h)
    quad_px = (1.0 * 640) * (1.0 * 360)
    # a triangle fills ~half its bounding quad (slack for AA / dest rounding)
    assert 0.35 * quad_px < green < 0.65 * quad_px
