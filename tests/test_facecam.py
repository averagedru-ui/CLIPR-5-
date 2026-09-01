"""Facecam / webcam overlay: placement presets + toggle via graph enable."""
from __future__ import annotations

import numpy as np

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()


def test_placement_presets():
    fc = Graph().add_node("Facecam") if False else None
    g = Graph()
    fc = g.add_node("Facecam")
    g.set_param(fc.id, "margin", 0.05)

    g.set_param(fc.id, "placement", "top-left")
    cx, cy = fc.dest_center(0.3, 0.2)
    assert cx == 0.05 + 0.15 and cy == 0.05 + 0.10

    g.set_param(fc.id, "placement", "bottom-right")
    cx, cy = fc.dest_center(0.3, 0.2)
    assert abs(cx - (1 - 0.05 - 0.15)) < 1e-9
    assert abs(cy - (1 - 0.05 - 0.10)) < 1e-9

    g.set_param(fc.id, "placement", "top-center")
    cx, cy = fc.dest_center(0.3, 0.2)
    assert cx == 0.5

    g.set_param(fc.id, "placement", "custom")
    g.set_param(fc.id, "dest_x", 0.7)
    g.set_param(fc.id, "dest_y", 0.9)
    assert fc.dest_center(0.3, 0.2) == (0.7, 0.9)


def test_facecam_renders_in_the_chosen_corner(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    fc = g.add_node("Facecam")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", fc.id, "image")
    g.connect(fc.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    clip.set_media_info(1280, 720, 30.0, 2.0)
    g.set_param(fc.id, "source_rect", (0.0, 0.0, 1.0, 1.0))
    g.set_param(fc.id, "shape", "rect")
    g.set_param(fc.id, "feather", 0.0)
    g.set_param(fc.id, "border_width", 0.0)
    g.set_param(fc.id, "placement", "top-left")
    g.set_param(fc.id, "margin", 0.04)
    g.set_param(fc.id, "size", 0.4)

    src = np.full((720, 1280, 3), (0, 220, 90), np.uint8)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    res = g.evaluate(ctx)
    ctx.release_all()

    assert tuple(res[120, 120, :3]) == (0, 220, 90)      # top-left has the cam
    assert tuple(res[1800, 950, :3]) == (0, 0, 0)          # bottom-right empty


def test_disabled_facecam_contributes_nothing(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    fc = g.add_node("Facecam")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", fc.id, "image")
    g.connect(fc.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    g.set_enabled(fc.id, False)
    clip.set_media_info(1280, 720, 30.0, 2.0)
    src = np.full((720, 1280, 3), (255, 0, 0), np.uint8)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    res = g.evaluate(ctx)
    ctx.release_all()
    assert tuple(res[100, 100, :3]) == (0, 0, 0)


def test_builtins_carry_disabled_facecam():
    from vcomp.templates import builtin

    for t in builtin.build_all():
        g = Graph()
        g.load_dict(t.graph)
        fcs = [n for n in g.nodes.values() if n.type_name == "Facecam"]
        assert len(fcs) == 1
        assert fcs[0].enabled is False
