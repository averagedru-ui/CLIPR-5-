"""ExportJob: render every output frame through the shared pipeline and pipe it
to ffmpeg. Runs on a worker thread; reports progress; cancellable.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from vcomp.core.graph import Graph
from vcomp.export.encoder import EncodeSpec, EncoderOption, FFmpegProcess, detect_encoders
from vcomp.media.decoder import VideoDecoder
from vcomp.render.frame_pipeline import render_graph_frame

log = logging.getLogger("vcomp.export")


@dataclass
class ExportRequest:
    graph_dict: dict            # serialized graph snapshot
    source_path: str
    out_path: str
    width: int
    height: int
    fps: int
    in_point: float
    out_point: float
    render_scale: float = 2.0
    encoder_key: str = "x264"
    crf: int = 18
    audio_bitrate: str = "192k"
    speed: float = 1.0


class ExportJob(QObject):
    progress = Signal(int, int, float, object)   # frame, total, fps, thumb(np|None)
    finished = Signal(bool, str)                  # ok, message

    def __init__(self, req: ExportRequest) -> None:
        super().__init__()
        self.req = req
        self._cancel = False
        self._thread = QThread()
        self._thread.setObjectName("ExportJob")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel = True

    def wait(self, ms: int = 30000) -> None:
        self._thread.quit()
        self._thread.wait(ms)

    # ------------------------------------------------------------------ run
    def _run(self) -> None:
        req = self.req
        comp = decoder = proc = None
        try:
            from vcomp.render.compositor import Compositor
            from vcomp.nodes.registry import load_builtin_nodes

            load_builtin_nodes()
            graph = Graph()
            graph.load_dict(req.graph_dict)
            clip_ids = [n.id for n in graph.clip_source_nodes()]
            for n in graph.clip_source_nodes():
                pass

            decoder = VideoDecoder(req.source_path)
            for n in graph.clip_source_nodes():
                n.set_media_info(decoder.info.display_width, decoder.info.display_height,
                                 decoder.info.fps, decoder.info.duration)

            comp = Compositor()

            enc = next((e for e in detect_encoders() if e.key == req.encoder_key),
                       detect_encoders()[0])
            spec = EncodeSpec(
                out_path=req.out_path, width=req.width, height=req.height, fps=req.fps,
                encoder=enc, crf=req.crf, audio_bitrate=req.audio_bitrate,
                source_path=req.source_path, in_point=req.in_point,
                out_point=req.out_point, speed=req.speed,
            )
            proc = FFmpegProcess(spec)
            proc.start()

            total = max(1, round((req.out_point - req.in_point) * req.fps))
            t0 = time.time()
            for n in range(total):
                if self._cancel:
                    proc.cancel()
                    self.finished.emit(False, "cancelled")
                    return
                t = req.in_point + n / req.fps
                frame = decoder.frame_at(t)
                frames = {cid: frame for cid in clip_ids}
                arr = render_graph_frame(comp, graph, frames, t,
                                         render_scale=req.render_scale)
                arr = _ensure_rgba(arr, req.width, req.height)
                proc.write_frame(np.ascontiguousarray(arr).tobytes())

                if n % 8 == 0 or n == total - 1:
                    elapsed = time.time() - t0
                    fps = (n + 1) / elapsed if elapsed > 0 else 0.0
                    thumb = arr[::6, ::6, :3].copy() if n % 24 == 0 else None
                    self.progress.emit(n + 1, total, fps, thumb)

            rc = proc.finish()
            if rc != 0:
                self.finished.emit(False, f"ffmpeg exited {rc}\n{proc.stderr_tail}")
            else:
                self.finished.emit(True, req.out_path)
        except Exception as exc:  # noqa: BLE001
            log.exception("export failed")
            if proc:
                proc.cancel()
            self.finished.emit(False, str(exc))
        finally:
            if decoder:
                decoder.close()
            if comp:
                comp.release()


def _ensure_rgba(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    if arr.shape[2] == 3:
        rgba = np.empty((arr.shape[0], arr.shape[1], 4), np.uint8)
        rgba[..., :3] = arr
        rgba[..., 3] = 255
        arr = rgba
    if arr.shape[1] != w or arr.shape[0] != h:
        yi = (np.arange(h) * (arr.shape[0] / h)).astype(np.int64)
        xi = (np.arange(w) * (arr.shape[1] / w)).astype(np.int64)
        arr = arr[yi][:, xi]
    return arr


def render_single_frame(graph_dict: dict, source_path: str, frame_index: int,
                        fps: float, render_scale: float = 2.0,
                        compositor=None) -> np.ndarray:
    """Headless single-frame render through the EXACT export path (used by the
    golden-frame test and 'export current frame as PNG'). Pass ``compositor`` to
    reuse an existing GL context; otherwise a throwaway one is created."""
    from vcomp.nodes.registry import load_builtin_nodes

    load_builtin_nodes()
    graph = Graph()
    graph.load_dict(graph_dict)
    decoder = VideoDecoder(source_path)
    for n in graph.clip_source_nodes():
        n.set_media_info(decoder.info.display_width, decoder.info.display_height,
                         decoder.info.fps, decoder.info.duration)

    own = compositor is None
    if own:
        from vcomp.render.compositor import Compositor

        compositor = Compositor()
    try:
        t = frame_index / fps
        frame = decoder.frame_at(t)
        frames = {n.id: frame for n in graph.clip_source_nodes()}
        return render_graph_frame(compositor, graph, frames, t, render_scale=render_scale)
    finally:
        decoder.close()
        if own:
            compositor.release()
