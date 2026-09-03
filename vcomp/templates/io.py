""".vctpl template read / write / apply.

A ``.vctpl`` is a JSON document: a serialized node graph (with Clip Source file
paths stripped) plus metadata and a reference resolution. Applying one remaps
every HUD Region's source rect from the template's reference resolution to the
current clip's resolution (spec 8).
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vcomp.core import coords
from vcomp.core.graph import Connection, Graph
from vcomp.util import paths

log = logging.getLogger("vcomp.templates")

FORMAT = "vctpl"
VERSION = 1


@dataclass
class TemplateMeta:
    name: str = "Untitled"
    game: str = ""
    author: str = "local"
    created: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    thumbnail_b64: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "game": self.game, "author": self.author,
            "created": self.created or datetime.now(timezone.utc).isoformat(),
            "tags": list(self.tags), "notes": self.notes,
            "thumbnail": self.thumbnail_b64,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TemplateMeta":
        return cls(
            name=d.get("name", "Untitled"), game=d.get("game", ""),
            author=d.get("author", "local"), created=d.get("created", ""),
            tags=list(d.get("tags", [])), notes=d.get("notes", ""),
            thumbnail_b64=d.get("thumbnail", ""),
        )


@dataclass
class Template:
    meta: TemplateMeta
    reference_resolution: tuple[int, int]
    canvas: tuple[int, int, int]              # w, h, fps
    graph: dict                               # serialized graph
    path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": VERSION,
            "meta": self.meta.to_dict(),
            "reference_resolution": {"width": self.reference_resolution[0],
                                     "height": self.reference_resolution[1]},
            "canvas": {"width": self.canvas[0], "height": self.canvas[1],
                       "fps": self.canvas[2]},
            "graph": self.graph,
        }


# --------------------------------------------------------------- migration
_MIGRATIONS: dict[int, "callable"] = {}


def _migrate(data: dict) -> dict:
    v = int(data.get("version", 1))
    while v < VERSION:
        fn = _MIGRATIONS.get(v)
        if fn is None:
            break
        data = fn(data)
        v = int(data.get("version", v + 1))
    return data


# --------------------------------------------------------------------- IO
def save_template(tpl: Template, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(tpl.to_dict(), indent=2), encoding="utf-8")
    tpl.path = path
    return path


def load_template(path: str | Path) -> Template:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError(f"{path} is not a .vctpl file")
    data = _migrate(data)
    rr = data.get("reference_resolution", {"width": 1920, "height": 1080})
    cv = data.get("canvas", {"width": 1080, "height": 1920, "fps": 30})
    return Template(
        meta=TemplateMeta.from_dict(data.get("meta", {})),
        reference_resolution=(int(rr["width"]), int(rr["height"])),
        canvas=(int(cv["width"]), int(cv["height"]), int(cv["fps"])),
        graph=data.get("graph", {"nodes": [], "connections": []}),
        path=path,
    )


def template_from_graph(graph: Graph, meta: TemplateMeta,
                        reference_resolution: tuple[int, int]) -> Template:
    gd = graph.to_dict()
    for node in gd["nodes"]:
        if node["type"] == "Clip Source" and "file_path" in node["params"]:
            node["params"]["file_path"]["value"] = ""
    cw, ch, _ = graph.canvas_params()
    fps_p = graph.output_node().params["fps"].value
    fps = int(fps_p) if str(fps_p).isdigit() else 30
    return Template(meta, reference_resolution, (cw, ch, fps), gd)


# --------------------------------------------------------------- apply
def apply_template(graph: Graph, tpl: Template, clip_resolution: tuple[int, int]
                   ) -> list[str]:
    """Replace ``graph`` with the template, remapping HUD Region rects and
    preserving the existing Clip Source(s). Returns a list of warnings."""
    warnings: list[str] = []

    old_clips = [
        {
            "file_path": n.params["file_path"].value,
            "in_point": n.params["in_point"].value,
            "out_point": n.params["out_point"].value,
            "speed": n.params["speed"].value,
            "media": (n.media_w, n.media_h, n.media_fps, n.media_duration),
        }
        for n in graph.clip_source_nodes()
    ]

    ref_res = tpl.reference_resolution
    from_ar = ref_res[0] / ref_res[1]
    to_ar = clip_resolution[0] / clip_resolution[1]

    graph.load_dict(tpl.graph)

    # remap HUD Region + Facecam source rects
    for node in graph.nodes.values():
        if node.type_name not in ("HUD Region", "Facecam"):
            continue
        rect = tuple(node.params["source_rect"].value)
        placement = coords.RegionPlacement(
            anchor=node.params["anchor"].value if "anchor" in node.params else "top-left",
            size_mode=node.params["size_mode"].value if "size_mode" in node.params else "relative",
            reference_height=int(node.params["reference_height"].value)
            if "reference_height" in node.params else ref_res[1],
            ultrawide_policy=node.params["ultrawide_policy"].value
            if "ultrawide_policy" in node.params else "pin_to_edge",
        )
        new_rect = coords.remap_region(rect, ref_res, clip_resolution, placement)
        node.params["source_rect"].set(new_rect)
        # Pin the region's authoring reference height so its on-canvas placement
        # is stable regardless of the clip resolution it's applied to.
        if "reference_height" in node.params:
            node.params["reference_height"].set(int(ref_res[1]))

    # restore Clip Source identity
    new_clips = graph.clip_source_nodes()
    for i, cn in enumerate(new_clips):
        if i < len(old_clips):
            oc = old_clips[i]
            cn.params["file_path"].set(oc["file_path"])
            cn.params["in_point"].set(oc["in_point"])
            cn.params["out_point"].set(oc["out_point"])
            cn.params["speed"].set(oc["speed"])
            cn.set_media_info(*oc["media"])

    if abs(from_ar - to_ar) > 0.02:
        warnings.append(
            f"Source aspect {to_ar:.2f} differs from template {from_ar:.2f} - "
            "regions pinned to edges; verify placements.")
    return warnings
