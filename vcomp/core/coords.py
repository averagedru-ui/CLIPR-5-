"""Coordinate systems and resolution-independent region remapping.

Three spaces, never mixed silently (spec 4.3):

* **source**  - normalized [0,1] over the source video frame
* **canvas**  - normalized [0,1] over the 9:16 output
* **pixel**   - only at the edges (viewport hit-testing, export)

Origin is **top-left** everywhere, matching image convention and the compositor.

``remap_region`` (spec 4.4) is what lets a HUD element authored at 1920x1080
land correctly on 2560x1440 or 3440x1440 footage; the template system calls it
on apply.
"""
from __future__ import annotations

from dataclasses import dataclass

Rect = tuple[float, float, float, float]   # x, y, w, h

ANCHORS: dict[str, tuple[float, float]] = {
    "top-left": (0.0, 0.0),
    "top-center": (0.5, 0.0),
    "top-right": (1.0, 0.0),
    "mid-left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "mid-right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0),
    "bottom-center": (0.5, 1.0),
    "bottom-right": (1.0, 1.0),
}

SIZE_MODES = ("relative", "fixed")
ULTRAWIDE_POLICIES = ("pin_to_edge", "pin_to_16x9_safe_area")


# --------------------------------------------------------------- basic maths
def norm_to_px(rect: Rect, w: int, h: int) -> Rect:
    x, y, rw, rh = rect
    return (x * w, y * h, rw * w, rh * h)


def px_to_norm(rect: Rect, w: int, h: int) -> Rect:
    x, y, rw, rh = rect
    return (x / w, y / h, rw / w, rh / h)


def anchor_uv(anchor: str) -> tuple[float, float]:
    return ANCHORS.get(anchor, (0.0, 0.0))


def clamp_rect(rect: Rect, lo: float = 0.0, hi: float = 1.0) -> Rect:
    x, y, w, h = rect
    w = max(0.0, min(w, hi - lo))
    h = max(0.0, min(h, hi - lo))
    x = max(lo, min(x, hi - w))
    y = max(lo, min(y, hi - h))
    return (x, y, w, h)


def rect_center(rect: Rect) -> tuple[float, float]:
    x, y, w, h = rect
    return (x + w / 2, y + h / 2)


def rect_corner(rect: Rect, anchor: str) -> tuple[float, float]:
    """Point on ``rect`` that corresponds to ``anchor`` (top-left origin)."""
    ax, ay = anchor_uv(anchor)
    x, y, w, h = rect
    return (x + ax * w, y + ay * h)


def rect_to_uvrect(rect: Rect) -> tuple[float, float, float, float]:
    """(x,y,w,h) -> (u0,v0,u1,v1)."""
    x, y, w, h = rect
    return (x, y, x + w, y + h)


# ------------------------------------------------------- ultrawide safe area
def safe_area_16x9(res_w: int, res_h: int) -> Rect:
    """Centred 16:9 rectangle inside a possibly-ultrawide frame, in px."""
    target = 16 / 9
    actual = res_w / res_h
    if actual > target:                      # wider than 16:9 -> pillarbox
        w = res_h * target
        return ((res_w - w) / 2, 0.0, w, float(res_h))
    h = res_w / target                       # taller than 16:9 -> letterbox
    return (0.0, (res_h - h) / 2, float(res_w), h)


# --------------------------------------------------------- region remapping
@dataclass(frozen=True)
class RegionPlacement:
    """Resolution-independent description of a source rect."""
    anchor: str = "top-left"
    size_mode: str = "relative"            # relative | fixed
    reference_height: int = 1080
    ultrawide_policy: str = "pin_to_edge"  # pin_to_edge | pin_to_16x9_safe_area


def encode_region(rect_norm: Rect, res_w: int, res_h: int,
                  placement: RegionPlacement) -> dict:
    """Capture a source rect (normalized, top-left origin) as an anchor-relative
    description that survives a resolution change."""
    frame = _policy_frame(placement.ultrawide_policy, res_w, res_h)
    fx, fy, fw, fh = frame
    ax, ay = anchor_uv(placement.anchor)
    anchor_px = (fx + ax * fw, fy + ay * fh)

    rpx = norm_to_px(rect_norm, res_w, res_h)
    corner_px = rect_corner(rpx, placement.anchor)
    offset_px = (corner_px[0] - anchor_px[0], corner_px[1] - anchor_px[1])

    return {
        "anchor": placement.anchor,
        "size_mode": placement.size_mode,
        "reference_height": placement.reference_height,
        "ultrawide_policy": placement.ultrawide_policy,
        "offset_px": offset_px,           # measured at (res_w, res_h)
        "size_px": (rpx[2], rpx[3]),
        "src_res": (res_w, res_h),
    }


def decode_region(enc: dict, res_w: int, res_h: int) -> Rect:
    """Inverse of :func:`encode_region` for a (possibly different) target res."""
    from_w, from_h = enc["src_res"]
    frame = _policy_frame(enc["ultrawide_policy"], res_w, res_h)
    fx, fy, fw, fh = frame
    ax, ay = anchor_uv(enc["anchor"])
    anchor_px = (fx + ax * fw, fy + ay * fh)

    if enc["size_mode"] == "fixed":
        s = res_h / max(1, enc["reference_height"])
        size_px = (enc["size_px"][0] * s, enc["size_px"][1] * s)
        off = (enc["offset_px"][0] * s, enc["offset_px"][1] * s)
    else:  # relative - scales with the resolution
        sx, sy = res_w / from_w, res_h / from_h
        size_px = (enc["size_px"][0] * sx, enc["size_px"][1] * sy)
        off = (enc["offset_px"][0] * sx, enc["offset_px"][1] * sy)

    corner_px = (anchor_px[0] + off[0], anchor_px[1] + off[1])
    top_left = (corner_px[0] - ax * size_px[0], corner_px[1] - ay * size_px[1])
    rect_px = (top_left[0], top_left[1], size_px[0], size_px[1])
    return clamp_rect(px_to_norm(rect_px, res_w, res_h))


def remap_region(rect_norm: Rect, from_res: tuple[int, int],
                 to_res: tuple[int, int], placement: RegionPlacement) -> Rect:
    """Convenience: encode at ``from_res`` then decode at ``to_res``."""
    enc = encode_region(rect_norm, from_res[0], from_res[1], placement)
    return decode_region(enc, to_res[0], to_res[1])


def _policy_frame(policy: str, res_w: int, res_h: int) -> Rect:
    if policy == "pin_to_16x9_safe_area":
        return safe_area_16x9(res_w, res_h)
    return (0.0, 0.0, float(res_w), float(res_h))
