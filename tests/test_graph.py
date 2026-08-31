"""M3: params, graph topology, evaluation through the GL compositor."""
from __future__ import annotations

import numpy as np
import pytest

from vcomp.core.params import Param, ParamType
from vcomp.core.graph import Graph, GraphError, build_default_graph
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()


# ------------------------------------------------------------------- params
def test_param_resolution_order():
    p = Param("x", ParamType.FLOAT, 1.0)
    assert p.evaluate(0.0) == 1.0
    p.set(5.0)
    assert p.evaluate(0.0) == 5.0
    assert p.evaluate(0.0, upstream=lambda: 9.0) == 9.0  # port wins


def test_param_clamp_and_keyframes():
    p = Param("x", ParamType.FLOAT, 0.0, min=0.0, max=10.0)
    p.set(50.0)
    assert p.evaluate(0.0) == 10.0
    from vcomp.core.params import Keyframe

    p.keyframes = [Keyframe(0.0, 0.0), Keyframe(2.0, 10.0)]
    assert abs(p.evaluate(1.0) - 5.0) < 1e-6


# ----------------------------------------------------------------- topology
def test_cycle_detection():
    g = Graph()
    a = g.add_node("Main Framing")
    b = g.add_node("Stack")
    g.connect(a.id, "image", b.id, "layers")
    with pytest.raises(GraphError):
        g.connect(b.id, "image", a.id, "image")


def test_type_mismatch_rejected():
    g = Graph()
    v = g.add_node("Value")
    s = g.add_node("Stack")
    with pytest.raises(GraphError):
        g.connect(v.id, "value", s.id, "layers")   # Number -> Image


def test_output_singleton_and_undeletable():
    g = Graph()
    g.add_node("Output")
    with pytest.raises(GraphError):
        g.add_node("Output")
    with pytest.raises(GraphError):
        g.remove_node(g.output_node().id)


def test_serialize_roundtrip():
    g = Graph()
    build_default_graph(g)
    g.set_param(g.clip_source_nodes()[0].id, "speed", 2.0)
    data = g.to_dict()

    g2 = Graph()
    g2.load_dict(data)
    assert len(g2.nodes) == len(g.nodes)
    assert len(g2.connections) == len(g.connections)
    assert g2.clip_source_nodes()[0].params["speed"].value == 2.0


# --------------------------------------------------------------- evaluation
def test_default_graph_evaluates(compositor):
    from vcomp.core.graph import EvalContext

    g = Graph()
    build_default_graph(g)
    clip = g.clip_source_nodes()[0]
    clip.set_media_info(1280, 720, 60.0, 4.0)

    src = np.zeros((720, 1280, 3), np.uint8)
    src[:] = (200, 60, 40)
    g.set_param(g.output_node().id, "render_scale", 1.0)
    g.set_param(g.output_node().id, "background_clear_color", (0, 0, 0, 1))
    # solid bg node -> dark grey
    bg_id = [n.id for n in g.nodes.values() if n.type_name == "Solid Background"][0]
    g.set_param(bg_id, "color", (0.1, 0.1, 0.1, 1.0))

    cw, ch, rs = g.canvas_params()
    ctx = EvalContext(compositor, t=0.0, canvas_w=cw, canvas_h=ch, render_scale=1.0,
                      frames={clip.id: src})
    out = g.evaluate(ctx)
    ctx.release_all()

    assert out.shape == (1920, 1080, 4)
    assert all(abs(int(v) - 25) <= 1 for v in out[5, 5, :3])       # background band
    assert all(abs(int(a) - b) <= 2 for a, b in zip(out[960, 540, :3], (200, 60, 40)))


def test_frame_cache_hits(compositor):
    from vcomp.core.graph import EvalContext

    g = Graph()
    build_default_graph(g)
    clip = g.clip_source_nodes()[0]
    clip.set_media_info(320, 180, 30.0, 2.0)
    src = np.full((180, 320, 3), 120, np.uint8)
    cw, ch, _ = g.canvas_params()

    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
    a = g.evaluate(ctx)
    b = g.evaluate(ctx)
    ctx.release_all()
    assert a is b   # identical object -> cache hit
