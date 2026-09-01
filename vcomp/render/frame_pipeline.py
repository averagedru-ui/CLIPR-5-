"""The single frame-rendering entry point shared by preview and export.

Preview worker and the export job MUST both call :func:`render_graph_frame` so a
frame rendered for the timeline is byte-for-byte the same as the frame written
to the encoder at the same timestamp and render scale. The golden-frame test
(spec 11) enforces this.
"""
from __future__ import annotations

import numpy as np

from vcomp.core.graph import EvalContext, Graph


def render_graph_frame(compositor, graph: Graph, frames: dict[str, np.ndarray],
                       t: float, *, render_scale: float = 1.0,
                       thumbs: dict | None = None) -> np.ndarray:
    """Evaluate ``graph`` at time ``t`` and return the canvas-resolution RGBA
    array. ``frames`` maps Clip Source node id -> RGB frame for that timestamp.
    Pass ``thumbs`` (a dict) to have it filled with ``node_id -> small RGBA``.
    """
    cw, ch, _ = graph.canvas_params()
    ctx = EvalContext(compositor, t=t, canvas_w=cw, canvas_h=ch,
                      render_scale=render_scale, frames=frames, thumbs=thumbs)
    try:
        return graph.evaluate(ctx)
    finally:
        ctx.release_all()
