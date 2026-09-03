"""Timeline ruler seek, mask crop, blur strength, full-quality toggle."""
from __future__ import annotations

import os

import numpy as np
import pytest

from vcomp.core.graph import EvalContext, Graph
from vcomp.nodes.registry import load_builtin_nodes

load_builtin_nodes()

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI")


@pytest.fixture()
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_timeline_ruler_click_seeks(app):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from vcomp.ui.timeline import Timeline

    tl = Timeline()
    tl.set_media(200, 30.0)
    tl.ruler.resize(400, 40)
    got = []
    tl.frameChanged.connect(got.append)

    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(200, 20),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    tl.ruler.mousePressEvent(press)
    assert got and abs(got[-1] - 100) <= 2         # clicked mid-ruler -> ~frame 100


def test_mask_edge_crop(compositor):
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
    for k, v in dict(shape="rect", source_rect=(0.0, 0.0, 1.0, 1.0), dest_x=0.5,
                     dest_y=0.5, dest_anchor="center", dest_scale=2.0, feather=0.0,
                     reference_height=360).items():
        g.set_param(reg.id, k, v)

    src = np.full((360, 640, 3), (0, 200, 0), np.uint8)
    cw, ch, _ = g.canvas_params()

    def render():
        ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
        r = g.evaluate(ctx)
        ctx.release_all()
        return (r[..., 1] > 100).sum()

    full = render()
    g.set_param(reg.id, "crop_left", 0.3)
    g.set_param(reg.id, "crop_right", 0.3)
    cropped = render()
    assert cropped < full * 0.6            # trimming 60% of the width shrinks coverage


def test_blur_radius_increases_smoothing(compositor):
    g = Graph()
    clip = g.add_node("Clip Source")
    blur = g.add_node("Blur Background")
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", blur.id, "image")
    g.connect(blur.id, "image", stack.id, "layers")
    g.connect(stack.id, "image", out.id, "image")
    g.set_param(blur.id, "vignette_amount", 0.0)
    g.set_param(blur.id, "overlay_opacity", 0.0)
    g.set_param(blur.id, "brightness", 1.0)
    clip.set_media_info(640, 360, 30.0, 2.0)

    src = np.zeros((360, 640, 3), np.uint8)
    src[:, ::20] = 255                       # vertical stripes -> lots of high freq
    cw, ch, _ = g.canvas_params()

    def variance(radius):
        g.set_param(blur.id, "blur_radius", radius)
        ctx = EvalContext(compositor, 0.0, cw, ch, 1.0, {clip.id: src})
        r = g.evaluate(ctx)
        ctx.release_all()
        return float(r[400:1500, :, 0].astype(np.float32).var())

    assert variance(400) < variance(20) * 0.5     # heavy blur flattens the stripes


def test_full_quality_toggle(app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from vcomp.ui.main_window import MainWindow
    from vcomp.util.settings import Settings

    w = MainWindow(Settings())
    w.renderer.preview_scale = 0.25
    w.act_fullq.setChecked(True)
    assert w.renderer.lock_full_quality is True
    assert w.renderer.preview_scale == 1.0
    w.act_fullq.setChecked(False)
    assert w.renderer.lock_full_quality is False
    w.fetcher.stop()
    w.renderer.stop()
    w.close()
