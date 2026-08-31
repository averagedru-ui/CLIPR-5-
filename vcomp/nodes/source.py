"""Input nodes."""
from __future__ import annotations

from typing import Any

from vcomp.core.params import Param, ParamType, WireType
from vcomp.nodes.base import VNode
from vcomp.nodes.registry import register


@register
class ClipSource(VNode):
    type_name = "Clip Source"
    category = "Input"
    title_default = "Clip Source"
    color = (70, 120, 90)

    def _define(self) -> None:
        self.add_param(Param("file_path", ParamType.FILEPATH, "", group="Clip",
                             tooltip="Source video file."))
        self.add_param(Param("in_point", ParamType.FLOAT, 0.0, min=0.0, group="Clip"))
        self.add_param(Param("out_point", ParamType.FLOAT, 0.0, min=0.0, group="Clip"))
        self.add_param(Param("speed", ParamType.FLOAT, 1.0, min=0.25, max=4.0, step=0.05,
                             group="Clip", tooltip="Playback rate; audio is time-stretched at export."))
        self.add_param(Param("loop", ParamType.BOOL, False, group="Clip"))
        self.add_param(Param("stabilize_timebase", ParamType.BOOL, True, group="Clip",
                             tooltip="Resample a VFR source onto a constant frame rate."))

        self.add_output("image", WireType.IMAGE)
        self.add_output("audio", WireType.AUDIO)
        for n in ("width", "height", "fps", "duration"):
            self.add_output(n, WireType.NUMBER)

        # populated by the app when a clip is loaded
        self.media_w = 0
        self.media_h = 0
        self.media_fps = 0.0
        self.media_duration = 0.0

    def set_media_info(self, w: int, h: int, fps: float, duration: float) -> None:
        self.media_w, self.media_h = w, h
        self.media_fps, self.media_duration = fps, duration

    def is_time_dependent(self) -> bool:
        return True

    def render(self, ctx, inputs: dict[str, Any]) -> dict[str, Any]:
        arr = ctx.frames.get(self.id)
        out: dict[str, Any] = {
            "width": float(self.media_w),
            "height": float(self.media_h),
            "fps": float(self.media_fps),
            "duration": float(self.media_duration),
            "audio": {"path": self.params["file_path"].value,
                      "in": self.params["in_point"].value,
                      "out": self.params["out_point"].value,
                      "speed": self.params["speed"].value},
        }
        if arr is not None:
            out["image"] = ctx.upload(arr)
        return out


@register
class ColorNode(VNode):
    type_name = "Color"
    category = "Input"
    title_default = "Color"
    color = (150, 140, 60)

    def _define(self) -> None:
        self.add_param(Param("color", ParamType.COLOR, (1.0, 1.0, 1.0, 1.0)))
        self.add_output("color", WireType.COLOR)

    def render(self, ctx, inputs) -> dict[str, Any]:
        return {"color": tuple(self.params["color"].value)}


@register
class ValueNode(VNode):
    type_name = "Value"
    category = "Input"
    title_default = "Value"
    color = (120, 120, 130)

    def _define(self) -> None:
        self.add_param(Param("value", ParamType.FLOAT, 0.0, step=0.01))
        self.add_output("value", WireType.NUMBER)

    def render(self, ctx, inputs) -> dict[str, Any]:
        return {"value": float(self.params["value"].value)}
