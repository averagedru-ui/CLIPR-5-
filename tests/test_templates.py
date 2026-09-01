"""M7: .vctpl round-trip, apply + remap, built-ins, project save/load."""
from __future__ import annotations

import json

import pytest

from vcomp.core.graph import Graph, build_default_graph
from vcomp.core.project import Project
from vcomp.nodes.registry import load_builtin_nodes
from vcomp.templates import builtin
from vcomp.templates.io import (
    Template, TemplateMeta, apply_template, load_template, save_template,
    template_from_graph,
)

load_builtin_nodes()


def _graph_with_region():
    g = Graph()
    build_default_graph(g)
    clip = g.clip_source_nodes()[0]
    clip.params["file_path"].set("C:/games/clip.mp4")
    stack = [n for n in g.nodes.values() if n.type_name == "Stack"][0]
    r = g.add_node("HUD Region", title="Minimap")
    g.set_param(r.id, "source_rect", (0.80, 0.74, 0.20, 0.26))
    g.set_param(r.id, "anchor", "bottom-right")
    g.connect(clip.id, "image", r.id, "image")
    g.connect(r.id, "image", stack.id, "layers")
    return g, r.id


def test_vctpl_roundtrip(tmp_path):
    g, _ = _graph_with_region()
    tpl = template_from_graph(g, TemplateMeta(name="T", game="X", tags=["a"]), (1920, 1080))
    p = save_template(tpl, tmp_path / "t.vctpl")

    # file paths stripped
    raw = json.loads(p.read_text())
    for n in raw["graph"]["nodes"]:
        if n["type"] == "Clip Source":
            assert n["params"]["file_path"]["value"] == ""

    back = load_template(p)
    assert back.meta.name == "T"
    assert back.reference_resolution == (1920, 1080)
    assert len(back.graph["nodes"]) == len(g.nodes)


def test_apply_preserves_clip_and_remaps(tmp_path):
    g, rid = _graph_with_region()
    tpl = template_from_graph(g, TemplateMeta(name="T"), (1920, 1080))
    save_template(tpl, tmp_path / "t.vctpl")
    tpl = load_template(tmp_path / "t.vctpl")

    target = Graph()
    build_default_graph(target)
    tclip = target.clip_source_nodes()[0]
    tclip.params["file_path"].set("D:/other/match.mp4")
    tclip.params["in_point"].set(3.0)
    tclip.set_media_info(2560, 1440, 60.0, 90.0)

    warns = apply_template(target, tpl, (2560, 1440))

    tc = target.clip_source_nodes()[0]
    assert tc.params["file_path"].value == "D:/other/match.mp4"
    assert tc.params["in_point"].value == 3.0

    reg = [n for n in target.nodes.values() if n.type_name == "HUD Region"][0]
    x, y, w, h = reg.params["source_rect"].value
    assert x + w == pytest.approx(1.0, abs=1e-6)   # still bottom-right
    assert y + h == pytest.approx(1.0, abs=1e-6)
    assert warns == []                              # 16:9 -> 16:9, no banner


def test_apply_ultrawide_warns(tmp_path):
    g, _ = _graph_with_region()
    save_template(template_from_graph(g, TemplateMeta(name="T"), (1920, 1080)),
                  tmp_path / "t.vctpl")
    tpl = load_template(tmp_path / "t.vctpl")

    target = Graph()
    build_default_graph(target)
    target.clip_source_nodes()[0].set_media_info(3440, 1440, 60.0, 60.0)
    warns = apply_template(target, tpl, (3440, 1440))
    assert any("aspect" in w for w in warns)


def test_build_all_templates_valid():
    tpls = builtin.build_all()
    assert len(tpls) >= 10
    for t in tpls:
        g = Graph()
        g.load_dict(t.graph)          # must deserialize cleanly
        assert g.output_node() is not None
        assert g.clip_source_nodes()


def test_install_builtins(tmp_path):
    n = builtin.install_builtins(tmp_path)
    assert n >= 10
    assert builtin.install_builtins(tmp_path) == 0    # idempotent
    assert list(tmp_path.glob("*.vctpl"))


def test_project_roundtrip(tmp_path):
    clip = tmp_path / "movie.mp4"
    clip.write_bytes(b"x")
    g = Graph()
    build_default_graph(g)
    g.clip_source_nodes()[0].params["file_path"].set(str(clip))

    proj = Project(graph=g, in_point=10, out_point=200)
    p = proj.save(tmp_path / "sub" / "proj.vcproj") if (tmp_path / "sub").mkdir(
        exist_ok=True) or True else None

    loaded = Project.load(tmp_path / "sub" / "proj.vcproj")
    assert loaded.in_point == 10 and loaded.out_point == 200
    assert loaded.graph.clip_source_nodes()[0].params["file_path"].value == str(clip)
    assert loaded.missing_media() == []
