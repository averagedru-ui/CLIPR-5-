"""M8: autosave/recovery, Guides node, headless --render CLI."""
from __future__ import annotations

import time

import pytest

from vcomp.core.graph import Graph, build_default_graph
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()


def test_autosave_prune_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from vcomp.core import autosave
    from vcomp.core.project import Project

    g = Graph()
    build_default_graph(g)
    for i in range(8):
        autosave.write_autosave(Project(graph=g))
        time.sleep(1.05)   # timestamped filenames are per-second

    files = list(autosave._dir().glob("autosave_*.vcproj"))
    assert len(files) == autosave.KEEP
    assert autosave.pending_recovery() is not None
    autosave.clear_recovery()
    assert autosave.pending_recovery() is None


def test_guides_node_passthrough(compositor):
    from vcomp.core.graph import EvalContext

    g = Graph()
    bg = g.add_node("Solid Background")
    guides = g.add_node("Guides")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(bg.id, "image", guides.id, "image")
    g.connect(guides.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(bg.id, "color", (0.4, 0.2, 0.1, 1.0))
    g.set_param(out.id, "background_clear_color", (0, 0, 0, 1))

    cw, ch, _ = g.canvas_params()
    ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {})
    res = g.evaluate(ctx)
    ctx.release_all()
    assert abs(int(res[960, 540, 0]) - 102) < 3     # 0.4 * 255, unchanged


@pytest.mark.slow
def test_render_cli(cfr_clip, tmp_path):
    import main
    from vcomp.core.project import Project

    g = Graph()
    build_default_graph(g)
    g.clip_source_nodes()[0].params["file_path"].set(str(cfr_clip))
    proj = Project(graph=g, in_point=0, out_point=45)
    pj = tmp_path / "p.vcproj"
    proj.save(pj)

    out = tmp_path / "cli_out.mp4"
    rc = main.main(["--render", str(pj), str(out)])
    assert rc == 0
    assert out.exists() and out.stat().st_size > 1000
