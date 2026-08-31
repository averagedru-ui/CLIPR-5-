"""Blend-mode enum. GLSL side lives in ``shaders/lib_blend.glsl``; the integer
values here MUST match the ``if`` ladder there.
"""
from __future__ import annotations

from enum import IntEnum


class BlendMode(IntEnum):
    NORMAL = 0
    ADD = 1
    SCREEN = 2
    MULTIPLY = 3
    OVERLAY = 4
    SOFT_LIGHT = 5
    DARKEN = 6
    LIGHTEN = 7

    @classmethod
    def from_name(cls, name: str) -> "BlendMode":
        return cls[name.upper().replace("-", "_").replace(" ", "_")]
