"""M5: backgrounds, modifiers, value nodes."""
from __future__ import annotations

import numpy as np
import pytest

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.registry import load_builtin_nodes
from vcomp.nodes.value import ExpressionError, safe_expression

load_builtin_nodes()


# ------------------------------------------------------------- expression
def test_expression_whitelist_ok():
    assert safe_expression("clamp(a*b + 1, 0, 10)", {"a": 3, "b": 4}) == 10.0
    assert abs(safe_expression("sin(pi/2)", {"pi": 3.14159265}) - 1.0) < 1e-4


def test_expression_rejects_dunder():
    with pytest.raises((ExpressionError, SyntaxError)):
        safe_expression("__import__('os').system('x')", {})
    with pytest.raises(ExpressionError):
        safe_expression("a.b", {"a": 1})


# ------------------------------------------------------------------ helpers
def _bg_graph(bg_type: str, **params):
    g = Graph()
    bg = g.add_node(bg_type)
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(bg.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))
    for k, v in params.items():
        g.set_param(bg.id, k, v)
    return g, bg


def _render(compositor, g):
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {})
    r = g.evaluate(ctx)
    ctx.release_all()
    return r


def test_gradient_background(compositor):
    g, _ = _bg_graph("Gradient Background", type="linear", angle=90.0,
                     stops="0:1,0,0,1 ; 1:0,0,1,1", interpolation="sRGB", dither=False)
    out = _render(compositor, g)
    top = out[10, 540, :3]
    bot = out[1900, 540, :3]
    assert (top[0] > 150) != (bot[0] > 150)   # red at one end, blue at the other


def test_blur_background_softens(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    blur = g.add_node("Blur Background")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", blur.id, "image")
    g.connect(blur.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    clip.set_media_info(640, 360, 30.0, 2.0)
    g.set_param(blur.id, "blur_radius", 120.0)
    g.set_param(blur.id, "vignette_amount", 0.0)
    g.set_param(blur.id, "overlay_opacity", 0.0)
    g.set_param(blur.id, "brightness", 1.0)

    src = np.zeros((360, 640, 3), np.uint8)
    src[:, :320] = (240, 0, 0)
    src[:, 320:] = (0, 0, 240)
    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    res = g.evaluate(ctx)
    ctx.release_all()
    # hard red/blue seam should now have purple-ish transition pixels
    mid_col = res[:, 540, :3].astype(np.int32)
    assert ((mid_col[:, 0] > 30) & (mid_col[:, 2] > 30)).sum() > 100


def test_color_adjust_exposure(compositor):
    g = Graph()
    bg = g.add_node("Solid Background")
    adj = g.add_node("Color Adjust")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(bg.id, "image", adj.id, "image")
    g.connect(adj.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(bg.id, "color", (0.25, 0.25, 0.25, 1.0))
    g.set_param(adj.id, "exposure", 1.0)   # +1 stop -> ~2x
    out_arr = _render(compositor, g)
    v = int(out_arr[960, 540, 0])
    assert 120 < v < 140     # 0.25 * 2 = 0.5 -> ~127


def test_stack_per_layer_blend(compositor):
    g = Graph()
    a = g.add_node("Solid Background")
    b = g.add_node("Solid Background")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(a.id, "image", stack.id, "layers")
    g.connect(b.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(a.id, "color", (0.5, 0.5, 0.5, 1.0))
    g.set_param(b.id, "color", (0.5, 0.5, 0.5, 1.0))
    g.set_param(stack.id, "blends", "normal,add")   # layer1 (top) adds
    res = _render(compositor, g)
    assert res[960, 540, 0] > 240    # 0.5 + 0.5 = 1.0


def test_disabled_modifier_bypasses(compositor):
    g = Graph()
    bg = g.add_node("Solid Background")
    adj = g.add_node("Color Adjust")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(bg.id, "image", adj.id, "image")
    g.connect(adj.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(bg.id, "color", (0.3, 0.3, 0.3, 1.0))
    g.set_param(adj.id, "exposure", 3.0)
    g.set_enabled(adj.id, False)
    res = _render(compositor, g)
    assert abs(int(res[960, 540, 0]) - 77) < 3    # 0.3*255, adjust bypassed
