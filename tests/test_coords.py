"""M4: coordinate conversions + resolution-independent region remapping."""
from __future__ import annotations

import pytest

from vcomp.core import coords
from vcomp.core.coords import RegionPlacement, remap_region


def test_norm_px_roundtrip():
    r = (0.1, 0.2, 0.3, 0.4)
    assert coords.px_to_norm(coords.norm_to_px(r, 1920, 1080), 1920, 1080) == pytest.approx(r)


def test_clamp_rect():
    assert coords.clamp_rect((0.9, 0.9, 0.5, 0.5)) == pytest.approx((0.5, 0.5, 0.5, 0.5))


def test_safe_area_ultrawide():
    x, y, w, h = coords.safe_area_16x9(3440, 1440)
    assert h == 1440
    assert abs(w - 1440 * 16 / 9) < 1
    assert abs(x - (3440 - w) / 2) < 1


@pytest.mark.parametrize("to_res", [(1920, 1080), (2560, 1440), (3840, 2160)])
def test_bottom_right_region_stays_bottom_right(to_res):
    """A minimap pinned bottom-right at 1080p must still touch the bottom-right
    corner at any 16:9 resolution."""
    src = (0.80, 0.74, 0.20, 0.26)   # touching BR corner, 1920x1080
    pl = RegionPlacement(anchor="bottom-right", size_mode="relative")
    out = remap_region(src, (1920, 1080), to_res, pl)
    assert out[0] + out[2] == pytest.approx(1.0, abs=1e-6)   # right edge
    assert out[1] + out[3] == pytest.approx(1.0, abs=1e-6)   # bottom edge


def test_relative_keeps_normalized_size():
    src = (0.0, 0.0, 0.25, 0.15)
    pl = RegionPlacement(anchor="top-left", size_mode="relative")
    out = remap_region(src, (1920, 1080), (2560, 1440), pl)
    assert out[2] == pytest.approx(0.25, abs=1e-6)
    assert out[3] == pytest.approx(0.15, abs=1e-6)


def test_fixed_scales_with_reference_height():
    src = (0.0, 0.0, 0.25, 0.15)      # 480x162 px at 1080
    pl = RegionPlacement(anchor="top-left", size_mode="fixed", reference_height=1080)
    out = remap_region(src, (1920, 1080), (2560, 1440), pl)
    # px scale by 1440/1080 = 1.333 -> 640x216 px; on a proportional 16:9 bump the
    # normalized size is therefore unchanged
    assert out[2] == pytest.approx(0.25, abs=2e-3)
    assert out[3] == pytest.approx(0.15, abs=2e-3)


def test_ultrawide_safe_area_pins_inside_16x9():
    src = (0.80, 0.0, 0.20, 0.10)     # top-right at 1080
    pl = RegionPlacement(anchor="top-right", size_mode="relative",
                         ultrawide_policy="pin_to_16x9_safe_area")
    out = remap_region(src, (1920, 1080), (3440, 1440), pl)
    safe = coords.safe_area_16x9(3440, 1440)
    right_edge_px = (out[0] + out[2]) * 3440
    assert right_edge_px == pytest.approx(safe[0] + safe[2], abs=2.0)
