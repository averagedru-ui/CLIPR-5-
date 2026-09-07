"""Multi-track audio: probe detection, timeline lanes, export mixing."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VCOMP_SKIP_GUI") == "1", reason="GUI")


@pytest.fixture()
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _tracks(n):
    from vcomp.media.probe import AudioStreamInfo

    return [AudioStreamInfo(i, 2, 48000, "aac", f"trk{i}") for i in range(n)]


def test_timeline_lanes_and_active_tracks(app):
    from vcomp.ui.timeline import Timeline

    tl = Timeline()
    tl.set_media(300, 60.0)

    tl.set_audio_tracks(_tracks(1), "")        # single track -> no lanes, default [0]
    assert tl._lanes == [] and tl.active_audio_tracks() == [0]

    tl.set_audio_tracks(_tracks(6), "")
    assert len(tl._lanes) == 6
    assert tl.active_audio_tracks() == [0, 1, 2, 3, 4, 5]

    tl._lanes[1].btn_m.setChecked(True)
    tl._lanes[3].btn_m.setChecked(True)
    assert tl.active_audio_tracks() == [0, 2, 4, 5]

    tl._lanes[5].btn_s.setChecked(True)        # solo overrides mutes
    assert tl.active_audio_tracks() == [5]


def test_encoder_mixes_selected_tracks():
    from vcomp.export.encoder import EncodeSpec, EncoderOption, FFmpegProcess

    enc = EncoderOption("x264", "x", "libx264", ["-preset", "slow"])
    s = EncodeSpec(out_path="o.mp4", width=1080, height=1920, fps=30, encoder=enc,
                   source_path="in.mp4", audio_tracks=(1, 3, 5))
    args = " ".join(FFmpegProcess(s).build_args())
    assert "amix=inputs=3" in args
    assert "[1:a:1][1:a:3][1:a:5]" in args
    assert "-map [aout]" in args

    s1 = EncodeSpec(out_path="o.mp4", width=1080, height=1920, fps=30, encoder=enc,
                    source_path="in.mp4", audio_tracks=(2,))
    args1 = " ".join(FFmpegProcess(s1).build_args())
    assert "-map 1:a:2?" in args1 and "amix" not in args1


def test_probe_reports_audio_tracks(cfr8_clip):
    from vcomp.media.probe import probe

    info = probe(str(cfr8_clip))
    assert info.has_audio
    assert len(info.audio_tracks) == 1
    assert info.audio_tracks[0].sample_rate > 0
