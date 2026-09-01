""".vcproj project model: the graph plus clip paths, in/out, and UI state.

Media paths are stored both absolute and relative to the project file; on load
we try relative first, then absolute, then leave it for the app to prompt a
relink.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vcomp.core.graph import Graph

log = logging.getLogger("vcomp.project")

FORMAT = "vcproj"
VERSION = 1

_MIGRATIONS: dict[int, "callable"] = {}


@dataclass
class Project:
    graph: Graph = field(default_factory=Graph)
    path: Path | None = None
    ui_state: dict = field(default_factory=dict)
    in_point: int = 0
    out_point: int = 0

    # ------------------------------------------------------------------ save
    def to_dict(self) -> dict:
        base = self.path.parent if self.path else None
        gd = self.graph.to_dict()
        for node in gd["nodes"]:
            if node["type"] == "Clip Source":
                p = node["params"].get("file_path", {}).get("value", "")
                node["media"] = {
                    "abs": os.path.abspath(p) if p else "",
                    "rel": (os.path.relpath(p, base) if p and base else ""),
                }
        return {
            "format": FORMAT, "version": VERSION,
            "saved": datetime.now(timezone.utc).isoformat(),
            "in_point": self.in_point, "out_point": self.out_point,
            "ui_state": self.ui_state,
            "graph": gd,
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        self.path = path
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path) -> "Project":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT:
            raise ValueError(f"{path} is not a .vcproj file")
        data = _migrate(data)

        g = Graph()
        g.load_dict(data.get("graph", {"nodes": [], "connections": []}))

        # relink media
        base = path.parent
        for node in data.get("graph", {}).get("nodes", []):
            if node["type"] != "Clip Source":
                continue
            media = node.get("media", {})
            resolved = _resolve_media(media, base)
            gn = g.nodes.get(node["id"])
            if gn is not None and resolved:
                gn.params["file_path"].set(resolved)

        proj = cls(graph=g, path=path,
                   ui_state=data.get("ui_state", {}),
                   in_point=int(data.get("in_point", 0)),
                   out_point=int(data.get("out_point", 0)))
        return proj

    def missing_media(self) -> list[str]:
        out = []
        for n in self.graph.clip_source_nodes():
            p = n.params["file_path"].value
            if p and not os.path.exists(p):
                out.append(p)
        return out


def _resolve_media(media: dict, base: Path) -> str:
    rel, ab = media.get("rel", ""), media.get("abs", "")
    if rel:
        cand = (base / rel).resolve()
        if cand.exists():
            return str(cand)
    if ab and os.path.exists(ab):
        return ab
    return ab or rel


def _migrate(data: dict) -> dict:
    v = int(data.get("version", 1))
    while v < VERSION and v in _MIGRATIONS:
        data = _MIGRATIONS[v](data)
        v = int(data.get("version", v + 1))
    return data
