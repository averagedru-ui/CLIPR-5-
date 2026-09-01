"""Scaling Main Framing past 1.0 overflows the canvas (crop, not squish)."""
from __future__ import annotations

import numpy as np

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.framing import _fit_dest
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()


def test_fit_width_letterbox_not_squished():
    x0, y0, x1, y1 = _fit_dest("fit_width", 1080, 1920, 1920, 1080, (0.5, 0.5), 1.0)
    assert (x0, x1) == (0.0, 1.0)
    band = (y1 - y0)
    assert abs(band - (1080 / 1920) * (9 / 16) ** -1 * 0) < 1  # sanity
    assert 0.30 < band < 0.34          # ~9/16 of a 16:9 band inside 9:16


def test_scale_up_overflows_edges():
    d = _fit_dest("fit_width", 1080, 1920, 1920, 1080, (0.5, 0.5), 2.5)
    assert d[0] < 0.0 and d[2] > 1.0   # left+right past the frame
    # centred
    assert abs((d[0] + d[2]) - 1.0) < 1e-6


def test_fill_covers_and_overflows():
    d = _fit_dest("fill", 1080, 1920, 1920, 1080, (0.5, 0.5), 1.0)
    assert d[1] >= -1e-6 and d[3] <= 1.0 + 1e-6   # height fits
    assert d[0] < 0.0 and d[2] > 1.0              # width overflows (cover)


def test_pan_shifts_when_overflowing():
    left = _fit_dest("fit_width", 1080, 1920, 1920, 1080, (0.5, 0.5), 3.0, pan_x=0.0)
    right = _fit_dest("fit_width", 1080, 1920, 1920, 1080, (0.5, 0.5), 3.0, pan_x=1.0)
    assert left[0] > right[0]           # pan_x=0 shows the left side -> quad pushed right


def test_scaled_render_still_full_frame(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    fr = g.add_node("Main Framing")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", fr.id, "image")
    g.connect(fr.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    clip.set_media_info(1280, 720, 30.0, 2.0)
    g.set_param(fr.id, "fit_mode", "fill")   # cover the canvas
    g.set_param(fr.id, "dest_scale", 1.0)

    src = np.zeros((720, 1280, 3), np.uint8)
    src[:] = (50, 150, 210)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    res = g.evaluate(ctx)
    ctx.release_all()
    # fill mode covers the whole 9:16 frame edge-to-edge, no black band
    assert tuple(res[10, 10, :3]) == (50, 150, 210)
    assert tuple(res[1900, 1070, :3]) == (50, 150, 210)


def test_skew_shears_content(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    fr = g.add_node("Main Framing")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", fr.id, "image")
    g.connect(fr.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    clip.set_media_info(640, 360, 30.0, 2.0)
    g.set_param(fr.id, "fit_mode", "fill")
    g.set_param(fr.id, "skew_x", 0.5)

    src = np.zeros((360, 640, 3), np.uint8)
    src[:, :320] = (255, 0, 0)
    src[:, 320:] = (0, 0, 255)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    res = g.evaluate(ctx)
    ctx.release_all()
    # with horizontal skew the red/blue boundary is at different x on top vs bottom rows
    def boundary(row):
        r = res[row, :, 0].astype(int)
        b = res[row, :, 2].astype(int)
        xs = np.where((r > 150) & (b < 80))[0]
        return xs.max() if len(xs) else -1
    assert abs(boundary(300) - boundary(1600)) > 20
