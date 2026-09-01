"""M6: golden-frame WYSIWYG, ffmpeg command, export integration, deadlock."""
from __future__ import annotations

import time

import av
import numpy as np
import pytest

from vcomp.core.graph import Graph, build_default_graph
from vcomp.export.encoder import EncodeSpec, EncoderOption, _atempo_chain
from vcomp.export.job import ExportJob, ExportRequest, render_single_frame
from vcomp.nodes.registry import load_builtin_nodes
from vcomp.render.frame_pipeline import render_graph_frame

load_builtin_nodes()


# --------------------------------------------------------- ffmpeg command
def test_atempo_chain():
    assert _atempo_chain(1.5) == "atempo=1.5000"
    assert _atempo_chain(4.0).count("atempo") == 2      # 2.0 * 2.0
    assert _atempo_chain(0.25).count("atempo") == 2


def test_build_args_has_required_flags():
    enc = EncoderOption("x264", "x", "libx264", ["-preset", "slow", "-crf", "18"])
    spec = EncodeSpec(out_path="o.mp4", width=1080, height=1920, fps=30, encoder=enc,
                      source_path="in.mp4", in_point=1.0, out_point=3.0)
    from vcomp.export.encoder import FFmpegProcess

    args = FFmpegProcess(spec).build_args()
    s = " ".join(args)
    assert "-pix_fmt yuv420p" in s
    assert "-f rawvideo -pixel_format rgba" in s
    assert "-video_size 1080x1920" in s
    assert "-map 1:a:0?" in s
    assert "-movflags +faststart" in s
    assert s.endswith("o.mp4")
    assert "-ss 1.0" in s and "-to 3.0" in s


# ------------------------------------------------------------ golden frame
def _graph_dict():
    g = Graph()
    build_default_graph(g)
    bg = [n for n in g.nodes.values() if n.type_name == "Solid Background"][0]
    g.set_param(bg.id, "color", (0.12, 0.14, 0.2, 1.0))
    return g.to_dict()


def test_golden_frame_preview_equals_export(compositor, cfr_clip):
    """Preview path and export path must render the same frame (spec 1.6 / 11)."""
    gd = _graph_dict()
    g = Graph()
    g.load_dict(gd)
    from vcomp.media.decoder import VideoDecoder

    dec = VideoDecoder(str(cfr_clip))
    for n in g.clip_source_nodes():
        n.set_media_info(dec.info.width, dec.info.height, dec.info.fps, dec.info.duration)
    fps = dec.info.fps
    frame = dec.frame_at(100 / fps)
    frames = {n.id: frame for n in g.clip_source_nodes()}

    preview = render_graph_frame(compositor, g, frames, 100 / fps, render_scale=1.0)
    export = render_single_frame(gd, str(cfr_clip), 100, fps, render_scale=1.0,
                                 compositor=compositor)
    dec.close()

    diff = np.abs(preview.astype(np.int16) - export.astype(np.int16))
    assert diff.mean() < 1.0        # < 1/255
    assert diff.max() < 2           # < 2/255


def test_supersample_stays_close(compositor, cfr_clip):
    gd = _graph_dict()
    export1 = render_single_frame(gd, str(cfr_clip), 100, 30.0, render_scale=1.0,
                                  compositor=compositor)
    export2 = render_single_frame(gd, str(cfr_clip), 100, 30.0, render_scale=2.0,
                                  compositor=compositor)
    d = np.abs(export1.astype(np.int16) - export2.astype(np.int16))
    assert d.mean() < 6.0          # supersampling should not shift the image


# -------------------------------------------------------- export run
def _run_job(req, timeout=90):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    job = ExportJob(req)
    result = {}
    job.finished.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    job.start()
    end = time.time() + timeout
    while "ok" not in result and time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    job.wait()
    return result


@pytest.mark.slow
def test_export_integration(cfr_clip, tmp_path):
    g = Graph()
    build_default_graph(g)
    out = tmp_path / "out.mp4"
    req = ExportRequest(
        graph_dict=g.to_dict(), source_path=str(cfr_clip), out_path=str(out),
        width=270, height=480, fps=30, in_point=0.0, out_point=2.0,
        render_scale=1.0, encoder_key="x264", crf=23,
    )
    res = _run_job(req)
    assert res.get("ok"), res.get("msg")
    assert out.exists() and out.stat().st_size > 1000

    with av.open(str(out)) as c:
        v = c.streams.video[0]
        assert (v.codec_context.width, v.codec_context.height) == (270, 480)
        assert v.codec_context.pix_fmt == "yuv420p"
        assert c.streams.audio, "audio stream missing"
        dur = float(v.duration * v.time_base)
        assert 1.8 < dur < 2.2
        n = sum(1 for _ in c.decode(video=0))
        assert n >= 55


@pytest.mark.slow
def test_export_no_deadlock_longer(cfr8_clip, tmp_path):
    g = Graph()
    build_default_graph(g)
    out = tmp_path / "long.mp4"
    req = ExportRequest(
        graph_dict=g.to_dict(), source_path=str(cfr8_clip), out_path=str(out),
        width=180, height=320, fps=30, in_point=0.0, out_point=8.0,
        render_scale=1.0, encoder_key="x264", crf=28,
    )
    res = _run_job(req, timeout=180)
    assert res.get("ok"), res.get("msg")


def test_export_cancel(cfr8_clip, tmp_path):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    g = Graph()
    build_default_graph(g)
    out = tmp_path / "cancel.mp4"
    req = ExportRequest(
        graph_dict=g.to_dict(), source_path=str(cfr8_clip), out_path=str(out),
        width=180, height=320, fps=30, in_point=0.0, out_point=8.0, render_scale=1.0,
    )
    job = ExportJob(req)
    result = {}
    job.finished.connect(lambda ok, msg: result.update(ok=ok, msg=msg))
    job.start()
    t0 = time.time()
    while "ok" not in result and time.time() - t0 < 30:
        app.processEvents()
        time.sleep(0.02)
        if time.time() - t0 > 0.3:
            job.cancel()
    job.wait()
    assert result.get("ok") is False
    assert not out.exists()          # partial file deleted
