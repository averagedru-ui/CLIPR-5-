"""M4: HUD Region node - shapes, feather, placement, polygon mask."""
from __future__ import annotations

import numpy as np
import pytest

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.region import _bake_polygon_mask
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()


def _checker(w=640, h=360) -> np.ndarray:
    a = np.zeros((h, w, 3), np.uint8)
    a[:, : w // 2] = (220, 40, 40)
    a[:, w // 2:] = (40, 220, 40)
    return a


def test_polygon_mask_bake():
    tri = [(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)]
    m = _bake_polygon_mask(tri, res=64)
    assert m.shape == (64, 64, 3)
    assert m[40, 32, 0] > 200         # well inside
    assert m[5, 5, 0] < 40            # top-left: outside
    assert m[5, 58, 0] < 40           # top-right: outside


def _eval_region(compositor, **params):
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
    for k, v in params.items():
        g.set_param(reg.id, k, v)

    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: _checker()})
    res = g.evaluate(ctx)
    ctx.release_all()
    return res


def test_rect_region_lands_on_canvas(compositor):
    out = _eval_region(
        compositor,
        shape="rect",
        source_rect=(0.0, 0.0, 0.5, 1.0),     # left (red) half of source
        dest_x=0.5, dest_y=0.5, dest_anchor="center",
        dest_scale=2.0, feather=0.0, reference_height=360,
    )
    assert out.shape == (1920, 1080, 4)
    # centre of canvas should now be red (the lifted left half)
    cx, cy = 540, 960
    assert out[cy, cx, 0] > 150 and out[cy, cx, 1] < 90
    # far corner stays clear -> composited over black
    assert tuple(out[5, 5, :3]) == (0, 0, 0)


def test_dest_rect_is_resolution_independent():
    """A region authored at one clip resolution must place identically when the
    same params are applied to a different-resolution clip of the same aspect."""
    from vcomp.nodes.registry import get

    def quad(clip_w, clip_h):
        r = get("HUD Region")("r")
        r.params["source_rect"].set((0.86, 0.88, 0.12, 0.06))
        r.params["reference_height"].set(1440)   # authored on a 1440p clip
        r.params["dest_scale"].set(1.25)
        r.params["dest_x"].set(0.82)
        r.params["dest_y"].set(0.80)
        return r.dest_rect_for(1080, 1920, clip_w, clip_h)

    a = quad(2560, 1440)
    b = quad(1920, 1080)
    assert all(abs(x - y) < 1e-6 for x, y in zip(a, b))


def test_ellipse_feather_has_soft_edge(compositor):
    out = _eval_region(
        compositor, shape="ellipse",
        source_rect=(0.0, 0.0, 1.0, 1.0),
        dest_x=0.5, dest_y=0.5, dest_anchor="center", dest_scale=1.5,
        feather=48.0,
    )
    # Output makes the final frame opaque, so probe RGB instead: the region
    # (checker) fades to black at the feathered edge -> intermediate values.
    row = out[960, :, 1].astype(np.int32)   # green channel through the centre
    assert ((row > 15) & (row < 205)).sum() > 40


def test_disabled_region_passes_through_empty(compositor):
    out = _eval_region(compositor, shape="rect", enabled=False) \
        if False else None
    # enabled is not a param; toggling handled by graph.set_enabled
    g = Graph()
    clip = g.add_node("Clip Source")
    reg = g.add_node("HUD Region")
    stack = g.add_node("Stack")
    o = g.ensure_output()
    g.connect(clip.id, "image", reg.id, "image")
    g.connect(reg.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", o.id, "image")
    g.set_param(o.id, "background_clear_color", (0, 0, 0, 1))
    g.set_enabled(reg.id, False)
    clip.set_media_info(640, 360, 30.0, 2.0)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: _checker()})
    res = g.evaluate(ctx)
    ctx.release_all()
    assert tuple(res[960, 540, :3]) == (0, 0, 0)
