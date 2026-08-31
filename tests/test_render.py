"""M2: offscreen GL context, FBO pool, layer shader, blend modes, readback."""
from __future__ import annotations

import numpy as np
import pytest

moderngl = pytest.importorskip("moderngl")

try:
    from vcomp.render.context import RenderContext

    _ctx = RenderContext()
    _GL_OK = True
except Exception as exc:  # noqa: BLE001
    _GL_OK = False
    _GL_ERR = str(exc)

pytestmark = pytest.mark.skipif(not _GL_OK, reason="no usable GL context")


@pytest.fixture(scope="module")
def ctx() -> "RenderContext":
    return _ctx


@pytest.fixture(scope="module")
def compositor(ctx):
    from vcomp.render.compositor import Compositor

    return Compositor(ctx)


def test_fbo_pool_reuse(ctx):
    a = ctx.acquire_fbo(64, 64)
    ida = id(a)
    ctx.release_fbo(a)
    b = ctx.acquire_fbo(64, 64)
    assert id(b) == ida  # same object recycled
    ctx.release_fbo(b)


def test_letterbox_geometry():
    from vcomp.render.compositor import letterbox_dest

    x0, y0, x1, y1 = letterbox_dest(1080, 1920, 16 / 9)
    assert (x0, x1) == (0.0, 1.0)
    band = (y1 - y0) * 1920
    assert abs(band - 1080 * 9 / 16) < 1.0
    assert abs((y0 + y1) - 1.0) < 1e-6  # centred


def test_gameplay_on_solid(compositor):
    src = np.zeros((720, 1280, 3), np.uint8)
    src[:] = (40, 160, 220)
    out = compositor.render_gameplay_on_solid(src, 1080, 1920, bg_color=(0, 0, 0, 1))

    assert out.shape == (1920, 1080, 4)
    assert tuple(out[5, 5, :3]) == (0, 0, 0)          # letterbox band
    assert tuple(out[960, 540, :3]) == (40, 160, 220)  # gameplay centre


@pytest.mark.parametrize("mode,expected", [
    ("NORMAL", (255, 255, 255)),     # full-opacity src replaces bg
    ("ADD", (255, 255, 255)),
    ("MULTIPLY", (127, 127, 127)),   # grey * white = grey
    ("DARKEN", (127, 127, 127)),
    ("LIGHTEN", (255, 255, 255)),
])
def test_blend_modes(compositor, mode, expected):
    from vcomp.render.blend import BlendMode
    from vcomp.render.compositor import FrameSpec, LayerSpec

    src = np.full((16, 16, 3), 255, np.uint8)   # white layer
    spec = FrameSpec(
        canvas_w=32, canvas_h=32, bg_color=(0.5, 0.5, 0.5, 1.0),
        layers=[LayerSpec(dest=(0, 0, 1, 1), blend=BlendMode.from_name(mode))],
    )
    out = compositor.render_frame(spec, src)
    got = tuple(int(v) for v in out[16, 16, :3])
    assert all(abs(g - e) <= 2 for g, e in zip(got, expected)), (mode, got)


def test_readback_roundtrip(ctx):
    from vcomp.render.readback import read_fbo

    with ctx.fbo(8, 8) as f:
        f.use()
        f.clear(0.25, 0.5, 0.75, 1.0)
        arr = read_fbo(f)
    assert arr.shape == (8, 8, 4)
    assert all(abs(int(a) - b) <= 1 for a, b in zip(arr[0, 0], (64, 128, 191, 255)))
