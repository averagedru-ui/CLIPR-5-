"""Programmatically-built starter templates (spec 8.5).

Generic, sensible HUD positions - the user refines them. Regions are authored
against a 1920x1080 reference.
"""
from __future__ import annotations

from vcomp.core.graph import Graph
from vcomp.templates.io import Template, TemplateMeta, template_from_graph

REF = (1920, 1080)


def _base_graph(background: str = "Blur Background") -> tuple[Graph, str, str]:
    g = Graph()
    clip = g.add_node("Clip Source")
    framing = g.add_node("Main Framing")
    bg = g.add_node(background)
    stack = g.add_node("Stack")
    out = g.ensure_output()
    g.connect(clip.id, "image", framing.id, "image")
    if background == "Blur Background":
        g.connect(clip.id, "image", bg.id, "image")
    g.connect(bg.id, "image", stack.id, "layers")        # bottom
    g.connect(framing.id, "image", stack.id, "layers")   # gameplay band
    g.connect(stack.id, "image", out.id, "image")
    g.connect(clip.id, "audio", out.id, "audio")
    return g, clip.id, stack.id


def _add_region(g: Graph, clip_id: str, stack_id: str, *, label: str,
                source_rect, anchor: str, dest_x: float, dest_y: float,
                scale: float = 1.0, shape: str = "rect") -> None:
    r = g.add_node("HUD Region", title=label)
    g.set_param(r.id, "label", label)
    g.set_param(r.id, "source_rect", source_rect)
    g.set_param(r.id, "anchor", anchor)
    g.set_param(r.id, "shape", shape)
    g.set_param(r.id, "dest_x", dest_x)
    g.set_param(r.id, "dest_y", dest_y)
    g.set_param(r.id, "dest_scale", scale)
    g.set_param(r.id, "feather", 0.0)
    g.connect(clip_id, "image", r.id, "image")
    g.connect(r.id, "image", stack_id, "layers")


# each entry: (name, game, tags, [regions])
_CORNER = {
    "minimap": dict(source_rect=(0.0, 0.0, 0.17, 0.30), anchor="top-left",
                    dest_x=0.22, dest_y=0.09, shape="rect"),
    "ammo": dict(source_rect=(0.86, 0.86, 0.14, 0.14), anchor="bottom-right",
                 dest_x=0.82, dest_y=0.93),
    "health": dict(source_rect=(0.30, 0.88, 0.24, 0.10), anchor="bottom-center",
                   dest_x=0.5, dest_y=0.95),
    "killfeed": dict(source_rect=(0.70, 0.06, 0.30, 0.20), anchor="top-right",
                     dest_x=0.72, dest_y=0.10),
    "abilities": dict(source_rect=(0.36, 0.90, 0.28, 0.09), anchor="bottom-center",
                      dest_x=0.5, dest_y=0.90),
}

_GAMES: list[tuple[str, str, list[str], list[str]]] = [
    ("Valorant - Top HUD + Minimap", "Valorant", ["fps", "valorant", "1080p"],
     ["minimap", "killfeed", "abilities", "health"]),
    ("Apex Legends - Corners", "Apex Legends", ["fps", "apex", "br"],
     ["minimap", "ammo", "health", "killfeed"]),
    ("Fortnite - Minimap + Materials", "Fortnite", ["br", "fortnite"],
     ["minimap", "ammo", "health"]),
    ("R6 Siege - Ping + Ammo", "R6 Siege", ["fps", "siege"],
     ["killfeed", "ammo", "health"]),
    ("Overwatch - Ults + Health", "Overwatch", ["fps", "overwatch", "hero"],
     ["abilities", "health", "killfeed"]),
    ("Rocket League - Boost + Clock", "Rocket League", ["sports", "rl"],
     ["health", "killfeed"]),
    ("The Finals - Cashout + Ammo", "The Finals", ["fps", "thefinals"],
     ["minimap", "ammo", "health"]),
    ("Battlefield - Minimap + Tickets", "Battlefield", ["fps", "battlefield"],
     ["minimap", "ammo", "killfeed"]),
    ("Arc Raiders - Corners", "Arc Raiders", ["pve", "arcraiders"],
     ["minimap", "ammo", "health"]),
]


def _add_facecam(g: Graph, clip_id: str, stack_id: str) -> None:
    fc = g.add_node("Facecam", title="Facecam")
    g.set_param(fc.id, "source_rect", (0.0, 0.72, 0.22, 0.28))   # bottom-left PiP
    g.set_param(fc.id, "placement", "top-right")
    g.set_param(fc.id, "size", 0.34)
    g.set_enabled(fc.id, False)                                  # off until toggled
    g.connect(clip_id, "image", fc.id, "image")
    g.connect(fc.id, "image", stack_id, "layers")


def build_all() -> list[Template]:
    out: list[Template] = []

    for name, game, tags, region_keys in _GAMES:
        g, clip_id, stack_id = _base_graph("Blur Background")
        slot_y = 0.06
        for key in region_keys:
            spec = dict(_CORNER[key])
            _add_region(g, clip_id, stack_id, label=key.title(), **spec)
        _add_facecam(g, clip_id, stack_id)
        meta = TemplateMeta(name=name, game=game, tags=tags,
                            notes="Generic HUD positions - refine per your UI scale.")
        out.append(template_from_graph(g, meta, REF))

    # Generic Corners - four empty regions ready to drag
    g, clip_id, stack_id = _base_graph("Blur Background")
    for i, (label, anchor, dx, dy) in enumerate([
        ("Corner TL", "top-left", 0.2, 0.08), ("Corner TR", "top-right", 0.8, 0.08),
        ("Corner BL", "bottom-left", 0.2, 0.92), ("Corner BR", "bottom-right", 0.8, 0.92),
    ]):
        _add_region(g, clip_id, stack_id, label=label,
                    source_rect=(0.02 + 0.8 * (i % 2), 0.02 + 0.8 * (i // 2), 0.16, 0.16),
                    anchor=anchor, dest_x=dx, dest_y=dy)
    _add_facecam(g, clip_id, stack_id)
    out.append(template_from_graph(
        g, TemplateMeta(name="Generic Corners", game="", tags=["generic"],
                        notes="Four empty corner regions + a disabled webcam overlay."), REF))

    # simplest possible: blur bg + centered gameplay, no regions
    g, clip_id, stack_id = _base_graph("Blur Background")
    _add_facecam(g, clip_id, stack_id)
    out.append(template_from_graph(
        g, TemplateMeta(name="Blur Background + Centered Gameplay", game="",
                        tags=["minimal"],
                        notes="No HUD regions - the simplest start. Webcam overlay "
                              "included but disabled."),
        REF))
    return out


def _bundled_dir():
    from pathlib import Path

    from vcomp.util import paths

    d = Path(paths.resource_path("vcomp", "templates", "builtin"))
    return d if d.is_dir() else None


def install_builtins(dest_dir) -> int:
    """Populate ``dest_dir`` with any missing built-in templates. Prefers copying
    the shipped ``.vctpl`` files; falls back to building them in memory."""
    import shutil
    from pathlib import Path

    from vcomp.templates.io import save_template

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0

    bundled = _bundled_dir()
    if bundled and bundled != dest:
        for src in bundled.glob("*.vctpl"):
            if not (dest / src.name).exists():
                shutil.copy2(src, dest / src.name)
                written += 1
        if written or list(dest.glob("*.vctpl")):
            return written

    for tpl in build_all():
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in tpl.meta.name)
        target = dest / f"{safe}.vctpl"
        if not target.exists():
            save_template(tpl, target)
            written += 1
    return written
