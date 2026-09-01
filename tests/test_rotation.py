"""Container rotation: detect display-matrix rotation, apply it on decode,
and honour a Clip Source override."""
from __future__ import annotations

import numpy as np

from vcomp.media import probe as probe_mod
from vcomp.media.decoder import VideoDecoder
from vcomp.media.probe import probe


def test_detect_rotation_parses_ffmpeg_output(monkeypatch):
    class _Res:
        stderr = "  Stream #0:0(und): Video: h264\n    Side data:\n" \
                 "      displaymatrix: rotation of -90.00 degrees\n"

    monkeypatch.setattr(probe_mod.subprocess, "run", lambda *a, **k: _Res())
    assert probe_mod.detect_rotation("x.mp4") == 90

    _Res.stderr = "displaymatrix: rotation of 180.00 degrees"
    assert probe_mod.detect_rotation("x.mp4") == 180

    _Res.stderr = "nothing here"
    assert probe_mod.detect_rotation("x.mp4") == 0


def test_no_rotation_by_default(cfr_clip):
    info = probe(cfr_clip)
    assert info.rotation == 0
    assert (info.display_width, info.display_height) == (info.width, info.height)


def test_decoder_applies_rotation(cfr_clip):
    plain = VideoDecoder(cfr_clip)
    raw = plain.frame_at(0.0)
    plain.close()

    r90 = VideoDecoder(cfr_clip, rotation=90)
    rot = r90.frame_at(0.0)
    r90.close()

    assert rot.shape[0] == raw.shape[1] and rot.shape[1] == raw.shape[0]
    # 90 CW then 90 CCW restores the original
    assert np.array_equal(np.rot90(rot, k=1), raw)


def test_override_none_ignores_rotation(cfr_clip, monkeypatch):
    monkeypatch.setattr(probe_mod, "detect_rotation", lambda *a, **k: 90)
    forced = VideoDecoder(cfr_clip, rotation=0)
    assert forced._rotation == 0
    auto = VideoDecoder(cfr_clip)
    assert auto._rotation == 90
    forced.close()
    auto.close()
